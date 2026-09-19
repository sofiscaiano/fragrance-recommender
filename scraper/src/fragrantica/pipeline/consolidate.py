"""Fases 4 y 6: consolidacion del dataset. Todo local, sin red.

Fase 4  resolucion de member_id  (la FK que la pagina de perfume no trae)
Fase 6  dedup, integridad referencial, k-core iterativo, export
"""

from __future__ import annotations

import json
import os
import shutil
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
    wardrobe_rows: int = 0
    orphan_item_ids: list[int] | None = None

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["orphan_item_ids"] = (self.orphan_item_ids or [])[:200]
        return d


def _parquet_files(staging: Path, name: str) -> list[str]:
    """Lista fija de parts: un snapshot, no un glob que crece mientras el daemon escribe."""
    d = staging / name
    if not d.exists():
        return []
    return sorted(str(p) for p in d.glob("*.parquet") if p.is_file())


def _load_parquet(con: duckdb.DuckDBPyConnection, files: list[str], table: str) -> None:
    """Lee parts con union_by_name.

    Cada flush de ParquetWriter infiere el esquema del batch. Un part donde
    `signature_perfume_id` (u otra columna opcional) es todo-null queda tipado
    como NULL; el siguiente, con un entero, como BIGINT. Sin union_by_name
    DuckDB toma el primer archivo y el resto explota al castear.
    """
    con.execute(
        f"CREATE TABLE {table} AS SELECT * FROM read_parquet(?, union_by_name=true)",
        [files],
    )


