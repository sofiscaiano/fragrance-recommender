"""Ganchos que el crawl llama al pedir una página o al esperar un cooldown.

No emiten métricas. Existen para no mezclar ese registro con la lógica del crawl.
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from typing import Any, Iterator


def egress_via(cfg: Any | None = None, *, shelves: bool = False) -> str:
    """`home`, `proxy` o `shelves_proxy`. Nunca la URL: puede traer credenciales."""

    if cfg is None:
        from .config import CRAWL

        cfg = CRAWL
    if shelves and getattr(cfg, "shelves_proxies", ()):
        return "shelves_proxy"
    if getattr(cfg, "proxies", ()):
        return "proxy"
    return "home"


def kind_from_url(url: str, *, method: str = "GET") -> str:
    """Clasifica el request. Sin usernames ni query."""

    if method == "POST" or "ajax.php" in url:
        return "shelves"
    if "/designers" in url:
        return "designer"
    if "/perfume/" in url:
        return "perfume"
    if "/@" in url:
        return "profile"
    return "other"


def classify_http(
    status: int,
    *,
    interstitial: bool = False,
    network_error: bool = False,
) -> tuple[str, str]:
    """(outcome, status) de una respuesta. El interstitial gana sobre el código."""

    if network_error:
        return "error", "0"
    code = str(int(status))
    if interstitial:
        return "interstitial", code
    if status == 200:
        return "200", code
    if status in {403, 404, 429, 503}:
        return code, code
    return "error", code


def attach_snapshot(**_kwargs: Any) -> None:
    return None


def record_http(*_args: Any, **_kwargs: Any) -> None:
    return None


def record_records(*_args: Any, **_kwargs: Any) -> None:
    return None


def record_block(*_args: Any, **_kwargs: Any) -> None:
    return None


def record_cooldown(**_kwargs: Any) -> None:
    return None


def record_runner_outcome(*_args: Any, **_kwargs: Any) -> None:
    return None


@contextmanager
def start_span(_name: str, **_attrs: Any) -> Iterator[None]:
    yield None


def http_span(_kind: str, _method: str) -> Any:
    return nullcontext(None)
