"""Watchdog: crawl continuo que no martillea cuando Cloudflare corta.

Un `phase 2` one-shot se apaga en el primer interstitial y deja el trabajo
a medias. Este loop es lo que permite terminar el slice (y mas adelante el
catalogo) sin sentarse a esperar el probe a mano:

    trabajo -> StopCrawl -> espera exponencial -> UN probe -> si 200, sigue

La espera crece (30 min, 1 h, 2 h, ... tope 6 h) porque reanudar en caliente
es lo que convirtio el 429 en bloqueo de IP. Un probe por ciclo, nunca un
retry inmediato de la URL que fallo.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from rich.console import Console

from ..config import CRAWL, CrawlConfig
from ..frontier import Frontier, Kind
from ..http_client import Client, probe_site
from .phases import phase2_perfumes, phase3_profiles
from .runner import StopCrawl

log = logging.getLogger(__name__)
console = Console()

_PHASES: tuple[tuple[Kind, int], ...] = (("perfume", 2), ("profile", 3))


@dataclass
class DaemonState:
    consecutive_blocks: int = 0
    last_reason: str = "challenge"
    last_block_at: float = 0.0


def cooldown_seconds(
    reason: str,
    consecutive: int,
    cfg: CrawlConfig = CRAWL,
) -> float:
    """Espera antes del proximo probe. consecutive=0 es el primer bloqueo."""
    base = cfg.cooldown_429 if reason == "429" else cfg.cooldown_challenge
    return min(cfg.cooldown_cap, base * (2 ** max(0, consecutive)))


def reason_from_error(message: str) -> str:
    return "429" if "429" in message else "challenge"


def next_phase(frontier: Frontier) -> int | None:
    """2 si hay perfume reclamable ahora, 3 si solo perfiles, None si no hay red.

    Las URLs `deferred` (cuarentena) con backoff a futuro no bloquean el
    salto a fase 3: pending_count solo las cuenta cuando ya vencio.
    """
    for kind, phase in _PHASES:
        n = (
            frontier.pending_count(kind)
            + frontier.waiting_count(kind)
            + frontier.in_flight_count(kind)
        )
        if n:
            return phase
    return None


def latest_block(frontier: Frontier) -> tuple[float, str] | None:
    row = frontier.conn.execute(
        """
        SELECT updated_at, last_error FROM frontier
         WHERE last_error LIKE '%interstitial%'
            OR last_error LIKE '%HTTP 429%'
         ORDER BY updated_at DESC
         LIMIT 1
        """
    ).fetchone()
    if not row or not row["last_error"]:
        return None
    return float(row["updated_at"]), reason_from_error(row["last_error"])


def remaining_wait(
    last_block_at: float,
    reason: str,
    consecutive: int,
    *,
    now: float | None = None,
    cfg: CrawlConfig = CRAWL,
) -> float:
    if last_block_at <= 0:
        return 0.0
    due = last_block_at + cooldown_seconds(reason, consecutive, cfg)
    return max(0.0, due - (now if now is not None else time.time()))


def load_state(path: Path) -> DaemonState:
    if not path.exists():
        return DaemonState()
    try:
        raw = json.loads(path.read_text())
        return DaemonState(
            consecutive_blocks=int(raw.get("consecutive_blocks", 0)),
            last_reason=str(raw.get("last_reason") or "challenge"),
            last_block_at=float(raw.get("last_block_at") or 0.0),
        )
    except (OSError, ValueError, TypeError):
        return DaemonState()


def save_state(path: Path, state: DaemonState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2) + "\n")


def seed_state_from_frontier(state: DaemonState, frontier: Frontier) -> DaemonState:
    """Si no hay estado propio, hereda el ultimo bloqueo del frontier.

    Evita que un restart del daemon pegue un probe a los 2 minutos de un
    interstitial: usaria el cooldown corto otra vez.
    """
    found = latest_block(frontier)
    if not found:
        return state
    ts, reason = found
    if ts > state.last_block_at:
        return DaemonState(
            consecutive_blocks=state.consecutive_blocks,
            last_reason=reason,
            last_block_at=ts,
        )
    return state


async def sleep_countdown(seconds: float) -> None:
    """Duerme en tramos para que Ctrl-C no espere el cooldown entero."""
    end = time.time() + seconds
    while True:
        left = end - time.time()
        if left <= 0:
            return
        mins = left / 60
        console.print(f"[dim]proxima probe en {mins:.1f} min[/dim]")
        await asyncio.sleep(min(300.0, left))


async def wait_until_clear(
    state: DaemonState,
    state_path: Path,
    cfg: CrawlConfig = CRAWL,
) -> DaemonState:
    """Espera el cooldown, un probe; si sigue bloqueado, dobla y repite."""
    while True:
        wait = remaining_wait(
            state.last_block_at, state.last_reason, state.consecutive_blocks, cfg=cfg
        )
        if wait > 0:
            console.print(
                f"[yellow]Cooldown {state.last_reason}: "
                f"{wait / 60:.1f} min (#{state.consecutive_blocks + 1})[/yellow]"
            )
            await sleep_countdown(wait)

        console.print("[bold]probe[/bold]: un request para ver si se puede reanudar")
        result = await asyncio.to_thread(probe_site, cfg)
        if result.ok:
            console.print(
                f"[green]probe OK[/green] {result.status} {result.nbytes:,} bytes"
            )
            state = DaemonState()
            save_state(state_path, state)
            return state

        reason = result.blocked or "other"
        state = DaemonState(
            consecutive_blocks=state.consecutive_blocks + 1,
            last_reason=reason if reason in ("429", "challenge") else "challenge",
            last_block_at=time.time(),
        )
        save_state(state_path, state)
        nxt = cooldown_seconds(state.last_reason, state.consecutive_blocks, cfg)
        console.print(
            f"[red]probe bloqueado[/red] {result.status} {result.nbytes:,} bytes "
            f"({reason}). Siguiente espera: {nxt / 60:.0f} min"
        )


async def run_daemon(
    *,
    frontier: Frontier,
    staging: Path,
    state_path: Path,
    cfg: CrawlConfig = CRAWL,
) -> None:
    """Fase 2 y despues 3, hasta vaciar las colas o hasta Ctrl-C."""
    state = seed_state_from_frontier(load_state(state_path), frontier)
    save_state(state_path, state)

    if state.last_block_at > 0:
        # Aunque el cooldown ya haya vencido, un probe. Crawlear a ciegas
        # despues de un interstitial es lo que quemo la IP.
        state = await wait_until_clear(state, state_path, cfg)

    while True:
        phase = next_phase(frontier)
        if phase is None:
            console.print(
                "[bold green]Colas de perfume y perfil vacias.[/bold green] "
                "Siguiente: [bold]fragrantica phase 6[/bold] (local, sin red)."
            )
            return

        console.print(
            f"[bold]Ciclo fase {phase}[/bold] "
            f"(delay {cfg.delay_min:.0f}-{cfg.delay_max:.0f}s, 1 worker)"
        )
        try:
            async with Client(cfg) as client:
                if phase == 2:
                    await phase2_perfumes(frontier, client, staging)
                else:
                    await phase3_profiles(frontier, client, staging)
        except StopCrawl as exc:
            # El ciclo llego a pedir paginas: el bloqueo es fresco. El primer
            # escalon (30 min / 15 min) alcanza; consecutive sube solo si el
            # probe sigue fallando, dentro de wait_until_clear.
            state = DaemonState(
                consecutive_blocks=0,
                last_reason=exc.reason,
                last_block_at=time.time(),
            )
            save_state(state_path, state)
            console.print(
                f"[red]ciclo cortado ({exc.reason})[/red]: {exc}\n"
                "El proceso sigue vivo. Espera + probe; no hace falta relanzar."
            )
            state = await wait_until_clear(state, state_path, cfg)
            continue

        state = DaemonState()
        save_state(state_path, state)
        log.info("fase %s vacia, paso a la siguiente", phase)
