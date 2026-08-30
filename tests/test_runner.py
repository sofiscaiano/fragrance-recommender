"""El runner corta el proceso ante 429 / 403; no se queda reintentando solo."""

from pathlib import Path

import pytest

from fragrantica.frontier import Frontier
from fragrantica.http_client import ChallengeDetected, RateLimited
from fragrantica.pipeline.runner import AlreadyHave, StopCrawl, run_phase
from fragrantica.storage import ParquetWriter


class _Boom:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def fetch(self, url: str, *, worker: int = 0, referer=None, kind="html"):
        raise self.exc

    async def canary_ok(self, *, worker: int = 0) -> bool:
        try:
            await self.fetch("https://canary", worker=worker)
        except ChallengeDetected:
            return False
        except RateLimited:
            raise
        return True


@pytest.mark.asyncio
async def test_429_stops_the_process(tmp_path: Path) -> None:
    fr = Frontier(tmp_path / "f.db")
    fr.add("https://x/1", "perfume", "1")
    writer = ParquetWriter(tmp_path, "dummy")
    with writer:
        with pytest.raises(StopCrawl, match="429"):
            await run_phase(
                name="test",
                kind="perfume",
                frontier=fr,
                client=_Boom(RateLimited("HTTP 429 en https://x/1")),
                writers={"dummy": writer},
                handler=lambda *_: {},
            )
    pending = fr.conn.execute(
        "SELECT status FROM frontier WHERE url = 'https://x/1'"
    ).fetchone()
    assert pending["status"] == "pending"
    fr.close()


@pytest.mark.asyncio
async def test_403_stops_the_process(tmp_path: Path) -> None:
    fr = Frontier(tmp_path / "f.db")
    fr.add("https://x/1", "perfume", "1")
    writer = ParquetWriter(tmp_path, "dummy")
    with writer:
        with pytest.raises(StopCrawl, match="Cloudflare"):
            await run_phase(
                name="test",
                kind="perfume",
                frontier=fr,
                client=_Boom(ChallengeDetected("HTTP 403 / interstitial en https://x/1")),
                writers={"dummy": writer},
                handler=lambda *_: {},
            )
    fr.close()


@pytest.mark.asyncio
async def test_already_have_skips_the_request(tmp_path: Path) -> None:
    """Si el precheck dice que ya esta, no hay GET."""
    fr = Frontier(tmp_path / "f.db")
    fr.add("https://x/1", "perfume", "1")
    writer = ParquetWriter(tmp_path, "dummy")
    fetches: list[str] = []

    class _Spy:
        async def fetch(self, url: str, *, worker: int = 0, referer=None, kind="html"):
            fetches.append(url)
            raise AssertionError("no deberia pedirse")

    def precheck(url: str, entity_id: str) -> None:
        raise AlreadyHave()

    with writer:
        await run_phase(
            name="test",
            kind="perfume",
            frontier=fr,
            client=_Spy(),
            writers={"dummy": writer},
            handler=lambda *_: {},
            precheck=precheck,
        )
    assert fetches == []
    status = fr.conn.execute("SELECT status FROM frontier").fetchone()["status"]
    assert status == "done"
    fr.close()


@pytest.mark.asyncio
async def test_interstitial_defers_when_canary_ok(tmp_path: Path) -> None:
    """Sauvage pasa: la URL rara va a cuarentena y el lote no se corta."""
    fr = Frontier(tmp_path / "f.db")
    fr.add("https://x/poison", "perfume", "1")
    writer = ParquetWriter(tmp_path, "dummy")

    class _Poison:
        async def fetch(self, url: str, *, worker: int = 0, referer=None, kind="html"):
            raise ChallengeDetected(f"HTTP 200 / interstitial en {url}")

        async def canary_ok(self, *, worker: int = 0) -> bool:
            return True

    with writer:
        stats = await run_phase(
            name="test",
            kind="perfume",
            frontier=fr,
            client=_Poison(),
            writers={"dummy": writer},
            handler=lambda *_: {},
        )
    row = fr.conn.execute(
        "SELECT status FROM frontier WHERE url='https://x/poison'"
    ).fetchone()
    assert row["status"] == "deferred"
    assert stats.deferred == 1
    fr.close()


@pytest.mark.asyncio
async def test_interstitial_stops_when_canary_fails(tmp_path: Path) -> None:
    fr = Frontier(tmp_path / "f.db")
    fr.add("https://x/1", "perfume", "1")
    writer = ParquetWriter(tmp_path, "dummy")

    class _BothBlocked:
        async def fetch(self, url: str, *, worker: int = 0, referer=None, kind="html"):
            raise ChallengeDetected(f"HTTP 200 / interstitial en {url}")

        async def canary_ok(self, *, worker: int = 0) -> bool:
            return False

    with writer:
        with pytest.raises(StopCrawl, match="Cloudflare"):
            await run_phase(
                name="test",
                kind="perfume",
                frontier=fr,
                client=_BothBlocked(),
                writers={"dummy": writer},
                handler=lambda *_: {},
            )
    row = fr.conn.execute("SELECT status FROM frontier").fetchone()
    assert row["status"] == "pending"
    fr.close()
