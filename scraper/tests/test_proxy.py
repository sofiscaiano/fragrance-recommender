"""Puerto sticky: se queda mientras responde y rota solo cuando ese puerto falla."""

import logging

import pytest

from fragrantica.config import CrawlConfig
from fragrantica.http_client import (
    SHELVES_WORKER,
    ChallengeDetected,
    Client,
    FetchError,
    RateLimited,
    proxy_label,
)
from fragrantica import http_client

OK = "<main itemprop='n' fragrantica>ok</main>"
PAGE = "https://www.fragrantica.com/perfume/Dior/Sauvage-31861.html"
AJAX = "https://www.fragrantica.com/ajax.php?user_shelves"


class _Resp:
    def __init__(self, status: int, body: str = "", headers: dict | None = None) -> None:
        self.status_code = status
        self.text = body
        self.headers = headers or {}


def _install(monkeypatch: pytest.MonkeyPatch, scripts: dict[str, list]) -> list[str]:
    created: list[str] = []

    def factory(*_args, **kwargs):
        proxy = kwargs["proxy"]
        created.append(proxy)
        script = scripts[proxy]

        class _Session:
            async def get(self, url, headers=None, allow_redirects=True):
                item = script.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item

            async def post(self, url, data=None, headers=None, allow_redirects=True):
                return await self.get(url)

            async def close(self):
                return None

        return _Session()

    monkeypatch.setattr(http_client.cffi, "AsyncSession", factory)
    return created


def _cfg(**overrides) -> CrawlConfig:
    params = {
        "delay_min": 0.0,
        "delay_max": 0.0,
        "cooldown_429": 300.0,
        "rate_limit_pause": 0.0,
    }
    params.update(overrides)
    return CrawlConfig(**params)


async def test_sticks_to_one_port_across_requests(monkeypatch) -> None:
    a, b = "http://gw.example:1", "http://gw.example:2"
    created = _install(monkeypatch, {a: [_Resp(200, OK), _Resp(200, OK)], b: []})
    client = Client(_cfg(proxies=(a, b)))
    first = await client.fetch(PAGE)
    second = await client.fetch(PAGE)
    assert first.status == second.status == 200
    assert created == [a]


async def test_tls_refresh_keeps_the_same_port(monkeypatch) -> None:
    a, b = "http://gw.example:1", "http://gw.example:2"
    created = _install(monkeypatch, {a: [_Resp(200, OK), _Resp(200, OK)], b: []})
    client = Client(_cfg(proxies=(a, b), requests_per_session=1))
    await client.fetch(PAGE)
    await client.fetch(PAGE)
    assert created == [a, a]


async def test_429_retries_on_the_next_port_without_global_pause(monkeypatch) -> None:
    a, b, c = "http://gw.example:1", "http://gw.example:2", "http://gw.example:3"
    created = _install(
        monkeypatch,
        {a: [_Resp(429, "")], b: [_Resp(200, OK)], c: [_Resp(200, OK)]},
    )
    client = Client(_cfg(proxies=(a, b, c)))
    result = await client.fetch(PAGE)
    assert result.status == 200
    assert created == [a, b]
    assert client._paused_until == 0
    assert client._cooled["page"][a] > client._cooled["page"].get(b, 0)


async def test_single_proxy_429_still_pauses(monkeypatch) -> None:
    a = "http://gw.example:1"
    _install(monkeypatch, {a: [_Resp(429, "")]})
    client = Client(_cfg(proxies=(a,)))
    with pytest.raises(RateLimited):
        await client.fetch(PAGE)
    assert client._paused_until > 0
    assert client._cooled["page"] == {}


async def test_exhausted_pool_does_not_open_another_session(monkeypatch) -> None:
    a, b = "http://gw.example:1", "http://gw.example:2"
    created = _install(monkeypatch, {a: [_Resp(429, "")], b: [_Resp(429, "")]})
    client = Client(_cfg(proxies=(a, b)))
    with pytest.raises(RateLimited):
        await client.fetch(PAGE)
    opened = len(created)
    with pytest.raises(RateLimited):
        await client.fetch(PAGE)
    assert len(created) == opened


