"""Watchdog: cooldowns y eleccion de fase, sin red."""

from pathlib import Path

from fragrantica.config import CrawlConfig
from fragrantica.frontier import Frontier
from fragrantica.pipeline.daemon import (
    DaemonState,
    cooldown_seconds,
    format_cooldown_left,
    latest_block,
    next_phase,
    reason_from_error,
    remaining_wait,
    seed_state_from_frontier,
)
from fragrantica.pipeline.runner import StopCrawl


CFG = CrawlConfig(
    delay_min=20,
    delay_max=40,
    cooldown_429=900,
    cooldown_challenge=1800,
    cooldown_cap=21600,
)


def test_format_cooldown_left() -> None:
    assert format_cooldown_left(300) == "5.0 min"
    assert format_cooldown_left(90) == "1.5 min"
    assert format_cooldown_left(12) == "12 s"
    assert format_cooldown_left(0) == "0 s"


def test_cooldown_doubles_until_cap() -> None:
    assert cooldown_seconds("challenge", 0, CFG) == 1800
    assert cooldown_seconds("challenge", 1, CFG) == 3600
    assert cooldown_seconds("challenge", 2, CFG) == 7200
    assert cooldown_seconds("429", 0, CFG) == 900
    assert cooldown_seconds("challenge", 10, CFG) == 21600


def test_remaining_wait_respects_elapsed() -> None:
    now = 1_000_000.0
    last = now - 600  # hace 10 min
    left = remaining_wait(last, "challenge", 0, now=now, cfg=CFG)
    assert abs(left - 1200) < 0.01  # 30 min - 10 min
    assert remaining_wait(last, "challenge", 0, now=now + 2000, cfg=CFG) == 0.0
    assert remaining_wait(0, "challenge", 0, now=now, cfg=CFG) == 0.0


def test_reason_from_error() -> None:
    assert reason_from_error("HTTP 429 / interstitial") == "429"
    assert reason_from_error("HTTP 200 / interstitial en https://x") == "challenge"
    assert StopCrawl("bloqueado", reason="challenge").reason == "challenge"


def test_next_phase_prefers_perfumes(tmp_path: Path) -> None:
    fr = Frontier(tmp_path / "f.db")
    assert next_phase(fr) is None
    fr.add("https://x/@a", "profile", "a")
    assert next_phase(fr) == 3
    fr.add("https://x/p", "perfume", "1")
    assert next_phase(fr) == 2
    fr.close()


def test_next_phase_prefers_designers(tmp_path: Path) -> None:
    fr = Frontier(tmp_path / "f.db")
    fr.add("https://x/@a", "profile", "a")
    fr.add("https://x/p", "perfume", "1")
    fr.add("https://x/designers/Chanel.html", "designer", "Chanel")
    assert next_phase(fr) == 1
    fr.close()


def test_next_phase_seed_catalog_even_if_queues_empty(tmp_path: Path) -> None:
    """Sin esto el daemon se iria con el slice Dior cerrado y no enumeraria el resto."""
    fr = Frontier(tmp_path / "f.db")
    assert next_phase(fr) is None
    assert next_phase(fr, seed_catalog=True) == 1
    fr.add("https://x/p", "perfume", "1")
    assert next_phase(fr, seed_catalog=True) == 1
    assert next_phase(fr) == 2
    fr.close()


def test_next_phase_ignores_quarantined_perfume(tmp_path: Path) -> None:
    fr = Frontier(tmp_path / "f.db")
    fr.add("https://x/p", "perfume", "1")
    fr.add("https://x/@a", "profile", "a")
    fr.mark_deferred("https://x/p", "interstitial", delay=86_400)
    assert next_phase(fr) == 3
    fr.close()


def test_seed_state_inherits_frontier_block(tmp_path: Path) -> None:
    fr = Frontier(tmp_path / "f.db")
    fr.add("https://x/p", "perfume", "1")
    fr.requeue("https://x/p", "HTTP 200 / interstitial en https://x/p", delay=0)
    ts, reason = latest_block(fr)
    assert reason == "challenge"
    assert ts > 0
    seeded = seed_state_from_frontier(DaemonState(), fr)
    assert seeded.last_reason == "challenge"
    assert seeded.last_block_at == ts
    fr.close()


def test_next_phase_stays_on_3_when_only_shelves_remain(tmp_path: Path) -> None:
    fr = Frontier(tmp_path / "f.db")
    assert next_phase(fr) is None
    fr.enqueue_shelves(1, "a", "https://www.fragrantica.com/@a")
    assert next_phase(fr) == 3
    fr.close()
