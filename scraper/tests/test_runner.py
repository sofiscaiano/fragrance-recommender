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


@pytest.mark.asyncio
async def test_interstitial_rotates_when_another_port_is_free(tmp_path: Path) -> None:
    """Canario falla y hay otro puerto: no es StopCrawl. La URL se vuelve a pedir."""
    fr = Frontier(tmp_path / "f.db")
    fr.add("https://x/poison", "perfume", "1")
    writer = ParquetWriter(tmp_path, "dummy")

    class _Switch:
        def __init__(self) -> None:
            self.fetches = 0
            self.retired: list[str] = []

        async def fetch(self, url: str, *, worker: int = 0, referer=None, kind="html"):
            self.fetches += 1
            if self.fetches == 1:
                raise ChallengeDetected(f"HTTP 200 / interstitial en {url}")
            return type("R", (), {"body": "<main fragrantica>"})()

        async def canary_ok(self, *, worker: int = 0) -> bool:
            return False

        async def retire_egress(self, worker: int, reason: str, *, seconds=None) -> bool:
            self.retired.append(reason)
            return True

    client = _Switch()
    with writer:
        stats = await run_phase(
            name="test",
            kind="perfume",
            frontier=fr,
            client=client,
            writers={"dummy": writer},
            handler=lambda *_: {},
        )
    row = fr.conn.execute(
        "SELECT status FROM frontier WHERE url='https://x/poison'"
    ).fetchone()
    assert row["status"] == "done"
    assert stats.done == 1
    assert client.retired == ["challenge"]
    assert client.fetches == 2
    fr.close()


@pytest.mark.asyncio
async def test_canary_ok_does_not_retire_the_port(tmp_path: Path) -> None:
    fr = Frontier(tmp_path / "f.db")
    fr.add("https://x/poison", "perfume", "1")
    writer = ParquetWriter(tmp_path, "dummy")

    class _Keep:
        async def fetch(self, url: str, *, worker: int = 0, referer=None, kind="html"):
            raise ChallengeDetected(f"HTTP 200 / interstitial en {url}")

        async def canary_ok(self, *, worker: int = 0) -> bool:
            return True

        async def retire_egress(self, worker: int, reason: str, *, seconds=None) -> bool:
            raise AssertionError("el canario paso: el puerto sigue sirviendo")

    with writer:
        await run_phase(
            name="test",
            kind="perfume",
            frontier=fr,
            client=_Keep(),
            writers={"dummy": writer},
            handler=lambda *_: {},
        )
    row = fr.conn.execute("SELECT status FROM frontier").fetchone()
    assert row["status"] == "deferred"
    fr.close()


@pytest.mark.asyncio
async def test_ajax_429_does_not_stop_profile_phase(tmp_path: Path) -> None:
    """El GET del perfil se confirma done; el POST queda en shelves_jobs."""
    from fragrantica.http_client import FetchResult
    from fragrantica.models import User
    from fragrantica.pipeline.phases import enqueue_missing_shelves

    class _HtmlOk:
        async def fetch(self, url: str, *, worker: int = 0, referer=None, kind="html"):
            # parse_profile needs real-ish html? handler is custom
            return FetchResult(url=url, status=200, body="<html>", elapsed=0.0)

    fr = Frontier(tmp_path / "f.db")
    fr.add("https://www.fragrantica.com/@one", "profile", "one")
    writer = ParquetWriter(tmp_path, "users")
    user = User(member_id=42, username_slug="one")

    async def handler(url: str, entity_id: str, body: str) -> dict:
        fr.record_member_id(user.username_slug, user.member_id)
        fr.enqueue_shelves(user.member_id, user.username_slug, url)
        return {"users": [user]}

    with writer:
        stats = await run_phase(
            name="test",
            kind="profile",
            frontier=fr,
            client=_HtmlOk(),
            writers={"users": writer},
            handler=handler,
        )
    assert stats.done == 1
    assert stats.rate_limited == 0
    assert fr.conn.execute("SELECT status FROM frontier").fetchone()["status"] == "done"
    assert fr.shelves_pending_count() == 1
    # backfill no duplica
    assert enqueue_missing_shelves(fr, tmp_path) == 0
    fr.close()


