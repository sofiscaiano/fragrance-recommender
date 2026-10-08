"""CLI del scraper.

Todos los comandos son reanudables: el estado vive en el frontier SQLite, asi
que volver a correr el mismo comando retoma donde quedo sin duplicar trabajo.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from .config import CRAWL, DATA_DIR, DATASET
from .frontier import Frontier
from .http_client import Client, probe_site
from .observability import setup_otel
from .pipeline.consolidate import consolidate
from .pipeline.daemon import forget_cooldown, run_daemon
from .pipeline.runner import StopCrawl, queue_progress
from .pipeline.phases import (
    phase1_enumerate,
    phase2_perfumes,
    phase3_profiles,
    phase5_orphans,
    prune_slice,
    enqueue_missing_shelves,
    shelves_progress,
)

app = typer.Typer(add_completion=False, help="Scraper de Fragrantica para sistemas de recomendacion")
console = Console()


def _run(coro) -> None:
    try:
        asyncio.run(coro)
    except StopCrawl as exc:
        console.print(
            "[red]El crawl se detuvo solo. No hace falta Ctrl+C.[/red] "
            "Para dejarlo corriendo solo: [bold]fragrantica daemon[/bold]. "
            "O esperar y [bold]fragrantica probe[/bold] antes de reanudar a mano."
        )
        raise typer.Exit(code=2) from exc


def _setup(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )
    logging.getLogger("curl_cffi").setLevel(logging.WARNING)


def _paths(data_dir: Path) -> tuple[Path, Path, Path]:
    staging = data_dir / "staging"
    final = data_dir / "final"
    db = data_dir / "frontier.db"
    staging.mkdir(parents=True, exist_ok=True)
    return staging, final, db


@app.command()
def slice(
    designer: str = typer.Option("Dior", help="Slug de la marca, como aparece en /designers/"),
    max_perfumes: int = typer.Option(0, help="0 = sin limite"),
    max_profiles: int = typer.Option(0, help="0 = sin limite"),
    data_dir: Path = typer.Option(DATA_DIR),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Vertical slice: las 6 fases de punta a punta sobre una sola marca.

    Sirve para validar esquema y calibrar la tasa de bloqueos con un ciclo de
    feedback de minutos en vez de horas, antes de largar el crawl completo.
    """
    _setup(verbose)
    staging, final, db = _paths(data_dir)

    async def run() -> None:
        frontier = Frontier(db)
        async with Client(CRAWL) as client:
            await phase1_enumerate(frontier, client, staging, designers=[designer])
            await phase2_perfumes(
                frontier, client, staging, limit=max_perfumes or None
            )
            await phase3_profiles(
                frontier, client, staging, limit=max_profiles or None
            )

            rep = consolidate(staging, final, frontier, DATASET)

            if rep.orphan_item_ids:
                url_by_id = _orphan_urls(staging, rep.orphan_item_ids)
                added = await phase5_orphans(
                    frontier, client, staging, rep.orphan_item_ids, url_by_id
                )
                if added:
                    console.print("[bold]Reconsolidando tras el backfill[/bold]")
                    consolidate(staging, final, frontier, DATASET)

        console.print(f"\n[bold green]Listo.[/bold green] Dataset en {final}")
        frontier.close()

    _run(run())


def _orphan_urls(staging: Path, orphan_ids: list[int]) -> dict[int, str]:
    """Recupera las URLs de los items huerfanos desde el frontier de items."""
    import duckdb

    src = staging / "item_frontier" / "*.parquet"
    try:
        rows = duckdb.sql(
            f"SELECT perfume_id, url FROM read_parquet('{src}', union_by_name=true)"
        ).fetchall()
    except Exception:
        return {}
    known = dict(rows)
    out = {pid: known[pid] for pid in orphan_ids if pid in known}
    # Los que no estan en el frontier de items se pueden reconstruir desde la
    # URL canonica, que el sitio resuelve por id aunque el slug no coincida.
    return out


@app.command()
def phase(
    which: int = typer.Argument(..., help="1, 2, 3, 5 o 6"),
    designer: str = typer.Option("", help="Solo para la fase 1; vacio = todas las marcas"),
    limit: int = typer.Option(0, help="0 = sin limite"),
    data_dir: Path = typer.Option(DATA_DIR),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    otel: bool = typer.Option(False, "--otel", help="Emitir metricas OTLP (OTEL_EXPORTER_OTLP_ENDPOINT)"),
) -> None:
    """Corre una fase individual. Reanudable: reejecutar retoma donde quedo."""
    _setup(verbose)
    if otel:
        setup_otel()
    staging, final, db = _paths(data_dir)

    async def run() -> None:
        if which == 6:
            # Solo lee member_ids; el daemon puede seguir escribiendo el WAL.
            frontier = Frontier(db, readonly=True)
            try:
                consolidate(staging, final, frontier, DATASET)
            finally:
                frontier.close()
            return
        frontier = Frontier(db)
        async with Client(CRAWL) as client:
            if which == 1:
                await phase1_enumerate(
                    frontier, client, staging, designers=[designer] if designer else None
                )
            elif which == 2:
                await phase2_perfumes(frontier, client, staging, limit=limit or None)
            elif which == 3:
                await phase3_profiles(frontier, client, staging, limit=limit or None)
            elif which == 5:
                rep = consolidate(staging, final, frontier, DATASET)
                if rep.orphan_item_ids:
                    await phase5_orphans(
                        frontier, client, staging, rep.orphan_item_ids,
                        _orphan_urls(staging, rep.orphan_item_ids),
                    )
            else:
                raise typer.BadParameter(f"fase desconocida: {which}")
        frontier.close()

    _run(run())