def _export_parquet(con: duckdb.DuckDBPyConnection, select_sql: str, dest: Path) -> None:
    """COPY a un .tmp y rename: si el proceso muere no deja el parquet final a medias."""
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.unlink(missing_ok=True)
    dest_sql = str(tmp).replace("'", "''")
    con.execute(
        f"COPY ({select_sql}) TO '{dest_sql}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    os.replace(tmp, dest)


def consolidate(
    staging: Path,
    final: Path,
    frontier: Frontier,
    cfg: DatasetConfig = DATASET,
) -> ConsolidationReport:
    final.mkdir(parents=True, exist_ok=True)
    work = final.parent / "_consolidate_work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(work / "work.duckdb"))
    work_sql = str(work).replace("'", "''")
    con.execute(f"SET temp_directory='{work_sql}'")
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET memory_limit='6GB'")
    rep = ConsolidationReport()

    try:
        return _consolidate(con, staging, final, frontier, cfg, rep)
    finally:
        con.close()
        shutil.rmtree(work, ignore_errors=True)


def _consolidate(
    con: duckdb.DuckDBPyConnection,
    staging: Path,
    final: Path,
    frontier: Frontier,
    cfg: DatasetConfig,
    rep: ConsolidationReport,
) -> ConsolidationReport:
    # ---- carga (lista de archivos congelada al arrancar) -----------------
    inter_files = _parquet_files(staging, "interactions_from_perfume") + _parquet_files(
        staging, "interactions_from_profile"
    )
    item_files = _parquet_files(staging, "items")
    user_files = _parquet_files(staging, "users")
    wardrobe_files = _parquet_files(staging, "wardrobe")
    if not inter_files:
        raise RuntimeError("no hay interacciones en staging; corre las fases 2 y 3 primero")

    console.print(
        f"[dim]snapshot staging: {len(item_files):,} items · "
        f"{len(user_files):,} users · {len(inter_files):,} inter · "
        f"{len(wardrobe_files):,} wardrobe[/dim]"
    )
    _load_parquet(con, inter_files, "raw_inter")
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
    # sin texto puede coexistir con esa review. El recomendador quiere un
    # par (user, item) con senal explicita; se queda con la fila mas
    # informativa. El wardrobe NO entra: es otra tabla.
    # Ojo: NO deduplicar solo por review_id. Los votos tienen review_id NULL
    # y un PARTITION BY review_id los colapsaria a una sola fila.
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
                             ELSE 3
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
    if item_files:
        _load_parquet(con, item_files, "items_raw")
        con.execute(
            """
            CREATE TABLE items AS
            SELECT * EXCLUDE (rn) FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY perfume_id ORDER BY reviews_scraped DESC
                ) AS rn FROM items_raw
            ) WHERE rn = 1
            """
        )
    else:
        con.execute("CREATE TABLE items AS SELECT NULL::BIGINT AS perfume_id WHERE false")

    if user_files:
        _load_parquet(con, user_files, "users_raw")
        con.execute(
            """
            CREATE TABLE users AS
            SELECT * EXCLUDE (rn) FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY member_id ORDER BY n_reviews_scraped DESC
                ) AS rn FROM users_raw
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

    # ---- wardrobe (tabla aparte, no entra al k-core) ---------------------
    # have/had/want no es una calificacion. Se exporta con integridad
    # referencial contra users+items, sin filtrar por k-core: un perfume
    # en la coleccion no deberia desaparecer porque el usuario no llego
    # al umbral de reviews.
    if wardrobe_files:
        _load_parquet(con, wardrobe_files, "wardrobe_raw")
        con.execute(
            """
            CREATE TABLE wardrobe_resolved AS
            SELECT w.* REPLACE (COALESCE(w.member_id, m.member_id) AS member_id)
            FROM wardrobe_raw w
            LEFT JOIN slug_map m USING (username_slug)
            """
        )
        con.execute(
            """
            CREATE TABLE wardrobe_dedup AS
            SELECT * EXCLUDE (rn) FROM (
                SELECT *, row_number() OVER (
                    PARTITION BY COALESCE(member_id, -1), perfume_id
                    ORDER BY CASE relation
                                 WHEN 'have' THEN 0
                                 WHEN 'had' THEN 1
                                 WHEN 'want' THEN 2
                                 ELSE 3
                             END
                ) AS rn
                FROM wardrobe_resolved
            ) WHERE rn = 1
            """
        )
    else:
        con.execute(
            """
            CREATE TABLE wardrobe_dedup AS
            SELECT NULL::BIGINT AS member_id,
                   NULL::VARCHAR AS username_slug,
                   NULL::BIGINT AS perfume_id,
                   NULL::VARCHAR AS relation,
                   NULL::BIGINT AS timestamp
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
            FROM (
                SELECT perfume_id FROM inter_dedup
                UNION
                SELECT perfume_id FROM wardrobe_dedup WHERE perfume_id IS NOT NULL
            ) i
            LEFT JOIN items t USING (perfume_id)
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

    _export_parquet(
        con,
        f"SELECT * EXCLUDE (username_slug), {hash_expr} AS user_hash FROM kcore",
        final / "interactions.parquet",
    )
    _export_parquet(
        con,
        "SELECT i.* FROM items i WHERE i.perfume_id IN (SELECT DISTINCT perfume_id FROM kcore)",
        final / "items.parquet",
    )
    _export_parquet(
        con,
        f"""SELECT u.* EXCLUDE (username_slug, username_display),
                   {hash_expr} AS user_hash
            FROM users u
            WHERE u.member_id IN (SELECT DISTINCT member_id FROM kcore)""",
        final / "users.parquet",
    )

    # Coleccion have/had/want: usuarios e items del catalogo crawleado, no
    # del k-core. El hash usa el mismo salt que interactions.
    _export_parquet(
        con,
        f"""SELECT w.* EXCLUDE (username_slug),
                   substr(sha256(w.username_slug || '{salt_sql}'), 1, 16) AS user_hash
            FROM wardrobe_dedup w
            JOIN items t USING (perfume_id)
            JOIN users u USING (member_id)
            WHERE w.member_id IS NOT NULL""",
        final / "wardrobe.parquet",
    )
    rep.wardrobe_rows = con.execute(
        """
        SELECT count(*) FROM wardrobe_dedup w
        JOIN items t USING (perfume_id)
        JOIN users u USING (member_id)
        WHERE w.member_id IS NOT NULL
        """
    ).fetchone()[0]

    # El mapeo hash -> username queda aparte, fuera del dataset publicable.
    _export_parquet(
        con,
        f"""SELECT DISTINCT member_id, username_slug, {hash_expr} AS user_hash
            FROM users""",
        final / "PRIVATE_user_mapping.parquet",
    )

    rep.items_clean = con.execute("SELECT count(*) FROM items").fetchone()[0]
    rep.users_clean = con.execute("SELECT count(*) FROM users").fetchone()[0]

    # ---- sensibilidad al umbral ------------------------------------------
    sensitivity = _sensitivity(con, cfg)
    _write_dataset_card(final, rep, sensitivity, con, cfg)
    _print_report(rep, sensitivity)

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
    wardrobe_rel = con.execute(
        """
        SELECT relation, count(*) FROM wardrobe_dedup w
        JOIN items t USING (perfume_id)
        JOIN users u USING (member_id)
        WHERE w.member_id IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC
        """
    ).fetchall()

    import datetime as dt

    def fmt(ts):
        return dt.datetime.fromtimestamp(ts).date().isoformat() if ts else "n/a"

    lines = [
        "# Dataset card",
        "",
        "Generado por el scraper de Fragrantica. Uso academico.",
        f"Export: {dt.datetime.now().isoformat(timespec='seconds')}.",
        "Reejecutar `fragrantica phase 6` incorpora perfiles bajados despues;",
        "no hace falta mezclar a mano con un parquet anterior.",
        "",
        "## Conteos",
        "",
        f"- Interacciones crudas recolectadas: {rep.interactions_raw:,}",
        f"- Tras dedup por (member_id, perfume_id): {rep.interactions_deduped:,}",
        f"- Tras integridad referencial: {rep.interactions_clean:,}",
        f"- **Dataset final (k-core k={cfg.k_core}): {rep.kcore_interactions:,} interacciones, "
        f"{rep.kcore_users:,} usuarios, {rep.kcore_items:,} items**",
        f"- Iteraciones hasta punto fijo del k-core: {rep.kcore_iterations}",
        f"- Wardrobe (have/had/want, tabla aparte, sin k-core): {rep.wardrobe_rows:,}",
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
        "## Wardrobe (coleccion, no entra a la matriz de ratings)",
        "",
        f"{rep.wardrobe_rows:,} filas en `wardrobe.parquet`. Un usuario puede "
        "tener un perfume en la coleccion y ademas una review; no se colapsan.",
        "",
        "| relation | n |",
        "|---|---|",
    ]
    lines += [f"| {r[0]} | {r[1]:,} |" for r in wardrobe_rel] or ["| (vacio) | 0 |"]
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
        "- **Wardrobe vs interacciones.** `interactions.parquet` son reviews y",
        "  votos (calificacion explicita). `wardrobe.parquet` es la coleccion",
        "  have/had/want, tabla aparte: no entra al k-core ni se deduplica",
        "  contra las reviews. Los votos sin review siguen en interacciones",
        "  con `source=vote`. Si el passphrase AES no se recupero, ambas",
        "  tablas ajax quedan vacias y el dataset cubre solo reviews del HTML.",
        "- **Truncado de reviews por item.** El sitio renderiza ~200 reviews para",
        "  visitantes anonimos; el archivo completo requiere login. Los items",
        "  marcados con `reviews_truncated` tienen su cola cubierta solo en la",
        "  medida en que se crawlearon los perfiles de sus autores.",
        "- **`reviews_total` es aproximado** para items populares: el sitio lo",
        "  muestra abreviado ('4.2K'). Ver la columna `reviews_total_is_approx`.",
        "- **Sesgo de muestreo de usuarios**: el frontier de perfiles se puebla",
        "  desde las reviews encontradas, asi que los usuarios muy poco activos",
        "  estan subrepresentados (el k-core los eliminaria igual).",
        "- **Export mientras corre la fase 3.** Este parquet es un snapshot de",
        "  staging. Las reviews de pagina de perfume cuyo autor todavia no tiene",
        "  perfil crawleado se descartan (sin member_id) hasta el proximo export.",
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
    t.add_row("wardrobe (tabla aparte)", f"{rep.wardrobe_rows:,}")
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
