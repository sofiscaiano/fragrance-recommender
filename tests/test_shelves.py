"""Parser de wardrobe / votos a partir del JSON ya descifrado."""

from fragrantica.config import CrawlConfig
from fragrantica.http_client import Client, FetchError, RateLimited
from fragrantica.models import User
from fragrantica.parsers.shelves import parse_shelves
from fragrantica.pipeline.phases import _shelves_for_profile

import pytest


def test_wardrobe_and_votes_from_named_keys():
    payload = {
        "wardrobe": [
            {"parfem_id": 31861, "relation": "have"},
            {"parfem_id": 109081, "relation": "had"},
        ],
        "myvotes": [
            {
                "parfem_id": 1,
                "perfume_votes": {
                    "rating": 5,
                    "winter": 1,
                    "spring": 0,
                    "summer": 0,
                    "autumn": 1,
                    "day": 0,
                    "night": 1,
                    "longevity": 4,
                    "sillage": 3,
                    "gender": None,
                    "relation": None,
                },
            }
        ],
        "custom": [{"parfem_id": 99, "relation": "have"}],
    }
    parsed = parse_shelves(payload, member_id=3158387, slug="quilter")
    wardrobe_ids = {r.perfume_id for r in parsed.wardrobe}
    vote_ids = {r.perfume_id for r in parsed.votes}
    assert wardrobe_ids == {31861, 109081}
    assert vote_ids == {1}
    # Los estantes custom no son la coleccion ni el voto.
    assert 99 not in wardrobe_ids
    assert all(r.review_id is None for r in parsed.votes)
    assert all(r.member_id == 3158387 for r in parsed.votes)
    assert all(r.member_id == 3158387 for r in parsed.wardrobe)
    have = next(r for r in parsed.wardrobe if r.perfume_id == 31861)
    assert have.relation == "have"
    vote = next(r for r in parsed.votes if r.perfume_id == 1)
    assert vote.rating == 5
    assert vote.season_winter == 1
    assert vote.source == "vote"


def test_list_of_typed_shelves():
    payload = [
        {"type": "wardrobe", "items": [{"perfume_id": 10, "relation": "want"}]},
        {"type": "myvotes", "items": [{"parfem_id": 2, "rating": 4}]},
    ]
    parsed = parse_shelves(payload, member_id=1, slug="u")
    assert len(parsed.wardrobe) == 1
    assert parsed.wardrobe[0].perfume_id == 10
    assert parsed.wardrobe[0].relation == "want"
    assert len(parsed.votes) == 1
    assert parsed.votes[0].perfume_id == 2
    assert parsed.votes[0].rating == 4


def test_rating_zero_on_vote_is_absent():
    payload = {"myvotes": [{"parfem_id": 7, "perfume_votes": {"rating": 0, "longevity": 0}}]}
    parsed = parse_shelves(payload, member_id=1, slug="u")
    assert parsed.wardrobe == []
    assert len(parsed.votes) == 1
    assert parsed.votes[0].source == "vote"
    assert parsed.votes[0].rating is None


def test_ajax_shelves_use_id_and_shelf_value():
    """Payload vivo: perfumes[].id y have/had/want / rating en el estante."""
    payload = [
        {
            "field": "relation",
            "value": "have",
            "name": "Perfumes I Have",
            "type": "wardrobe",
            "perfumes": [
                {"id": 219, "naslov": "Hypnotic Poison", "dizajner": "Dior",
                 "url": "/perfume/Dior/Hypnotic-Poison-219.html"},
            ],
        },
        {
            "field": "rating",
            "value": 5,
            "name": "love",
            "type": "myvotes",
            "perfumes": [
                {"id": 15452, "naslov": "Alien Essence Absolue", "dizajner": "Mugler",
                 "url": "/perfume/Mugler/Alien-Essence-Absolue-15452.html"},
            ],
        },
        {
            "field": "for_test",
            "value": 1,
            "name": "for test",
            "type": "wardrobe",
            "perfumes": [
                {"id": 99, "naslov": "Skip me", "dizajner": "X",
                 "url": "/perfume/X/Skip-99.html"},
            ],
        },
    ]
    parsed = parse_shelves(payload, member_id=1986300, slug="bansheesmile")
    assert [(w.perfume_id, w.relation) for w in parsed.wardrobe] == [(219, "have")]
    assert len(parsed.votes) == 1
    assert parsed.votes[0].perfume_id == 15452
    assert parsed.votes[0].rating == 5
    assert parsed.votes[0].source == "vote"
    payload = {"myvotes": [{"parfem_id": 7, "perfume_votes": {"rating": 0, "longevity": 0}}]}
    parsed = parse_shelves(payload, member_id=1, slug="u")
    assert parsed.wardrobe == []
    assert len(parsed.votes) == 1
    assert parsed.votes[0].source == "vote"
    assert parsed.votes[0].rating is None


