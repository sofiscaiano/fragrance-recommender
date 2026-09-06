"""Watchdog: crawl continuo que no martillea cuando Cloudflare corta.

Un `phase` one-shot se apaga en el primer interstitial y deja el trabajo
a medias. Este loop cubre fase 1 (indice A-Z + listados de marca), 2 y 3
sin sentarse a esperar el probe a mano:

    trabajo -> StopCrawl -> espera exponencial -> UN probe -> si 200, sigue

La espera crece (429: 5 min, 10, 20…; challenge: 30 min, 1 h, 2 h; tope 6 h)
porque reanudar en caliente es lo que convirtio el 429 en bloqueo de IP. Un
probe por ciclo, nunca un retry inmediato de la URL que fallo.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from rich.console import Console

from ..config import CRAWL, CrawlConfig
from ..frontier import Frontier, Kind
from ..http_client import Client, probe_site
from ..observability import attach_snapshot, egress_via, record_block, record_cooldown, start_span
from .phases import phase1_enumerate, phase2_perfumes, phase3_profiles
from .runner import StopCrawl

log = logging.getLogger(__name__)
console = Console()

_PHASES: tuple[tuple[Kind, int], ...] = (("designer", 1), ("perfume", 2), ("profile", 3))

# remaining seconds, "wait" | "probe". Lo usa la barra de perfiles HTML.
WaitTick = Callable[[float, str], None]


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


def next_phase(
    frontier: Frontier,
    *,
    seed_catalog: bool = False,
    skip_kinds: tuple[Kind, ...] = (),
) -> int | None:
    """1 marcas, 2 perfume, 3 perfiles. None si no hay red.

    `seed_catalog=True` fuerza la fase 1 aunque las colas esten vacias: hay
    que pedir el indice A-Z (add_many es idempotente; Dior already-done no
    se vuelve a bajar). Sin eso el daemon se iria a dormir con el slice
    cerrado y nunca enumeraria el resto del sitio.

    Las URLs `deferred` (cuarentena) con backoff a futuro no bloquean el
    salto a la fase siguiente: pending_count solo las cuenta cuando ya vencio.

    `skip_kinds` saltea una cola con trabajo: el 429 de /perfume/ no aplica
    a perfiles (medido en browser y en 7 rafagas de ~400 GETs).
    """
    if seed_catalog:
        return 1
    skipped = set(skip_kinds)
    for kind, phase in _PHASES:
        if kind in skipped:
            continue
        n = (
            frontier.pending_count(kind)
            + frontier.waiting_count(kind)
            + frontier.in_flight_count(kind)
        )
        if n:
            return phase
    if frontier.shelves_has_work() and "profile" not in skipped:
        return 3
    return None


def can_divert_perfume_429(frontier: Frontier) -> bool:
    """True si un 429 de perfume puede seguirse con perfiles en vez de cooldown."""
    return next_phase(frontier, skip_kinds=("perfume",)) == 3


def latest_block(frontier: Frontier) -> tuple[float, str] | None:
    """Ultimo bloqueo de IP, no una URL en cuarentena.

    `deferred` es canario OK: solo esa ficha espera 12 h. El lote siguio.
    Si al relanzar se heredara, un Ctrl-C despues de Dioressence arranca
    30 min de cooldown que la terminal nunca mostro como StopCrawl.
    """
    row = frontier.conn.execute(
        """
        SELECT updated_at, last_error FROM frontier
         WHERE status != 'deferred'
           AND (last_error LIKE '%interstitial%'
            OR last_error LIKE '%HTTP 429%')
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


def format_cooldown_left(seconds: float) -> str:
    """Texto corto para la barra: '12.3 min' o '8 s'."""
    if seconds >= 60:
        return f"{seconds / 60:.1f} min"
    return f"{max(0.0, seconds):.0f} s"


