"""Fases 4 y 6: consolidacion del dataset. Todo local, sin red.

Fase 4  resolucion de member_id  (la FK que la pagina de perfume no trae)
Fase 6  dedup, integridad referencial, k-core iterativo, export
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import duckdb
from rich.console import Console
from rich.table import Table

from ..config import DATASET, DatasetConfig
from ..frontier import Frontier

console = Console()


@dataclass
class ConsolidationReport:
    interactions_raw: int = 0
    interactions_deduped: int = 0
    dropped_null_member: int = 0
    dropped_orphan_item: int = 0
    dropped_orphan_user: int = 0
    interactions_clean: int = 0
    items_clean: int = 0
    users_clean: int = 0
    kcore_interactions: int = 0
    kcore_items: int = 0
    kcore_users: int = 0
    kcore_iterations: int = 0
    orphan_item_ids: list[int] | None = None

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["orphan_item_ids"] = (self.orphan_item_ids or [])[:200]
        return d


def _glob(staging: Path, name: str) -> str | None:
    d = staging / name
    if not d.exists() or not any(d.glob("*.parquet")):
        return None
    return str(d / "*.parquet")


def consolidate(
    staging: Path,
    final: Path,
    frontier: Frontier,
    cfg: DatasetConfig = DATASET,
) -> ConsolidationReport:
    final.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    rep = ConsolidationReport()

    # ---- carga -----------------------------------------------------------
    sources = []
    if (p := _glob(staging, "interactions_from_perfume")):
        sources.append(p)
    if (p := _glob(staging, "interactions_from_profile")):
        sources.append(p)
    if not sources:
        raise RuntimeError("no hay interacciones en staging; corre las fases 2 y 3 primero")

    union = " UNION ALL BY NAME ".join(f"SELECT * FROM read_parquet('{s}')" for s in sources)
    con.execute(f"CREATE TABLE raw_inter AS {union}")
    rep.interactions_raw = con.execute("SELECT count(*) FROM raw_inter").fetchone()[0]

    # ---- Fase 4: resolucion de member_id ---------------------------------
    # La pagina de perfume no trae el member_id numerico, solo el username.
    # El mapa slug -> member_id se poblo al crawlear los perfiles.
    mapping = frontier.member_id_map()
    con.execute("CREATE TABLE slug_map (username_slug VARCHAR, member_id BIGINT)")
    if mapping:
        con.executemany(
            "INSERT INTO slug_map VALUES (?, ?)",
            [(k, v) for k, v in mapping.items()],
        )

    con.execute(
        """
        CREATE TABLE inter_resolved AS
        SELECT
            i.* REPLACE (COALESCE(i.member_id, m.member_id) AS member_id)
        FROM raw_inter i
        LEFT JOIN slug_map m USING (username_slug)
        """
    )

    # ---- dedup por (usuario, item) --------------------------------------
    # La misma review puede llegar por perfume_page y profile_page. Un voto
    # o un item de wardrobe pueden coexistir con esa review. El recomendador
    # quiere un par (user, item); se queda con la fila mas informativa.
    # Ojo: NO deduplicar solo por review_id. Los votos/wardrobe tienen
    # review_id NULL y un PARTITION BY review_id los colapsaria a una sola fila.
    con.execute(
        """
        CREATE TABLE inter_dedup AS
        SELECT * EXCLUDE (rn) FROM (
            SELECT *, row_number() OVER (
                PARTITION BY COALESCE(member_id, -1), perfume_id
                ORDER BY CASE source
                             WHEN 'profile_page' THEN 0
                             WHEN 'perfume_page' THEN 1
                             WHEN 'vote' THEN 2
                             WHEN 'wardrobe' THEN 3
                             ELSE 4
                         END,
                         review_id IS NULL,
                         rating IS NULL
            ) AS rn
            FROM inter_resolved
        ) WHERE rn = 1
        """
    )
    rep.interactions_deduped = con.execute("SELECT count(*) FROM inter_dedup").fetchone()[0]

    # ---- items y users ---------------------------------------------------
    items_src = _glob(staging, "items")
    if items_src:
        con.execute(
            f"""
            CREATE TABLE items AS
            SELECT * EXCLUDE (rn) FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY perfume_id ORDER BY reviews_scraped DESC
                ) AS rn FROM read_parquet('{items_src}')
            ) WHERE rn = 1
            """
        )
    else:
        con.execute("CREATE TABLE items AS SELECT NULL::BIGINT AS perfume_id WHERE false")

    users_src = _glob(staging, "users")
    if users_src:
        con.execute(
            f"""
            CREATE TABLE users AS
            SELECT * EXCLUDE (rn) FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY member_id ORDER BY n_reviews_scraped DESC
                ) AS rn FROM read_parquet('{users_src}')
            ) WHERE rn = 1
            """
        )
    else:
        # Esquema minimo para que el COPY del export no falle si la fase 3
        # todavia no corrio (el estado actual del slice).
        con.execute(
            """
            CREATE TABLE users AS
            SELECT NULL::BIGINT AS member_id,
                   NULL::VARCHAR AS username_slug,
                   NULL::VARCHAR AS username_display
            WHERE false
            """
        )

    # ---- integridad referencial ------------------------------------------
    rep.dropped_null_member = con.execute(
        "SELECT count(*) FROM inter_dedup WHERE member_id IS NULL"
    ).fetchone()[0]

    rep.orphan_item_ids = [
        r[0]
        for r in con.execute(
            """
            SELECT DISTINCT i.perfume_id
            FROM inter_dedup i LEFT JOIN items t USING (perfume_id)
            WHERE t.perfume_id IS NULL
            """
        ).fetchall()
    ]

    con.execute(
        """
        CREATE TABLE inter_clean AS
        SELECT i.* FROM inter_dedup i
        JOIN items t USING (perfume_id)
        JOIN users u USING (member_id)
        WHERE i.member_id IS NOT NULL AND i.perfume_id IS NOT NULL
        """
    )
    rep.interactions_clean = con.execute("SELECT count(*) FROM inter_clean").fetchone()[0]
    rep.dropped_orphan_item = len(rep.orphan_item_ids)

    # ---- k-core iterativo ------------------------------------------------
    # Aplicar los umbrales una sola vez no alcanza: al eliminar un usuario
    # desaparecen sus reviews, lo que puede tumbar un item por debajo del
    # minimo, lo que a su vez puede tumbar otro usuario. Hay que iterar hasta
    # punto fijo.
    con.execute("CREATE TABLE kcore AS SELECT * FROM inter_clean")
    iterations = 0
    while True:
        iterations += 1
        before = con.execute("SELECT count(*) FROM kcore").fetchone()[0]
        con.execute(
            f"""
            CREATE OR REPLACE TABLE kcore AS
            WITH ucount AS (
                SELECT member_id FROM kcore GROUP BY 1 HAVING count(*) >= {cfg.k_core}
            ), icount AS (
                SELECT perfume_id FROM kcore GROUP BY 1 HAVING count(*) >= {cfg.k_core}
            )
            SELECT k.* FROM kcore k
            JOIN ucount USING (member_id)
            JOIN icount USING (perfume_id)
            """
        )
        after = con.execute("SELECT count(*) FROM kcore").fetchone()[0]
        if after == before or after == 0 or iterations > 50:
            break

    rep.kcore_iterations = iterations
    rep.kcore_interactions = con.execute("SELECT count(*) FROM kcore").fetchone()[0]
    rep.kcore_users = con.execute("SELECT count(DISTINCT member_id) FROM kcore").fetchone()[0]
    rep.kcore_items = con.execute("SELECT count(DISTINCT perfume_id) FROM kcore").fetchone()[0]

    # ---- export ----------------------------------------------------------
    # Pseudonimizacion: el dataset publico lleva el hash, no el username.
    # sha256 nativo de DuckDB para no depender de un UDF (que pide numpy).
    salt_sql = cfg.username_salt.replace("'", "''")
    hash_expr = f"substr(sha256(username_slug || '{salt_sql}'), 1, 16)"

    con.execute(
        f"""COPY (
            SELECT * EXCLUDE (username_slug), {hash_expr} AS user_hash
            FROM kcore
        ) TO '{final / "interactions.parquet"}' (FORMAT PARQUET, COMPRESSION ZSTD)"""
    )
    con.execute(
        f"""COPY (
            SELECT i.* FROM items i
            WHERE i.perfume_id IN (SELECT DISTINCT perfume_id FROM kcore)
        ) TO '{final / "items.parquet"}' (FORMAT PARQUET, COMPRESSION ZSTD)"""
    )
    con.execute(
        f"""COPY (
            SELECT u.* EXCLUDE (username_slug, username_display),
                   {hash_expr} AS user_hash
            FROM users u
            WHERE u.member_id IN (SELECT DISTINCT member_id FROM kcore)
        ) TO '{final / "users.parquet"}' (FORMAT PARQUET, COMPRESSION ZSTD)"""
    )

    # El mapeo hash -> username queda aparte, fuera del dataset publicable.
    con.execute(
        f"""COPY (
            SELECT DISTINCT member_id, username_slug, {hash_expr} AS user_hash
            FROM users
        ) TO '{final / "PRIVATE_user_mapping.parquet"}' (FORMAT PARQUET)"""
    )

    rep.items_clean = con.execute("SELECT count(*) FROM items").fetchone()[0]
    rep.users_clean = con.execute("SELECT count(*) FROM users").fetchone()[0]

    # ---- sensibilidad al umbral ------------------------------------------
    sensitivity = _sensitivity(con, cfg)
    _write_dataset_card(final, rep, sensitivity, con, cfg)
    _print_report(rep, sensitivity)

    con.close()
    return rep


def _sensitivity(con: duckdb.DuckDBPyConnection, cfg: DatasetConfig) -> list[dict]:
    """Tabla de sensibilidad al umbral, sin volver a tocar la red.

    Es posible porque el staging se guarda sin filtrar. Sirve para justificar
    la eleccion de k en la tesis.
    """
    out = []
    for k in cfg.sensitivity_k_values:
        con.execute("CREATE OR REPLACE TABLE _s AS SELECT * FROM inter_clean")
        for _ in range(50):
            before = con.execute("SELECT count(*) FROM _s").fetchone()[0]
            con.execute(
                f"""
                CREATE OR REPLACE TABLE _s AS
                WITH u AS (SELECT member_id FROM _s GROUP BY 1 HAVING count(*) >= {k}),
                     i AS (SELECT perfume_id FROM _s GROUP BY 1 HAVING count(*) >= {k})
                SELECT s.* FROM _s s JOIN u USING (member_id) JOIN i USING (perfume_id)
                """
            )
            after = con.execute("SELECT count(*) FROM _s").fetchone()[0]
            if after == before or after == 0:
                break
        n_i, n_u, n_it = con.execute(
            "SELECT count(*), count(DISTINCT member_id), count(DISTINCT perfume_id) FROM _s"
        ).fetchone()
        density = (n_i / (n_u * n_it)) if n_u and n_it else 0.0
        out.append(
            {
                "k": k,
                "interactions": n_i,
                "users": n_u,
                "items": n_it,
                "sparsity": 1 - density,
            }
        )
    return out


def _write_dataset_card(
    final: Path,
    rep: ConsolidationReport,
    sensitivity: list[dict],
    con: duckdb.DuckDBPyConnection,
    cfg: DatasetConfig,
) -> None:
    dist = con.execute(
        "SELECT rating, count(*) AS n FROM kcore GROUP BY 1 ORDER BY 1"
    ).fetchall()
    period = con.execute(
        "SELECT min(timestamp), max(timestamp) FROM kcore WHERE timestamp IS NOT NULL"
    ).fetchone()
    relations = con.execute(
        "SELECT relation, count(*) FROM kcore GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()

    import datetime as dt

    def fmt(ts):
        return dt.datetime.fromtimestamp(ts).date().isoformat() if ts else "n/a"

    lines = [
        "# Dataset card",
        "",
        "Generado por el scraper de Fragrantica. Uso academico.",
        "",
        "## Conteos",
        "",
        f"- Interacciones crudas recolectadas: {rep.interactions_raw:,}",
        f"- Tras dedup por (member_id, perfume_id): {rep.interactions_deduped:,}",
        f"- Tras integridad referencial: {rep.interactions_clean:,}",
        f"- **Dataset final (k-core k={cfg.k_core}): {rep.kcore_interactions:,} interacciones, "
        f"{rep.kcore_users:,} usuarios, {rep.kcore_items:,} items**",
        f"- Iteraciones hasta punto fijo del k-core: {rep.kcore_iterations}",
        "",
        "## Descartes",
        "",
        f"- Sin member_id resuelto: {rep.dropped_null_member:,}",
        f"- Apuntando a items ausentes del catalogo: {rep.dropped_orphan_item:,} items distintos",
        "",
        "## Distribucion de ratings (dataset final)",
        "",
        "| rating | n |",
        "|---|---|",
    ]
    lines += [f"| {r[0]} | {r[1]:,} |" for r in dist]
    lines += [
        "",
        "## Relacion con el perfume (feedback implicito)",
        "",
        "| relation | n |",
        "|---|---|",
    ]
    lines += [f"| {r[0]} | {r[1]:,} |" for r in relations]
    lines += [
        "",
        f"## Periodo cubierto\n\n{fmt(period[0])} a {fmt(period[1])}",
        "",
        "## Sensibilidad al umbral k",
        "",
        "| k | interacciones | usuarios | items | sparsity |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {s['k']} | {s['interactions']:,} | {s['users']:,} | {s['items']:,} | {s['sparsity']:.6f} |"
        for s in sensitivity
    ]
    lines += [
        "",
        "## Limitaciones conocidas",
        "",
        "- **Wardrobe y votos sin review.** Ademas de las reviews del HTML, la",
        "  fase 3 pide `POST /ajax.php?user_shelves` (robots.txt lo prohibe;",
        "  decision explicita) y descifra el payload AES. Esas filas entran",
        "  con `source=wardrobe` o `source=vote` y `review_id` nulo. El dedup",
        "  se queda con una fila por par (usuario, item), preferiendo review",
        "  sobre voto sobre wardrobe. Si el passphrase del bundle no se",
        "  pudo recuperar, esas filas no estan y el dataset cubre solo reviews.",
        "- **Truncado de reviews por item.** El sitio renderiza ~200 reviews para",
        "  visitantes anonimos; el archivo completo requiere login. Los items",
        "  marcados con `reviews_truncated` tienen su cola cubierta solo en la",
        "  medida en que se crawlearon los perfiles de sus autores.",
        "- **`reviews_total` es aproximado** para items populares: el sitio lo",
        "  muestra abreviado ('4.2K'). Ver la columna `reviews_total_is_approx`.",
        "- **Sesgo de muestreo de usuarios**: el frontier de perfiles se puebla",
        "  desde las reviews encontradas, asi que los usuarios muy poco activos",
        "  estan subrepresentados (el k-core los eliminaria igual).",
        "",
        "## Privacidad",
        "",
        "Los usernames estan pseudonimizados con SHA-256 mas salt. El mapeo",
        "reversible vive en `PRIVATE_user_mapping.parquet`, que NO debe",
        "publicarse ni versionarse.",
    ]
    (final / "dataset_card.md").write_text("\n".join(lines))
    (final / "report.json").write_text(json.dumps(rep.to_dict(), indent=2))


def _print_report(rep: ConsolidationReport, sensitivity: list[dict]) -> None:
    t = Table(title="Consolidacion")
    t.add_column("metrica")
    t.add_column("valor", justify="right")
    t.add_row("interacciones crudas", f"{rep.interactions_raw:,}")
    t.add_row("tras dedup", f"{rep.interactions_deduped:,}")
    t.add_row("sin member_id", f"{rep.dropped_null_member:,}")
    t.add_row("items huerfanos", f"{rep.dropped_orphan_item:,}")
    t.add_row("tras integridad", f"{rep.interactions_clean:,}")
    t.add_row("[bold]final k-core[/bold]", f"[bold]{rep.kcore_interactions:,}[/bold]")
    t.add_row("usuarios finales", f"{rep.kcore_users:,}")
    t.add_row("items finales", f"{rep.kcore_items:,}")
    console.print(t)

    s = Table(title="Sensibilidad al umbral k")
    for col in ("k", "interacciones", "usuarios", "items", "sparsity"):
        s.add_column(col, justify="right")
    for row in sensitivity:
        s.add_row(
            str(row["k"]),
            f"{row['interactions']:,}",
            f"{row['users']:,}",
            f"{row['items']:,}",
            f"{row['sparsity']:.6f}",
        )
    console.print(s)
