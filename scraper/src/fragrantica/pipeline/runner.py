"""Motor generico de crawl sobre el frontier.

Cada fase aporta un handler; el runner se ocupa de la maquina de estados, la
concurrencia, el backoff y —lo importante— del ORDEN de commits:

    flush de datos a Parquet  ->  DESPUES  ->  mark_done en el frontier

Si el proceso muere entremedio, la URL sigue in_progress, el lease vence y se
reprocesa. Se prefiere trabajo duplicado (que el dedup de la fase 6 absorbe)
sobre datos perdidos.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from dataclasses import dataclass, field

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

from ..config import CRAWL, CrawlConfig
from ..frontier import Frontier, Kind, backoff_delay
from ..http_client import (
    PROBE_URL,
    ChallengeDetected,
    Client,
    FetchError,
    NotFound,
    RateLimited,
)
from ..observability import attach_snapshot, record_records, record_runner_outcome
from ..storage import ParquetWriter

log = logging.getLogger(__name__)
console = Console()


class StopCrawl(Exception):
    """429 o interstitial sin otro puerto libre: se corta este ciclo.

    Seguir pidiendo en caliente es lo que pasa de rate-limit a penalizacion
    de IP. La URL vuelve a la cola; `fragrantica daemon` hace el probe.
    Si quedaba otro puerto, el runner no corta: enfria este y sigue.
    """

    def __init__(self, message: str, *, reason: str = "challenge") -> None:
        super().__init__(message)
        self.reason = reason


async def _switch_port(client: object, worker: int, reason: str) -> bool:
    """True si el cliente enfrio este puerto y tiene otro. Los fakes no rotan."""
    retire = getattr(client, "retire_egress", None)
    if retire is None:
        return False
    switched = retire(worker, reason)
    if asyncio.iscoroutine(switched):
        switched = await switched
    return bool(switched)


def _note_port_switch() -> None:
    log.warning("puerto de proxy en cooldown; el crawl sigue por otro")
    console.print("[yellow]Puerto en cooldown[/yellow] (sigo por otro)")


class SkipItem(Exception):
    """El handler decidio descartar este item deliberadamente (no es un fallo).

    Se usa, por ejemplo, para el porton de "item sin reviews": no hay que
    reintentarlo nunca, a diferencia de un dead-letter.
    """


class AlreadyHave(Exception):
    """El entity ya esta en staging o marcado done: no gastar otro request.

    Cierra la ventana flush-sin-mark_done. Reprocesar esa URL duplicaria el
    GET; el parquet viejo ya tiene las filas y la fase 6 las deduplica.
    """


@dataclass
class RunStats:
    done: int = 0
    skipped: int = 0
    failed: int = 0
    dead: int = 0
    rate_limited: int = 0
    deferred: int = 0
    records: dict[str, int] = field(default_factory=dict)


# El handler recibe (url, entity_id, body) y devuelve {nombre_writer: [registros]}
Handler = Callable[[str, str, str], Awaitable[dict[str, list]] | dict[str, list]]
# precheck corre ANTES del GET; SkipItem / AlreadyHave evitan el request.
Precheck = Callable[[str, str], None]


def queue_progress(frontier: Frontier, kind: Kind, name: str) -> tuple[int, int, str]:
    """done, total y texto para la barra: cuenta el frontier, no solo esta corrida."""
    st = frontier.stats(kind)
    done = st.get((kind, "done"), 0)
    queued = (
        frontier.pending_count(kind)
        + frontier.waiting_count(kind)
        + frontier.in_flight_count(kind)
    )
    waiting = frontier.waiting_count(kind)
    desc = f"{name}  {done:,} done · {queued:,} en cola"
    if waiting:
        desc += f"  ({waiting} backoff)"
    return done, done + queued, desc


def _refresh_queue_task(
    progress: Progress,
    task_id: TaskID,
    frontier: Frontier,
    kind: Kind,
    name: str,
) -> None:
    done, total, desc = queue_progress(frontier, kind, name)
    progress.update(task_id, completed=done, total=max(total, 1), description=desc)


async def run_phase(
    *,
    name: str,
    kind: Kind,
    frontier: Frontier,
    client: Client,
    writers: dict[str, ParquetWriter],
    handler: Handler,
    cfg: CrawlConfig = CRAWL,
    limit: int | None = None,
    precheck: Precheck | None = None,
    progress: Progress | None = None,
    task_id: TaskID | None = None,
) -> RunStats:
    """Consume el frontier de un `kind` hasta agotarlo.

    Si `progress`/`task_id` vienen de afuera (fase 3: perfiles + wardrobe
    en el mismo live display), no se abre otra barra.
    """

    reclaimed = frontier.reclaim_stale(cfg.lease_timeout_seconds)
    if reclaimed:
        console.print(
            f"[yellow]{name}: {reclaimed} URLs recuperadas de una corrida interrumpida[/yellow]"
        )

    stats = RunStats()
    pending_ack: list[str] = []
    ack_lock = asyncio.Lock()
    processed = 0
    halt: BaseException | None = None
    attach_snapshot(frontier=frontier)

    total_hint = frontier.pending_count(kind)

    async def flush_and_ack() -> None:
        """Descarga datos y solo entonces confirma las URLs en el frontier."""
        async with ack_lock:
            if not pending_ack:
                return
            for w in writers.values():
                w.flush()
            for url in pending_ack:
                frontier.mark_done(url)
            pending_ack.clear()

    async def handle_one(row, worker: int) -> None:
        nonlocal processed, halt
        url = row["url"]
        entity_id = row["entity_id"]
        try:
            if precheck is not None:
                precheck(url, entity_id)
            result = await client.fetch(url, worker=worker)
            out = handler(url, entity_id, result.body)
            if asyncio.iscoroutine(out):
                out = await out

            async with ack_lock:
                for key, records in out.items():
                    if not records:
                        continue
                    writers[key].add_many(records)
                    stats.records[key] = stats.records.get(key, 0) + len(records)
                    record_records(key, len(records))
                pending_ack.append(url)
            stats.done += 1

        except NotFound:
            # El GET ya conto HTTP 404. El runner marca skip en el frontier.
            frontier.mark_skipped(url, "404")
            stats.skipped += 1
        except AlreadyHave:
            record_runner_outcome("already_have", kind)
            frontier.mark_done(url)
            stats.done += 1
        except SkipItem as exc:
            record_runner_outcome("skip", kind)
            frontier.mark_skipped(url, str(exc))
            stats.skipped += 1
        except RateLimited as exc:
            # 429 de pagina: no es culpa de esta URL. El cliente ya roto de
            # puerto si habia otro libre; si esto sube, no queda ninguno
            # (o no hay proxy). Vuelve a pending y se CORTA el ciclo. El 429
            # de ajax lo traga `_shelves_for_profile`. Pausar 5 min y seguir
            # en la misma IP era lo que escalaba a 403.
            frontier.requeue(url, str(exc), delay=exc.retry_after or cfg.rate_limit_pause)
            stats.rate_limited += 1
            halt = StopCrawl("HTTP 429: el sitio pidio bajar el ritmo", reason="429")
        except ChallengeDetected as exc:
            # Un interstitial puede ser la IP o esa URL. El canario (Sauvage)
            # va por la misma sesion: si pasa, cuarentena y el puerto se queda.
            # Si tambien falla, esa IP esta quemada: otro puerto sigue; si no
            # hay, StopCrawl (no martillar la misma salida).
            if url.rstrip("/") == PROBE_URL.rstrip("/"):
                if await _switch_port(client, worker, "challenge"):
                    frontier.requeue(url, str(exc), delay=0)
                    _note_port_switch()
                else:
                    frontier.requeue(url, str(exc), delay=cfg.rate_limit_pause)
                    stats.failed += 1
                    halt = StopCrawl(
                        f"bloqueado por Cloudflare ({exc})", reason="challenge"
                    )
            else:
                try:
                    canary_fn = getattr(client, "canary_ok", None)
                    if canary_fn is not None:
                        canary = await canary_fn(worker=worker)
                    else:
                        try:
                            await client.fetch(PROBE_URL, worker=worker)
                            canary = True
                        except ChallengeDetected:
                            canary = False
                except RateLimited as limited:
                    if await _switch_port(client, worker, "429"):
                        frontier.requeue(url, str(limited), delay=0)
                        _note_port_switch()
                    else:
                        frontier.requeue(
                            url, str(limited), delay=limited.retry_after or cfg.rate_limit_pause,
                        )
                        stats.rate_limited += 1
                        halt = StopCrawl(
                            "HTTP 429: el sitio pidio bajar el ritmo", reason="429"
                        )
                else:
                    if canary:
                        frontier.mark_deferred(url, str(exc), cfg.quarantine_seconds)
                        stats.deferred += 1
                        log.warning(
                            "cuarentena %s: el canario paso; se reintenta en %.0fh",
                            url,
                            cfg.quarantine_seconds / 3600,
                        )
                        console.print(
                            f"[yellow]Cuarentena[/yellow] {url} "
                            f"(canario OK; reintento en {cfg.quarantine_seconds / 3600:.0f}h)"
                        )
                    elif await _switch_port(client, worker, "challenge"):
                        frontier.requeue(url, str(exc), delay=0)
                        _note_port_switch()
                    else:
                        frontier.requeue(url, str(exc), delay=cfg.rate_limit_pause)
                        stats.failed += 1
                        halt = StopCrawl(
                            f"bloqueado por Cloudflare ({exc})", reason="challenge"
                        )
        except FetchError as exc:
            delay = backoff_delay(row["attempts"] + 1, cfg.backoff_base, cfg.backoff_cap)
            outcome = frontier.mark_failed(url, str(exc), cfg.max_attempts, delay)
            if outcome == "dead":
                stats.dead += 1
                log.error("dead-letter %s: %s", url, exc)
            else:
                stats.failed += 1
                log.warning("reintento de %s en %.0fs: %s", url, delay, exc)
        except Exception as exc:  # parser roto: es un bug, no un fallo de red
            outcome = frontier.mark_failed(url, f"parse: {exc}", 1, 0)
            stats.dead += 1
            log.exception("error de parseo en %s", url)
        finally:
            processed += 1

    own_progress = progress is None
    live = progress or Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    )
    ctx = live if own_progress else nullcontext(live)

    with ctx:
        task = (
            live.add_task(
                name,
                total=total_hint if limit is None else min(total_hint, limit) or 1,
            )
            if own_progress
            else task_id
        )
        if task is None:
            raise RuntimeError("run_phase: task_id es obligatorio si se pasa progress")
        _refresh_queue_task(live, task, frontier, kind, name)

        while True:
            if limit is not None and processed >= limit:
                break
            batch_size = cfg.concurrency
            if limit is not None:
                batch_size = min(batch_size, limit - processed)
            rows = frontier.claim(kind, batch_size)
            if not rows:
                # Ojo: pending_count solo cuenta lo elegible YA. Hay que mirar
                # tambien lo diferido por backoff, o se abandonarian items a
                # mitad del reintento.
                waiting = frontier.waiting_count(kind)
                if frontier.in_flight_count(kind) == 0 and waiting == 0:
                    break
                if waiting:
                    eta = frontier.next_retry_eta(kind)
                    sleep_for = max(2.0, min(60.0, (eta or 0) - time.time())) if eta else 2.0
                    _refresh_queue_task(live, task, frontier, kind, name)
                    attach_snapshot(frontier=frontier)
                    await asyncio.sleep(sleep_for)
                else:
                    await asyncio.sleep(2.0)
                continue

            await asyncio.gather(
                *(handle_one(row, i) for i, row in enumerate(rows)), return_exceptions=False
            )
            await flush_and_ack()
            _refresh_queue_task(live, task, frontier, kind, name)
            attach_snapshot(frontier=frontier)
            if halt is not None:
                break

        _refresh_queue_task(live, task, frontier, kind, name)

    await flush_and_ack()

    if halt is not None:
        console.print(
            f"[red]{name} detenido: {halt}[/red]\n"
            "El daemon espera y reanuda solo. A mano: no reanudar hasta "
            "[bold]fragrantica probe[/bold] en 200."
        )
        raise halt

    console.print(
        f"[green]{name}[/green] terminado: "
        f"{stats.done} ok, {stats.skipped} descartados, "
        f"{stats.deferred} en cuarentena, "
        f"{stats.failed} para reintentar, {stats.dead} dead-letters, "
        f"{stats.rate_limited} veces limitados por rate"
    )
    if stats.records:
        console.print(f"  registros escritos: {stats.records}")
    return stats