async def test_interstitial_stays_on_the_same_port(monkeypatch) -> None:
    a, b = "http://gw.example:1", "http://gw.example:2"
    created = _install(
        monkeypatch,
        {a: [_Resp(200, "Just a moment")], b: [_Resp(200, OK)]},
    )
    client = Client(_cfg(proxies=(a, b)))
    with pytest.raises(ChallengeDetected):
        await client.fetch(PAGE)
    assert created == [a]
    assert client._cooled["page"] == {}


async def test_canary_429_does_not_hop(monkeypatch) -> None:
    a, b = "http://gw.example:1", "http://gw.example:2"
    created = _install(monkeypatch, {a: [_Resp(429, "")], b: [_Resp(200, OK)]})
    client = Client(_cfg(proxies=(a, b)))
    with pytest.raises(RateLimited):
        await client.canary_ok()
    assert created == [a]


async def test_network_error_rotates_and_redacts_credentials(monkeypatch, caplog) -> None:
    a = "http://user:secret-pass@gw.example:10001"
    b = "http://user:secret-pass@gw.example:10002"
    created = _install(
        monkeypatch,
        {
            a: [ConnectionError(f"connect {a}")],
            b: [_Resp(200, OK)],
        },
    )
    client = Client(_cfg(proxies=(a, b)))
    with caplog.at_level(logging.WARNING):
        result = await client.fetch(PAGE)
    assert result.status == 200
    assert created == [a, b]
    assert "secret-pass" not in caplog.text
    assert proxy_label(a) in caplog.text


async def test_network_error_on_one_proxy_is_a_fetch_error(monkeypatch) -> None:
    a = "http://user:secret-pass@gw.example:9"
    _install(monkeypatch, {a: [ConnectionError(f"connect {a}")]})
    client = Client(_cfg(proxies=(a,)))
    with pytest.raises(FetchError) as exc:
        await client.fetch(PAGE)
    assert "secret-pass" not in str(exc.value)


async def test_origin_5xx_does_not_rotate(monkeypatch) -> None:
    a, b = "http://gw.example:1", "http://gw.example:2"
    created = _install(monkeypatch, {a: [_Resp(500, OK)], b: [_Resp(200, OK)]})
    client = Client(_cfg(proxies=(a, b)))
    with pytest.raises(FetchError):
        await client.fetch(PAGE)
    assert created == [a]


async def test_retry_after_extends_port_cooldown(monkeypatch) -> None:
    a, b = "http://gw.example:1", "http://gw.example:2"
    _install(
        monkeypatch,
        {a: [_Resp(429, "", {"Retry-After": "500"})], b: [_Resp(200, OK)]},
    )
    client = Client(_cfg(proxies=(a, b), cooldown_429=10))
    await client.fetch(PAGE)
    import time

    assert client._cooled["page"][a] >= time.time() + 499


async def test_shelves_429_rotates_its_own_pool(monkeypatch) -> None:
    page = ("http://page.example:1", "http://page.example:2")
    shelves = ("http://shelf.example:1", "http://shelf.example:2")
    created = _install(
        monkeypatch,
        {
            page[0]: [_Resp(200, OK)],
            page[1]: [],
            shelves[0]: [_Resp(429, "")],
            shelves[1]: [_Resp(200, OK)],
        },
    )
    client = Client(_cfg(proxies=page, shelves_proxies=shelves))
    await client.fetch(PAGE)
    result = await client.post(AJAX, data={"action": "user_shelves"})
    assert result.status == 200
    assert created == [page[0], shelves[0], shelves[1]]
    assert page[0] not in client._cooled["page"]
    assert shelves[0] in client._cooled["shelves"]
    assert client._pin[0] == page[0]


async def test_ajax_429_on_shared_ip_does_not_drop_the_page_port(monkeypatch) -> None:
    a, b = "http://gw.example:1", "http://gw.example:2"
    created = _install(monkeypatch, {a: [_Resp(200, OK), _Resp(429, "")], b: []})
    client = Client(_cfg(proxies=(a, b)))
    await client.fetch(PAGE)
    with pytest.raises(RateLimited):
        await client.post(AJAX, data={"action": "user_shelves"}, worker=SHELVES_WORKER)
    assert created == [a, a]
    assert client._cooled["page"] == {}
    assert client._pin[0] == a
    assert client._paused_until == 0


def test_proxy_label_strips_userinfo() -> None:
    assert proxy_label("http://user:secret-pass@gw.example:10001") == "gw.example:10001"