@app.command()
def status(data_dir: Path = typer.Option(DATA_DIR)) -> None:
    """Estado del crawl, leido del frontier. Sobrevive a los reinicios."""
    _, _, db = _paths(data_dir)
    frontier = Frontier(db)
    stats = frontier.stats()
    if not stats:
        console.print("[yellow]frontier vacio: todavia no se corrio ninguna fase[/yellow]")
        return

    kinds = sorted({k for k, _ in stats})
    _, _, html_desc = queue_progress(frontier, "profile", "perfiles HTML")

    class _StatusShelves:
        _shelves_disabled = False

        def shelves_paused(self, *, now: float | None = None) -> bool:
            return False

    _, _, sh_desc = shelves_progress(frontier, _StatusShelves())
    console.print(f"[bold]{html_desc}[/bold]")
    console.print(f"[bold]{sh_desc}[/bold]\n")

    statuses = ["pending", "in_progress", "done", "failed", "skipped", "dead", "deferred"]
    t = Table(title="Estado del frontier")
    t.add_column("kind")
    for s in statuses:
        t.add_column(s, justify="right")
    t.add_column("total", justify="right")
    for kind in kinds:
        row = [kind]
        total = 0
        for s in statuses:
            n = stats.get((kind, s), 0)
            total += n
            row.append(f"{n:,}" if n else "-")
        row.append(f"{total:,}")
        t.add_row(*row)
    console.print(t)

    dead = frontier.dead_letters()
    if dead:
        console.print(f"\n[red]{len(dead)} dead-letters.[/red] Ejemplos:")
        for r in dead[:5]:
            console.print(f"  {r['url']}\n    {r['last_error']}")
        console.print("Para reintentarlos: [bold]fragrantica retry-dead[/bold]")
    deferred = [
        r
        for r in frontier.conn.execute(
            "SELECT url, last_error, next_retry_at FROM frontier WHERE status='deferred'"
        )
    ]
    if deferred:
        console.print(
            f"\n[yellow]{len(deferred)} en cuarentena[/yellow] "
            "(canario OK; se reintentan cuando venza el backoff):"
        )
        for r in deferred[:5]:
            console.print(f"  {r['url']}\n    {r['last_error']}")

    sh = frontier.shelves_stats()
    if sh:
        st = Table(title="Cola de wardrobe (shelves_jobs)")
        st.add_column("status")
        st.add_column("n", justify="right")
        for s, n in sorted(sh.items()):
            st.add_row(s, f"{n:,}")
        console.print(st)
        waiting = frontier.shelves_waiting_count()
        claimable = frontier.shelves_pending_count()
        console.print(
            f"[dim]wardrobe reclamables ahora: {claimable:,} · "
            f"en backoff (429/error): {waiting:,}[/dim]"
        )
    frontier.close()


@app.command("requeue-profiles")
def requeue_profiles(
    data_dir: Path = typer.Option(DATA_DIR),
) -> None:
    """Devuelve a pending los perfiles ya crawleados (reviews) para un 2º pase.

    No borra staging: las reviews duplicadas las absorbe el dedup. Baja la
    prioridad para que los perfiles nunca visitados salgan primero. Pensado
    para cuando falle el wardrobe (passphrase) y haya que volver por esos
    member_id sin tirar el trabajo de reviews.
    """
    _, _, db = _paths(data_dir)
    frontier = Frontier(db)
    n = frontier.requeue_done_profiles()
    console.print(
        f"{n} perfiles done/in_progress vueltos a pending (prioridad baja). "
        "Las reviews en staging se quedan; el wardrobe se pide en el proximo GET."
    )
    frontier.close()


@app.command("enqueue-shelves")
def enqueue_shelves_cmd(
    data_dir: Path = typer.Option(DATA_DIR),
) -> None:
    """Encola POST de wardrobe para perfiles con HTML y sin closet.

    No vuelve a bajar el perfil. Quien ya tiene filas en staging/wardrobe
    se saltea. Idempotente.
    """
    staging, _, db = _paths(data_dir)
    frontier = Frontier(db)
    n = enqueue_missing_shelves(frontier, staging)
    console.print(f"{n} jobs de wardrobe encolados")
    frontier.close()