async def sleep_countdown(
    seconds: float,
    on_tick: WaitTick | None = None,
    *,
    announce: bool = False,
) -> None:
    """Duerme en tramos para que Ctrl-C no espere el cooldown entero.

    `on_tick` alimenta la barra (fase 3) o el snapshot OTel. Si es el unico
    callback, la terminal no imprime nada y el cooldown parece un hang:
    `announce=True` restaura el 'proxima probe en X min' cada 5 min.
    """
    end = time.time() + seconds
    last_announce = 0.0
    while True:
        left = end - time.time()
        if left <= 0:
            return
        if on_tick is not None:
            on_tick(left, "wait")
        now = time.time()
        if announce and (last_announce == 0.0 or now - last_announce >= 300.0):
            console.print(f"[dim]proxima probe en {left / 60:.1f} min[/dim]")
            last_announce = now
        if on_tick is not None:
            await asyncio.sleep(min(2.0, left))
        else:
            await asyncio.sleep(min(300.0, left))


async def wait_until_clear(
    state: DaemonState,
    state_path: Path,
    cfg: CrawlConfig = CRAWL,
    *,
    on_tick: WaitTick | None = None,
    frontier: Frontier | None = None,
    phase: int | None = None,
) -> DaemonState:
    """Espera el cooldown, un probe; si sigue bloqueado, dobla y repite."""
    via = egress_via(cfg)
    ph = int(phase) if phase is not None else 0

    def _tick(left: float, mode: str) -> None:
        attach_snapshot(
            frontier=frontier,
            state=state,
            phase=ph or None,
            cooldown_remaining=left if mode == "wait" else 0.0,
            cfg=cfg,
        )
        if on_tick is not None:
            on_tick(left, mode)

    with start_span(
        "daemon.cooldown",
        **{
            "fragrantica.reason": state.last_reason,
            "fragrantica.phase": ph,
            "fragrantica.via": via,
        },
    ):
        while True:
            wait = remaining_wait(
                state.last_block_at, state.last_reason, state.consecutive_blocks, cfg=cfg
            )
            if wait > 0:
                record_cooldown(
                    reason=state.last_reason,
                    duration_s=wait,
                    phase=ph,
                    via=via,
                    kind="page",
                )
                if on_tick is None:
                    console.print(
                        f"[yellow]Cooldown {state.last_reason}: "
                        f"{wait / 60:.1f} min (#{state.consecutive_blocks + 1})[/yellow]"
                    )
                _tick(wait, "wait")
                await sleep_countdown(
                    wait, on_tick=_tick, announce=on_tick is None
                )

            if on_tick is None:
                console.print("[bold]probe[/bold]: un request para ver si se puede reanudar")
            _tick(0.0, "probe")
            with start_span("daemon.probe", **{"fragrantica.reason": state.last_reason}):
                result = await asyncio.to_thread(probe_site, cfg)
            if result.ok:
                console.print(
                    f"[green]probe OK[/green] {result.status} {result.nbytes:,} bytes"
                )
                state = DaemonState()
                save_state(state_path, state)
                attach_snapshot(frontier=frontier, state=state, cooldown_remaining=0.0)
                return state

            reason = result.blocked or "other"
            state = DaemonState(
                consecutive_blocks=state.consecutive_blocks + 1,
                last_reason=reason if reason in ("429", "challenge") else "challenge",
                last_block_at=time.time(),
            )
            save_state(state_path, state)
            nxt = cooldown_seconds(state.last_reason, state.consecutive_blocks, cfg)
            attach_snapshot(frontier=frontier, state=state, cooldown_remaining=nxt, cfg=cfg)
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
    """Fase 1 (indice + marcas), 2 y 3, hasta vaciar las colas o Ctrl-C."""
    state = seed_state_from_frontier(load_state(state_path), frontier)
    save_state(state_path, state)

    # Fase 2 es prioridad. Un 429 guardado no manda a perfiles al arrancar:
    # si rotaron la IP, el cupo de /perfume/ esta limpio. El desvio a fase 3
    # solo ocurre cuando un 429 sale en ESTE ciclo. Un challenge si espera:
    # crawlear a ciegas despues del interstitial es lo que quemo la IP.
    skip_perfume = False
    if state.last_block_at > 0 and state.last_reason != "429":
        attach_snapshot(frontier=frontier, state=state)
        state = await wait_until_clear(
            state, state_path, cfg, frontier=frontier, phase=next_phase(frontier) or 0
        )

    # Un fetch del indice A-Z por proceso. Tras eso, solo se drena lo pending.
    catalog_seeded = False

    while True:
        phase = next_phase(
            frontier,
            seed_catalog=not catalog_seeded and not skip_perfume,
            skip_kinds=("perfume",) if skip_perfume else (),
        )
        attach_snapshot(
            frontier=frontier, state=state, phase=phase or 0, cooldown_remaining=0.0
        )
        if phase is None:
            if skip_perfume and next_phase(frontier) is not None:
                # Perfiles vacios, perfume sigue en cola: ahora si el probe.
                skip_perfume = False
                console.print(
                    "[yellow]Perfiles drenados.[/yellow] Probe para ver si "
                    "volvio el cupo de /perfume/."
                )
                if state.last_block_at > 0:
                    state = await wait_until_clear(
                        state, state_path, cfg, frontier=frontier, phase=2
                    )
                continue
            console.print(
                "[bold green]Colas de marca, perfume, perfil y shelves vacias.[/bold green] "
                "Siguiente: [bold]fragrantica phase 5[/bold] y "
                "[bold]fragrantica phase 6[/bold] (6 es local)."
            )
            return

        console.print(
            f"[bold]Ciclo fase {phase}[/bold] "
            f"(delay {cfg.delay_min:.0f}-{cfg.delay_max:.0f}s, 1 worker)"
        )
        try:
            with start_span("daemon.cycle", **{"fragrantica.phase": phase}):
                async with Client(cfg) as client:
                    if phase == 1:
                        await phase1_enumerate(frontier, client, staging)
                        catalog_seeded = True
                    elif phase == 2:
                        await phase2_perfumes(frontier, client, staging)
                    else:
                        await phase3_profiles(
                            frontier, client, staging, state_path=state_path
                        )
        except StopCrawl as exc:
            record_block(exc.reason)
            if (
                exc.reason == "429"
                and phase == 2
                and can_divert_perfume_429(frontier)
            ):
                skip_perfume = True
                state = DaemonState(
                    consecutive_blocks=0,
                    last_reason="429",
                    last_block_at=time.time(),
                )
                save_state(state_path, state)
                attach_snapshot(frontier=frontier, state=state, phase=3)
                console.print(
                    f"[red]ciclo cortado (429 de perfume)[/red]: {exc}\n"
                    "El cupo es de /perfume/, no de la IP. Sigo con perfiles."
                )
                continue
            skip_perfume = False
            # Challenge, o 429 de perfil, o perfume 429 sin cola de users.
            state = DaemonState(
                consecutive_blocks=0,
                last_reason=exc.reason,
                last_block_at=time.time(),
            )
            save_state(state_path, state)
            attach_snapshot(frontier=frontier, state=state, phase=phase)
            console.print(
                f"[red]ciclo cortado ({exc.reason})[/red]: {exc}\n"
                "El proceso sigue vivo. Espera + probe; no hace falta relanzar."
            )
            state = await wait_until_clear(
                state, state_path, cfg, frontier=frontier, phase=phase
            )
            continue

        if skip_perfume and phase == 3:
            skip_perfume = False
            console.print(
                "[yellow]Perfiles drenados.[/yellow] Probe para ver si "
                "volvio el cupo de /perfume/."
            )
            if state.last_block_at > 0:
                state = await wait_until_clear(
                    state, state_path, cfg, frontier=frontier, phase=2
                )
            continue

        state = DaemonState()
        save_state(state_path, state)
        attach_snapshot(frontier=frontier, state=state, phase=phase, cooldown_remaining=0.0)
        log.info("fase %s vacia, paso a la siguiente", phase)
