"""Las fases de crawl (1, 2, 3, 5). Las fases 4 y 6 son locales, sin red."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)

from ..config import BASE_URL, CRAWL, DATA_DIR, DATASET, CrawlConfig, DatasetConfig
from ..frontier import Frontier, backoff_delay
from ..http_client import ChallengeDetected, Client, FetchError, NotFound, RateLimited, absolute
from ..models import User
from ..observability import attach_snapshot, record_records
from ..parsers.crypto import DecryptError, unwrap_ajax_body
from ..parsers.designer import (
    designer_slug_from_perfume_url,
    parse_designer_index,
    parse_designer_page,
    rows_for_designer,
)
from ..parsers.perfume import parse_perfume
from ..parsers.profile import member_id_from_avatar, parse_profile
from ..parsers.shelves import ParsedShelves, parse_shelves
from ..storage import ParquetWriter, existing_ids, existing_int_ids
from .runner import AlreadyHave, SkipItem, StopCrawl, queue_progress, run_phase

log = logging.getLogger(__name__)
console = Console()

_HTML_PROGRESS_NAME = "perfiles HTML"
_SHELVES_PROGRESS_NAME = "wardrobe POST"


def shelves_progress(
    frontier: Frontier,
    client: Any,
    *,
    now: float | None = None,
    current_slug: str | None = None,
) -> tuple[int, int, str]:
    """done, total y texto de la barra de closet, aparte del GET de perfil."""
    sh = frontier.shelves_stats()
    done = int(sh.get("done", 0))
    queued = (
        frontier.shelves_pending_count()
        + frontier.shelves_waiting_count()
        + frontier.shelves_in_flight_count()
    )
    waiting = frontier.shelves_waiting_count()
    desc = f"{_SHELVES_PROGRESS_NAME}  {done:,} done · {queued:,} en cola"
    if getattr(client, "_shelves_disabled", False):
        desc = f"{_SHELVES_PROGRESS_NAME}  deshabilitado  ({done:,} done · {queued:,} en cola)"
    elif client.shelves_paused(now=now):
        remaining = client.shelves_pause_remaining(now=now) if hasattr(client, "shelves_pause_remaining") else 0.0
        desc = (
            f"{_SHELVES_PROGRESS_NAME}  pausa 429 · {remaining / 60:.0f} min  "
            f"({done:,} done · {queued:,} en cola)"
        )
    elif current_slug:
        desc += f"  · POST @{current_slug}"
    elif waiting:
        desc += f"  ({waiting} backoff)"
    return done, done + queued, desc


def _refresh_shelves_task(
    progress: Progress | None,
    task_id: TaskID | None,
    frontier: Frontier,
    client: Any,
    *,
    current_slug: str | None = None,
) -> None:
    if progress is None or task_id is None:
        return
    done, total, desc = shelves_progress(
        frontier, client, current_slug=current_slug
    )
    progress.update(task_id, completed=done, total=max(total, 1), description=desc)


# --------------------------------------------------------------------------
# Fase 1: enumeracion del catalogo de items
# --------------------------------------------------------------------------


async def phase1_enumerate(
    frontier: Frontier,
    client: Client,
    staging: Path,
    designers: list[str] | None = None,
) -> None:
    """Puebla el frontier de perfumes desde los listados de marca.

    Si `designers` es None, primero enumera el indice A-Z. Para el vertical
    slice se pasa una sola marca.
    """
    if designers is None:
        console.print("[bold]Fase 1a[/bold]: indice de marcas")
        result = await client.fetch(absolute("/designers/"))
        designers = parse_designer_index(result.body)
        console.print(f"  {len(designers)} marcas encontradas")

    rows = [
        (absolute(f"/designers/{slug}.html"), "designer", slug, 10) for slug in designers
    ]
    added = frontier.add_many(rows)
    console.print(f"[bold]Fase 1b[/bold]: {added} listados de marca encolados")

    writer = ParquetWriter(staging, "item_frontier")

    def handle(url: str, entity_id: str, body: str) -> dict[str, list]:
        brand = entity_id.replace("-", " ")
        found = parse_designer_page(body, brand=brand)
        own = rows_for_designer(found, entity_id)
        dropped = len(found) - len(own)
        if dropped:
            log.info("fase 1: %d perfumes ajenos a %s no se encolan", dropped, entity_id)
        if not own:
            raise SkipItem("el listado de marca no tiene perfumes propios")
        frontier.add_many(
            [(row["url"], "perfume", str(row["perfume_id"]), 50) for row in own]
        )
        return {"item_frontier": [{**row, "designer_slug": entity_id} for row in own]}

    with writer:
        await run_phase(
            name="Fase 1: listados de marca",
            kind="designer",
            frontier=frontier,
            client=client,
            writers={"item_frontier": writer},
            handler=handle,
        )


# --------------------------------------------------------------------------
# Fase 2: paginas de perfume -> items + interacciones + semillas de usuarios
# --------------------------------------------------------------------------


async def phase2_perfumes(
    frontier: Frontier,
    client: Client,
    staging: Path,
    dataset: DatasetConfig = DATASET,
    limit: int | None = None,
) -> None:
    items = ParquetWriter(staging, "items")
    inter = ParquetWriter(staging, "interactions_from_perfume")
    already = existing_ids(staging / "items", "perfume_id")
    allowed = frontier.listed_designer_slugs()

    def precheck(url: str, entity_id: str) -> None:
        if entity_id in already or frontier.entity_is_done("perfume", entity_id):
            raise AlreadyHave()
        slug = designer_slug_from_perfume_url(url)
        if slug and allowed and slug not in allowed:
            raise SkipItem(f"marca {slug} fuera de las marcas listadas")

    def handle(url: str, entity_id: str, body: str) -> dict[str, list]:
        item, interactions, seeds = parse_perfume(body, url)

        # Porton de items: descartar los que no llegan al minimo de reviews.
        # Lo importante no es ahorrar este request (ya se gasto), sino evitar
        # arrastrar cientos de miles de perfiles inutiles a la fase 3.
        n = len(interactions)
        if n < dataset.crawl_min_item_reviews:
            # Se guarda igual la fila del item, para trazabilidad y para poder
            # revisar la decision despues sin volver a la red.
            items.add(item)
            already.add(str(item.perfume_id))
            raise SkipItem(f"solo {n} reviews (< {dataset.crawl_min_item_reviews})")

        # Solo los items que pasan el porton generan semillas de usuario.
        frontier.add_many(
            [
                (absolute(f"/@{s['username_slug']}"), "profile", s["username_slug"],
                 20 if item.reviews_truncated else 60)
                for s in seeds
            ]
        )
        already.add(str(item.perfume_id))
        return {"items": [item], "interactions_from_perfume": interactions}

    with items, inter:
        await run_phase(
            name="Fase 2: paginas de perfume",
            kind="perfume",
            frontier=frontier,
            client=client,
            writers={"items": items, "interactions_from_perfume": inter},
            handler=handle,
            limit=limit,
            precheck=precheck,
        )


# --------------------------------------------------------------------------
# Fase 3: perfiles de usuario -> users + member_id + historico completo
# --------------------------------------------------------------------------


HtmlCooldown = Callable[[StopCrawl, Path, CrawlConfig], Awaitable[None]]


async def _html_cooldown(
    exc: StopCrawl,
    state_path: Path,
    cfg: CrawlConfig,
    *,
    on_tick: Callable[[float, str], None] | None = None,
    frontier: Frontier | None = None,
) -> None:
    """Pausa solo el GET de perfil: espera + un probe. Shelves no se toca.

    Import tardio: daemon.py importa phase3_profiles.
    """
    from ..observability import record_block
    from .daemon import load_state, save_state, state_after_block, wait_until_clear

    record_block(exc.reason)
    state = state_after_block(exc.reason, load_state(state_path))
    save_state(state_path, state)
    console.print(
        f"[red]HTML en cooldown ({exc.reason})[/red]: {exc}\n"
        "Los POST de wardrobe siguen. El GET reanuda tras espera + probe."
    )
    await wait_until_clear(
        state, state_path, cfg, on_tick=on_tick, frontier=frontier, phase=3
    )


async def phase3_profiles(
    frontier: Frontier,
    client: Client,
    staging: Path,
    limit: int | None = None,
    *,
    state_path: Path | None = None,
    html_cooldown: HtmlCooldown | None = None,
) -> None:
    users = ParquetWriter(staging, "users")
    inter = ParquetWriter(staging, "interactions_from_profile")
    votes_out = ParquetWriter(staging, "interactions_from_profile")
    wardrobe = ParquetWriter(staging, "wardrobe")

    mismatches = 0
    if client.cfg.fetch_shelves:
        n = enqueue_missing_shelves(frontier, staging)
        if n:
            console.print(f"[bold]Shelves[/bold]: {n} perfiles ya crawleados sin closet, encolados")

    async def handle(url: str, entity_id: str, body: str) -> dict[str, list]:
        nonlocal mismatches
        user, interactions = parse_profile(body, entity_id)

        # Chequeo cruzado del atajo del avatar. No se usa para saltear la
        # visita (el perfil se necesita igual por el historico), sino como
        # canario: si no coincide, hay un bug en el parser y quiero saberlo.
        inferred = member_id_from_avatar(user.avatar_url)
        if inferred is not None and inferred != user.member_id:
            mismatches += 1
            log.warning(
                "member_id del avatar (%s) != del perfil (%s) en @%s",
                inferred, user.member_id, entity_id,
            )

        frontier.record_member_id(user.username_slug, user.member_id)
        if client.cfg.fetch_shelves:
            frontier.enqueue_shelves(user.member_id, user.username_slug, url)
        return {
            "users": [user],
            "interactions_from_profile": interactions,
        }

    html_error: BaseException | None = None
    state_file = state_path or (DATA_DIR / "daemon_state.json")

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        html_tid = progress.add_task(_HTML_PROGRESS_NAME, total=1)
        shelves_tid: TaskID | None = None
        if client.cfg.fetch_shelves:
            shelves_tid = progress.add_task(_SHELVES_PROGRESS_NAME, total=1)
            _refresh_shelves_task(progress, shelves_tid, frontier, client)

        async def run_html() -> None:
            # El 429 de pagina no corta la fase: esta tarea espera + probe y
            # vuelve a run_phase. html_task sigue viva durante el cooldown, asi
            # el daemon no se queda solo drenando shelves sin reanudar el GET.
            nonlocal html_error
            with users, inter:
                while True:
                    try:
                        await run_phase(
                            name=_HTML_PROGRESS_NAME,
                            kind="profile",
                            frontier=frontier,
                            client=client,
                            writers={
                                "users": users,
                                "interactions_from_profile": inter,
                            },
                            handler=handle,
                            limit=limit,
                            cfg=client.cfg,
                            progress=progress,
                            task_id=html_tid,
                        )
                        return
                    except StopCrawl as exc:

                        def on_html_tick(left: float, phase: str) -> None:
                            from .daemon import format_cooldown_left

                            done_n, total_n, _ = queue_progress(
                                frontier, "profile", _HTML_PROGRESS_NAME
                            )
                            if phase == "probe":
                                desc = (
                                    f"{_HTML_PROGRESS_NAME}  probe "
                                    f"({done_n:,} done · wardrobe sigue)"
                                )
                            else:
                                desc = (
                                    f"{_HTML_PROGRESS_NAME}  cooldown {exc.reason} · "
                                    f"{format_cooldown_left(left)} "
                                    f"({done_n:,} done · wardrobe sigue)"
                                )
                            progress.update(
                                html_tid,
                                completed=done_n,
                                total=max(total_n, 1),
                                description=desc,
                            )

                        if html_cooldown is not None:
                            await html_cooldown(exc, state_file, client.cfg)
                        else:
                            await _html_cooldown(
                                exc,
                                state_file,
                                client.cfg,
                                on_tick=on_html_tick,
                                frontier=frontier,
                            )
                    except BaseException as exc:
                        html_error = exc
                        raise

        html_task = asyncio.create_task(run_html())
        try:
            with votes_out, wardrobe:
                if client.cfg.fetch_shelves:
                    await run_shelves_loop(
                        frontier,
                        client,
                        votes_out,
                        wardrobe,
                        html_task,
                        progress=progress,
                        task_id=shelves_tid,
                    )
                await html_task
        except BaseException:
            if not html_task.done():
                html_task.cancel()
                try:
                    await html_task
                except BaseException:
                    pass
            raise

    if mismatches:
        console.print(f"[yellow]  {mismatches} discrepancias de member_id via avatar[/yellow]")
    if html_error is not None:
        raise html_error


def enqueue_missing_shelves(frontier: Frontier, staging: Path) -> int:
    """Encola member_id con HTML ya parseado y sin filas en wardrobe.

    No vuelve a pedir el perfil. Quien ya tiene closet no se toca. Quien
    tiene closet vacio se pide una vez; despues queda done en shelves_jobs.
    """
    have = existing_int_ids(staging / "wardrobe", "member_id")
    rows: list[tuple[int, str, str]] = []
    for slug, mid in frontier.member_id_map().items():
        if mid in have:
            continue
        rows.append((mid, slug, f"{BASE_URL}/@{slug}"))
    return frontier.enqueue_shelves_many(rows)


async def run_shelves_loop(
    frontier: Frontier,
    client: Client,
    votes_writer: ParquetWriter,
    wardrobe_writer: ParquetWriter,
    html_task: asyncio.Task,
    progress: Progress | None = None,
    task_id: TaskID | None = None,
) -> None:
    """Consume shelves_jobs. Un 429 pausa este loop, no el GET del perfil."""
    frontier.reclaim_stale(client.cfg.lease_timeout_seconds)
    _refresh_shelves_task(progress, task_id, frontier, client)

    while True:
        if client._shelves_disabled or not client.cfg.fetch_shelves:
            _refresh_shelves_task(progress, task_id, frontier, client)
            return
        if client.shelves_paused():
            _refresh_shelves_task(progress, task_id, frontier, client)
            await asyncio.sleep(2.0)
            continue
        if not client.should_fetch_shelves():
            _refresh_shelves_task(progress, task_id, frontier, client)
            await asyncio.sleep(2.0)
            continue

        rows = frontier.claim_shelves(1)
        if not rows:
            _refresh_shelves_task(progress, task_id, frontier, client)
            html_done = html_task.done()
            html_failed = html_done and (
                html_task.cancelled()
                or html_task.exception() is not None
            )
            if html_failed and not client.cfg.shelves_proxies:
                return
            if (
                html_done
                and frontier.shelves_pending_count() == 0
                and frontier.shelves_waiting_count() == 0
                and frontier.shelves_in_flight_count() == 0
            ):
                return
            await asyncio.sleep(1.0)
            continue

        job = rows[0]
        mid = int(job["member_id"])
        slug = str(job["slug"])
        profile_url = str(job["profile_url"])
        user = User(member_id=mid, username_slug=slug)
        _refresh_shelves_task(
            progress, task_id, frontier, client, current_slug=slug
        )
        try:
            parsed = await _shelves_for_profile(client, "", user, profile_url)
        except RateLimited as exc:
            frontier.requeue_shelves(mid, str(exc), client.cfg.shelves_cooldown)
            _refresh_shelves_task(progress, task_id, frontier, client)
            continue
        except ChallengeDetected as exc:
            frontier.requeue_shelves(mid, str(exc), client.cfg.shelves_cooldown)
            _refresh_shelves_task(progress, task_id, frontier, client)
            continue
        except FetchError as exc:
            delay = backoff_delay(
                int(job["attempts"]) + 1,
                client.cfg.backoff_base,
                client.cfg.backoff_cap,
            )
            frontier.mark_shelves_failed(mid, str(exc), client.cfg.max_attempts, delay)
            _refresh_shelves_task(progress, task_id, frontier, client)
            continue
        if parsed.votes:
            votes_writer.add_many(parsed.votes)
            record_records("interactions", len(parsed.votes))
        if parsed.wardrobe:
            wardrobe_writer.add_many(parsed.wardrobe)
            record_records("wardrobe", len(parsed.wardrobe))
        votes_writer.flush()
        wardrobe_writer.flush()
        frontier.mark_shelves_done(mid)
        attach_snapshot(frontier=frontier)
        _refresh_shelves_task(progress, task_id, frontier, client)


async def _shelves_for_profile(
    client: Client,
    html: str,
    user: User,
    profile_url: str,
) -> ParsedShelves:
    """POST de wardrobe. RateLimited/challenge suben al loop de jobs."""
    if not client.should_fetch_shelves():
        raise FetchError("shelves pausados o deshabilitados")
    pw = await client.ensure_passphrase(html)
    if not pw:
        raise FetchError("sin passphrase AES")
    try:
        result = await client.post(
            absolute("/ajax.php?user_shelves"),
            data={"action": "user_shelves", "user_id": str(user.member_id)},
            referer=profile_url,
        )
        payload = unwrap_ajax_body(result.body, pw)
    except RateLimited as exc:
        client.pause_shelves(str(exc))
        console.print(
            f"[yellow]shelves en pausa {client.cfg.shelves_cooldown / 60:.0f} min[/yellow] "
            f"(429 ajax; el HTML sigue). {exc}"
        )
        raise
    except ChallengeDetected as exc:
        client.disable_shelves(str(exc))
        raise
    except (DecryptError, FetchError, NotFound, ValueError) as exc:
        log.warning("shelves de @%s: %s", user.username_slug, exc)
        if isinstance(exc, DecryptError):
            client._shelves_decrypt_fails += 1
            if client._shelves_decrypt_fails >= 3:
                client.disable_shelves("descifrado ajax fallo 3 veces seguidas")
        raise FetchError(str(exc)) from exc
    client._shelves_decrypt_fails = 0
    return parse_shelves(payload, member_id=user.member_id, slug=user.username_slug)


# --------------------------------------------------------------------------
# Fase 5: backfill de items huerfanos
# --------------------------------------------------------------------------


async def phase5_orphans(
    frontier: Frontier,
    client: Client,
    staging: Path,
    orphan_ids: list[int],
    url_by_id: dict[int, str],
) -> int:
    """Crawlea los items referenciados por interacciones pero ausentes del catalogo.

    Garantiza integridad referencial: toda interaccion apunta a un item que
    existe en la tabla de items.
    """
    rows = []
    for pid in orphan_ids:
        url = url_by_id.get(pid)
        if url:
            rows.append((url, "perfume", str(pid), 30))
    if not rows:
        return 0
    added = frontier.add_many(rows)
    console.print(f"[bold]Fase 5[/bold]: {added} items huerfanos encolados")
    if added:
        await phase2_perfumes(frontier, client, staging)
    return added


def prune_slice(
    frontier: Frontier,
    staging: Path,
    designer_slug: str,
) -> dict[str, int]:
    """Limpia el frontier de un vertical slice: nada ajeno a `designer_slug`.

    Los perfume ya `done` de otras marcas se dejan: borrarles el done haria
    que una fase 1 posterior de esa marca los volviera a pedir.
    Los perfiles pending que no reseñaron ningun item de la marca salen de
    la cola para no gastar 13k GETs de ruido.
    """
    n_perfumes = frontier.drop_perfumes_not_from(designer_slug, keep_done=True)
    ids = _perfume_ids_for_designer(staging, frontier, designer_slug)
    slugs = _reviewer_slugs(staging, ids)
    # Sin slugs no borramos: un staging vacio vaciaria 13k perfiles por error.
    n_profiles = frontier.drop_profiles_except(slugs) if slugs else 0
    return {
        "perfumes_pending_dropped": n_perfumes,
        "profiles_dropped": n_profiles,
        "profiles_kept": len(slugs),
        "items_of_designer": len(ids),
    }


def _perfume_ids_for_designer(
    staging: Path, frontier: Frontier, designer_slug: str
) -> set[int]:
    ids: set[int] = set()
    items_dir = staging / "items"
    if items_dir.exists():
        import pyarrow.parquet as pq

        for path in items_dir.glob("*.parquet"):
            table = pq.read_table(path, columns=["perfume_id", "brand", "url"])
            for row in table.to_pylist():
                url = row.get("url") or ""
                brand = row.get("brand") or ""
                if (
                    f"/perfume/{designer_slug}/" in url
                    or brand.replace(" ", "-") == designer_slug
                    or brand == designer_slug
                ):
                    ids.add(int(row["perfume_id"]))
    like = f"%/perfume/{designer_slug}/%"
    for r in frontier.conn.execute(
        "SELECT entity_id FROM frontier WHERE kind='perfume' AND url LIKE ?",
        (like,),
    ):
        try:
            ids.add(int(r["entity_id"]))
        except (TypeError, ValueError):
            continue
    return ids


def _reviewer_slugs(staging: Path, perfume_ids: set[int]) -> set[str]:
    if not perfume_ids:
        return set()
    slugs: set[str] = set()
    inter_dir = staging / "interactions_from_perfume"
    if not inter_dir.exists():
        return slugs
    import pyarrow.parquet as pq

    want = {int(p) for p in perfume_ids}
    for path in inter_dir.glob("*.parquet"):
        table = pq.read_table(path, columns=["perfume_id", "username_slug"])
        for row in table.to_pylist():
            if row["perfume_id"] in want and row["username_slug"]:
                slugs.add(str(row["username_slug"]).lower())
    return slugs