@app.command("retry-dead")
def retry_dead(
    kind: str = typer.Option("", help="designer | perfume | profile; vacio = todos"),
    data_dir: Path = typer.Option(DATA_DIR),
) -> None:
    """Devuelve los dead-letters a la cola, p.ej. para reintentar con otra IP."""
    _, _, db = _paths(data_dir)
    frontier = Frontier(db)
    n = frontier.retry_dead(kind or None)  # type: ignore[arg-type]
    console.print(f"{n} URLs devueltas a la cola")
    frontier.close()


@app.command("reset-429")
def reset_429(
    kind: str = typer.Option("", help="designer | perfume | profile; vacio = todos"),
    data_dir: Path = typer.Option(DATA_DIR),
) -> None:
    """Devuelve a pending, sin intentos, las URLs caidas por 429/403.

    Un bloqueo de IP no es culpa de esa URL. El codigo viejo las mando a
    dead-letter; este comando las rehabilita para cuando se levante la
    penalizacion.
    """
    _, _, db = _paths(data_dir)
    frontier = Frontier(db)
    n = frontier.reset_rate_limited(kind or None)  # type: ignore[arg-type]
    console.print(f"{n} URLs rehabilitadas tras 429")
    frontier.close()


@app.command("clear-cooldown")
def clear_cooldown_cmd(
    data_dir: Path = typer.Option(DATA_DIR),
) -> None:
    """Olvida el cooldown del daemon para el proximo arranque.

    Equivale a borrar `daemon_state.json`: no hereda interstitial/429 viejos
    del frontier. No toca las colas ni el last_error de las URLs. Un bloqueo
    nuevo en esta corrida vuelve a esperar.
    """
    path = data_dir / "daemon_state.json"
    forget_cooldown(path)
    console.print(
        "Cooldown olvidado. El proximo [bold]fragrantica daemon[/bold] "
        "no espera ni hereda el bloqueo viejo del frontier."
    )


@app.command("prune-slice")
def prune_slice_cmd(
    designer: str = typer.Option("Dior", help="Slug de la marca del vertical slice"),
    data_dir: Path = typer.Option(DATA_DIR),
) -> None:
    """Saca del frontier items/perfiles ajenos a la marca del slice.

    No borra perfumes ya `done` de otras marcas (eso re-haria el GET).
    Si saca perfiles pending que no reseñaron ningun item de la marca.
    """
    staging, _, db = _paths(data_dir)
    frontier = Frontier(db)
    stats = prune_slice(frontier, staging, designer)
    console.print(
        f"perfumes pending ajenos borrados: {stats['perfumes_pending_dropped']}\n"
        f"perfiles pending ajenos borrados: {stats['profiles_dropped']}\n"
        f"perfiles conservados (reseñaron {designer}): {stats['profiles_kept']}\n"
        f"items de {designer} usados como filtro: {stats['items_of_designer']}"
    )
    frontier.close()


@app.command()
def daemon(
    data_dir: Path = typer.Option(DATA_DIR),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Crawl continuo: fase 1 (marcas), 2 y 3. No se apaga en el primer 429.

    Si Cloudflare corta, espera (429: 5 min y dobla; challenge: 30 min),
    hace UN probe y reanuda. Un worker, delay del config. Ctrl-C para parar; el frontier
    queda reanudable. Con el slice Dior ya done, el primer ciclo pide el
    indice A-Z y encola el resto del catalogo.
    """
    _setup(verbose)
    setup_otel()
    staging, _, db = _paths(data_dir)
    if CRAWL.shelves_proxies:
        console.print(
            f"[cyan]{len(CRAWL.shelves_proxies)} proxy(s) de wardrobe "
            "en FRAGRANTICA_SHELVES_PROXY[/cyan]"
        )
    if CRAWL.proxies:
        console.print(
            f"[cyan]{len(CRAWL.proxies)} proxy(s) en FRAGRANTICA_PROXY[/cyan] "
            "[dim](un puerto hasta que falle; despues rota)[/dim]"
        )
    else:
        console.print(
            "[dim]Sin FRAGRANTICA_PROXY. HTML por IP hogarena. "
            "Wardrobe: FRAGRANTICA_SHELVES_PROXY (opcional, residencial).[/dim]"
        )

    async def run() -> None:
        frontier = Frontier(db)
        try:
            await run_daemon(
                frontier=frontier,
                staging=staging,
                state_path=data_dir / "daemon_state.json",
            )
        finally:
            frontier.close()

    asyncio.run(run())


@app.command()
def probe() -> None:
    """Un solo request para saber si la penalizacion 429 se levanto.

    200 + ~1.8MB = se puede reanudar. 429 = seguir esperando. No subir
    concurrencia para compensar.
    """
    from .http_client import PROBE_URL

    result = probe_site()
    console.print(f"{result.status}  {result.nbytes:,} bytes  {PROBE_URL}")
    if result.ok:
        console.print("[green]Penalizacion levantada. Se puede reanudar.[/green]")
    elif result.blocked == "429":
        console.print("[red]Sigue el 429. Esperar mas. No subir concurrencia.[/red]")
        raise typer.Exit(code=2)
    else:
        console.print("[yellow]Respuesta inesperada; no reanudar todavia.[/yellow]")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
