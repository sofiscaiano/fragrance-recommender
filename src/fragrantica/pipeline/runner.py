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
from dataclasses import dataclass, field

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
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
from ..storage import ParquetWriter

log = logging.getLogger(__name__)
console = Console()


class StopCrawl(Exception):
    """429 o interstitial: se corta este ciclo. El daemon espera y reanuda.

    Seguir pidiendo en caliente es lo que pasa de rate-limit a penalizacion
    de IP. La URL vuelve a la cola; `fragrantica daemon` hace el probe.
    """

    def __init__(self, message: str, *, reason: str = "challenge") -> None:
        super().__init__(message)
        self.reason = reason


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
) -> RunStats:
    """Consume el frontier de un `kind` hasta agotarlo."""

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
                pending_ack.append(url)
            stats.done += 1

        except NotFound:
            frontier.mark_skipped(url, "404")
            stats.skipped += 1
        except AlreadyHave:
            frontier.mark_done(url)
            stats.done += 1
        except SkipItem as exc:
            frontier.mark_skipped(url, str(exc))
            stats.skipped += 1
        except RateLimited as exc:
            # El 429 no es culpa de esta URL. Vuelve a pending y se CORTA el
            # proceso: pausar 5 min y seguir era lo que escalaba a 403 de IP.
            frontier.requeue(url, str(exc), delay=exc.retry_after or cfg.rate_limit_pause)
            stats.rate_limited += 1
            halt = StopCrawl("HTTP 429: el sitio pidio bajar el ritmo", reason="429")
        except ChallengeDetected as exc:
            # Un interstitial puede ser la IP o esa URL. El canario (Sauvage)
            # va por la misma sesion: si pasa, cuarentena y el lote sigue;
            # si tambien falla, StopCrawl (no martillar).
            if url.rstrip("/") == PROBE_URL.rstrip("/"):
                frontier.requeue(url, str(exc), delay=cfg.rate_limit_pause)
                stats.failed += 1
                halt = StopCrawl(f"bloqueado por Cloudflare ({exc})", reason="challenge")
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
                except RateLimited:
                    frontier.requeue(url, str(exc), delay=cfg.rate_limit_pause)
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

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(name, total=total_hint if limit is None else min(total_hint, limit))

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
                    progress.update(
                        task,
                        description=f"{name} [dim](esperando backoff: {waiting} en cola)[/dim]",
                    )
                    await asyncio.sleep(sleep_for)
                else:
                    await asyncio.sleep(2.0)
                continue

            progress.update(task, description=name)

            await asyncio.gather(
                *(handle_one(row, i) for i, row in enumerate(rows)), return_exceptions=False
            )
            await flush_and_ack()
            progress.update(task, completed=processed)
            if halt is not None:
                break

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