# -- politica de fetch: 429 de ajax no tumba el perfil ----------------------


CFG_PAUSE = CrawlConfig(shelves_cooldown=3600.0)


def _user() -> User:
    return User(member_id=1, username_slug="u")


def test_pause_shelves_blocks_then_expires() -> None:
    client = Client(CFG_PAUSE)
    assert client.should_fetch_shelves(now=1000.0) is True
    client.pause_shelves("HTTP 429 en ajax", now=1000.0)
    assert client.shelves_paused(now=1000.0)
    assert client.should_fetch_shelves(now=1000.0) is False
    assert client.should_fetch_shelves(now=1000.0 + 3599) is False
    assert client.should_fetch_shelves(now=1000.0 + 3600) is True
    assert client.shelves_paused(now=1000.0 + 3600) is False


def test_disable_shelves_outlives_the_pause() -> None:
    client = Client(CFG_PAUSE)
    client.pause_shelves("429", now=1.0)
    client.disable_shelves("403")
    assert client.should_fetch_shelves(now=10_000.0) is False


class _Ajax429(Client):
    def __init__(self) -> None:
        super().__init__(CFG_PAUSE)
        self.posts = 0

    async def post(self, url, *, data, worker=0, referer=None):
        self.posts += 1
        raise RateLimited(f"HTTP 429 en {url}")

    async def ensure_passphrase(self, sample_html="", *, worker=0):
        return "pw"


async def test_ajax_429_raises_and_pauses() -> None:
    client = _Ajax429()
    user = _user()

    with pytest.raises(RateLimited):
        await _shelves_for_profile(
            client, "<html>", user, "https://www.fragrantica.com/@u"
        )
    assert client.posts == 1
    assert client.shelves_paused()

    with pytest.raises(FetchError):
        await _shelves_for_profile(
            client, "<html>", user, "https://www.fragrantica.com/@u"
        )
    assert client.posts == 1


def test_shelves_proxy_is_only_for_post_worker() -> None:
    from fragrantica.http_client import SHELVES_WORKER

    cfg = CrawlConfig(
        shelves_proxies=("http://shelf.example:9",),
        proxies=("http://home.example:8",),
    )
    client = Client(cfg)
    assert client._proxy_for(SHELVES_WORKER) == "http://shelf.example:9"
    assert client._proxy_for(0) == "http://home.example:8"


def test_enqueue_missing_skips_who_already_has_wardrobe(tmp_path) -> None:
    from fragrantica.frontier import Frontier
    from fragrantica.models import WardrobeItem
    from fragrantica.pipeline.phases import enqueue_missing_shelves
    from fragrantica.storage import ParquetWriter

    fr = Frontier(tmp_path / "f.db")
    fr.record_member_id("has", 10)
    fr.record_member_id("missing", 20)
    w = ParquetWriter(tmp_path, "wardrobe")
    w.add(WardrobeItem(member_id=10, username_slug="has", perfume_id=1, relation="have"))
    w.flush()
    n = enqueue_missing_shelves(fr, tmp_path)
    assert n == 1
    assert fr.claim_shelves(1)[0]["member_id"] == 20
    assert enqueue_missing_shelves(fr, tmp_path) == 0
    fr.close()