@pytest.mark.asyncio
async def test_phase3_html_429_cools_down_without_killing_shelves(tmp_path: Path) -> None:
    """Un 429 de GET no corta los POST: cooldown de esa tarea y reanuda."""
    import asyncio

    from fragrantica.config import CrawlConfig
    from fragrantica.http_client import FetchResult
    from fragrantica.parsers.shelves import ParsedShelves
    from fragrantica.pipeline.phases import phase3_profiles
    from fragrantica.pipeline.runner import StopCrawl

    html = (Path(__file__).parent / "fixtures" / "profile_quilter.html").read_text()
    shelves_during_html_wait: list[int] = []
    html_in_cooldown = asyncio.Event()

    class _Client:
        def __init__(self) -> None:
            self.cfg = CrawlConfig(
                fetch_shelves=True,
                delay_min=0,
                delay_max=0,
                rate_limit_pause=0,
            )
            self.gets = 0
            self._shelves_disabled = False

        async def fetch(self, url: str, *, worker: int = 0, referer=None, kind="html"):
            self.gets += 1
            if self.gets == 1:
                raise RateLimited(f"HTTP 429 en {url}", retry_after=0.1)
            return FetchResult(url=url, status=200, body=html, elapsed=0.0)

        def shelves_paused(self, *, now: float | None = None) -> bool:
            return False

        def shelves_pause_remaining(self, *, now: float | None = None) -> float:
            return 0.0

        def should_fetch_shelves(self, *, now: float | None = None) -> bool:
            return True

    async def cooldown(exc: StopCrawl, state_path: Path, cfg) -> None:
        assert exc.reason == "429"
        html_in_cooldown.set()
        await asyncio.sleep(0)

    async def fake_shelves(client, sample_html, user, profile_url):
        await html_in_cooldown.wait()
        shelves_during_html_wait.append(user.member_id)
        return ParsedShelves()

    import fragrantica.pipeline.phases as phases

    orig = phases._shelves_for_profile
    phases._shelves_for_profile = fake_shelves  # type: ignore[assignment]
    fr = Frontier(tmp_path / "f.db")
    fr.add("https://www.fragrantica.com/@quilter", "profile", "quilter")
    fr.enqueue_shelves(99, "other", "https://www.fragrantica.com/@other")
    client = _Client()
    try:
        await phase3_profiles(
            fr,
            client,  # type: ignore[arg-type]
            tmp_path,
            state_path=tmp_path / "daemon_state.json",
            html_cooldown=cooldown,
        )
        assert client.gets >= 2
        assert html_in_cooldown.is_set()
        assert 99 in shelves_during_html_wait
        row = fr.conn.execute(
            "SELECT status FROM frontier WHERE entity_id='quilter'"
        ).fetchone()
        assert row["status"] == "done"
        assert fr.conn.execute(
            "SELECT status FROM shelves_jobs WHERE member_id=99"
        ).fetchone()["status"] == "done"
    finally:
        phases._shelves_for_profile = orig
        fr.close()


def test_queue_progress_uses_frontier_totals(tmp_path: Path) -> None:
    from fragrantica.pipeline.runner import queue_progress

    fr = Frontier(tmp_path / "f.db")
    fr.add("https://x/1", "profile", "1")
    fr.add("https://x/2", "profile", "2")
    fr.mark_done("https://x/1")
    done, total, desc = queue_progress(fr, "profile", "perfiles HTML")
    assert done == 1
    assert total == 2
    assert "perfiles HTML" in desc
    assert "1 done" in desc
    assert "1 en cola" in desc
    fr.close()
