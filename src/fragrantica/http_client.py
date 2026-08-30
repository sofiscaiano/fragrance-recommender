"""Cliente HTTP con impersonacion TLS.

Cloudflare en Fragrantica filtra por fingerprint TLS/HTTP2, no con un JS
challenge bloqueante. Verificado en el reconocimiento: curl normal recibe 403
"Just a moment" en toda pagina interior, mientras que curl_cffi con
impersonacion devuelve 200 con el contenido completo.

Por eso no hay navegador en el camino caliente: seria 20-50x mas lento sin
aportar nada. Queda como fallback documentado si aparece un challenge real.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import deque
from dataclasses import dataclass

from curl_cffi import requests as cffi

from .config import BASE_URL, CRAWL, CrawlConfig

PROBE_URL = f"{BASE_URL}/perfume/Dior/Sauvage-31861.html"

log = logging.getLogger(__name__)


class ChallengeDetected(Exception):
    """Cloudflare devolvio un interstitial en vez de contenido."""


class RateLimited(Exception):
    """HTTP 429: el sitio nos esta pidiendo explicitamente que bajemos el ritmo.

    Se distingue del challenge a proposito. Un 403/interstitial es un problema
    de fingerprint y se puede reintentar rapido; un 429 es el servidor diciendo
    "sos demasiado" y reintentar pronto solo empeora las cosas y es descortes.
    Merece una pausa global, no solo del worker que lo recibio.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class FetchError(Exception):
    """Fallo transitorio: vale reintentar."""


class NotFound(Exception):
    """404 real: no vale reintentar."""


# El script de challenge de Cloudflare esta embebido en TODAS las paginas,
# incluso las buenas. Buscarlo da falsos positivos (me paso en el
# reconocimiento). La deteccion correcta combina el marcador del interstitial
# con la AUSENCIA de contenido real.
_INTERSTITIAL_MARKERS = ("Just a moment", "Enable JavaScript and cookies to continue")
_REAL_CONTENT_MARKERS = ("<main", "itemprop=", "fragrantica")


def looks_like_challenge(body: str, *, kind: str = "html") -> bool:
    if any(m in body for m in _INTERSTITIAL_MARKERS):
        return True
    # La heuristic de cuerpo corto es solo para HTML. Un JSON cifrado de ajax
    # ({ct, iv, s}) es pequeno y no tiene <main: lo marcariamos mal.
    if kind != "html":
        return False
    # Un cuerpo muy corto sin marcadores de contenido tambien es sospechoso.
    if len(body) < 15_000 and not any(m in body.lower() for m in _REAL_CONTENT_MARKERS):
        return True
    return False


@dataclass
class FetchResult:
    url: str
    status: int
    body: str
    elapsed: float


@dataclass(frozen=True)
class ProbeResult:
    status: int
    nbytes: int
    ok: bool
    blocked: str | None  # None | "429" | "challenge" | "other"


def probe_site(cfg: CrawlConfig = CRAWL) -> ProbeResult:
    """Un GET a Sauvage. Lo usa el CLI y el daemon; no es un crawl.

    Un 200 corto con "Just a moment" no cuenta como OK: es el interstitial
    disfrazado de pagina. El umbral de 100 KB es el HTML real (~1,8 MB).
    """
    proxy = random.choice(cfg.proxies) if cfg.proxies else None
    resp = cffi.Session(impersonate="chrome", proxy=proxy).get(PROBE_URL, timeout=30)
    body = resp.text or ""
    nbytes = len(body)
    if resp.status_code == 429:
        return ProbeResult(resp.status_code, nbytes, False, "429")
    if resp.status_code in (403, 503) or looks_like_challenge(body):
        return ProbeResult(resp.status_code, nbytes, False, "challenge")
    if resp.status_code == 200 and nbytes > 100_000:
        return ProbeResult(resp.status_code, nbytes, True, None)
    return ProbeResult(resp.status_code, nbytes, False, "other")


class Client:
    """Pool de sesiones con rotacion de fingerprint y cortesia incorporada."""

    def __init__(self, cfg: CrawlConfig = CRAWL) -> None:
        self.cfg = cfg
        self._sessions: dict[int, tuple[cffi.AsyncSession, int, str]] = {}
        self._outcomes: deque[bool] = deque(maxlen=cfg.challenge_window)
        self._paused_until = 0.0
        self._lock = asyncio.Lock()
        self._passphrase_lock = asyncio.Lock()
        # Passphrase AES = _pd(host). None = todavia no se calculo;
        # _passphrase_failed evita reintentar si el canario no abre.
        self._passphrase: str | None = None
        self._passphrase_failed = False
        self._shelves_disabled = False
        self._shelves_decrypt_fails = 0

    # -- gestion de sesiones ------------------------------------------------

    def _new_session(self, worker: int) -> tuple[cffi.AsyncSession, int, str]:
        profile = random.choice(self.cfg.impersonate_profiles)
        proxy = random.choice(self.cfg.proxies) if self.cfg.proxies else None
        session = cffi.AsyncSession(
            impersonate=profile,
            proxy=proxy,
            timeout=self.cfg.timeout,
            headers={
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        log.debug("worker %d: sesion nueva con perfil %s", worker, profile)
        return session, 0, profile

    async def _session_for(self, worker: int) -> cffi.AsyncSession:
        entry = self._sessions.get(worker)
        if entry is None or entry[1] >= self.cfg.requests_per_session:
            if entry is not None:
                try:
                    await entry[0].close()
                except Exception:
                    pass
            entry = self._new_session(worker)
        session, count, profile = entry
        self._sessions[worker] = (session, count + 1, profile)
        return session

    # -- circuit breaker ----------------------------------------------------

    def _record(self, ok: bool) -> None:
        self._outcomes.append(ok)

    @property
    def challenge_rate(self) -> float:
        if len(self._outcomes) < 20:
            return 0.0
        return 1.0 - (sum(self._outcomes) / len(self._outcomes))

    def pause_all(self, seconds: float, reason: str) -> None:
        """Frena a TODOS los workers, no solo al que fallo.

        Un 429 es una senal global sobre nuestro ritmo agregado; que solo el
        worker afectado espere no resuelve nada.
        """
        until = time.time() + seconds
        if until > self._paused_until:
            self._paused_until = until
            log.warning("pausa global de %.0fs: %s", seconds, reason)

    async def _respect_breaker(self) -> None:
        now = time.time()
        if now < self._paused_until:
            await asyncio.sleep(self._paused_until - now)
            return
        if self.challenge_rate > self.cfg.challenge_rate_threshold:
            async with self._lock:
                if time.time() >= self._paused_until:
                    self.pause_all(
                        self.cfg.breaker_pause,
                        f"tasa de fallos {self.challenge_rate * 100:.1f}% sobre el umbral",
                    )
                    self._outcomes.clear()
            await asyncio.sleep(1.0)

    # -- fetch --------------------------------------------------------------

    async def fetch(
        self,
        url: str,
        *,
        worker: int = 0,
        referer: str | None = None,
        kind: str = "html",
    ) -> FetchResult:
        """GET. Una sola tentativa; el reintento lo maneja el frontier."""
        return await self._request("GET", url, worker=worker, referer=referer, kind=kind)

    async def canary_ok(self, *, worker: int = 0) -> bool:
        """Sauvage por la misma sesion TLS. True = HTML real, no waiting room.

        Distinto de `fragrantica probe`, que abre un Session nuevo. Si el
        canario pasa y la URL del lote no, esa ficha va a cuarentena.
        """
        try:
            await self.fetch(PROBE_URL, worker=worker)
            return True
        except ChallengeDetected:
            return False

    async def post(
        self,
        url: str,
        *,
        data: dict[str, str],
        worker: int = 0,
        referer: str | None = None,
    ) -> FetchResult:
        """POST form-urlencoded (ajax). Misma cortesia y circuit breaker que GET."""
        return await self._request(
            "POST", url, worker=worker, referer=referer, data=data, kind="json",
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        worker: int,
        referer: str | None,
        kind: str,
        data: dict[str, str] | None = None,
    ) -> FetchResult:
        """Una sola tentativa. El reintento lo maneja el frontier, no esta capa.

        Deliberado: si el retry viviera aca, un fallo persistente bloquearia el
        worker. Dejando que el item vuelva al frontier con backoff, el worker
        sigue con el siguiente y el fallido se reintenta despues.
        """
        await self._respect_breaker()
        await asyncio.sleep(random.uniform(self.cfg.delay_min, self.cfg.delay_max))

        session = await self._session_for(worker)
        headers: dict[str, str] = {}
        if referer:
            headers["Referer"] = referer
        if kind == "json":
            headers["Accept"] = "application/json, text/javascript, */*;q=0.1"
            headers["X-Requested-With"] = "XMLHttpRequest"
            headers["Sec-Fetch-Dest"] = "empty"
            headers["Sec-Fetch-Mode"] = "cors"
            headers["Sec-Fetch-Site"] = "same-origin"

        started = time.monotonic()
        try:
            if method == "POST":
                resp = await session.post(
                    url, data=data or {}, headers=headers or None, allow_redirects=True,
                )
            else:
                resp = await session.get(url, headers=headers or None, allow_redirects=True)
        except Exception as exc:
            self._record(False)
            raise FetchError(f"error de red en {url}: {exc}") from exc
        elapsed = time.monotonic() - started

        body = resp.text or ""

        if resp.status_code == 404:
            self._record(True)  # 404 es una respuesta valida, no un bloqueo
            raise NotFound(url)

        if resp.status_code == 429:
            self._record(False)
            retry_after = None
            raw = resp.headers.get("Retry-After")
            if raw:
                try:
                    retry_after = float(raw)
                except ValueError:
                    retry_after = None
            # Pausa global: el 429 habla de nuestro ritmo agregado.
            self.pause_all(retry_after or self.cfg.rate_limit_pause, f"HTTP 429 en {url}")
            raise RateLimited(f"HTTP 429 en {url}", retry_after)

        if resp.status_code in (403, 503) or looks_like_challenge(body, kind=kind):
            self._record(False)
            raise ChallengeDetected(f"HTTP {resp.status_code} / interstitial en {url}")

        if resp.status_code >= 500:
            self._record(True)
            raise FetchError(f"HTTP {resp.status_code} en {url}")

        if resp.status_code != 200:
            self._record(True)
            raise FetchError(f"HTTP inesperado {resp.status_code} en {url}")

        self._record(True)
        return FetchResult(url=url, status=resp.status_code, body=body, elapsed=elapsed)

    async def ensure_passphrase(self, sample_html: str = "", *, worker: int = 0) -> str | None:
        """Passphrase AES = `_pd(hostname)`. Cero GET extra al bundle.

        Si el HTML trae un blob canario y no abre, se corta: el ajax tampoco
        va a cerrar y no vale gastar un POST por perfil.
        """
        from .parsers.crypto import (
            DecryptError,
            decrypt_cryptojs,
            encrypted_blobs_from_html,
            passphrase_from_host,
        )

        async with self._passphrase_lock:
            if self._passphrase:
                return self._passphrase
            if self._passphrase_failed:
                return None

            pw = passphrase_from_host()
            blobs = encrypted_blobs_from_html(sample_html) if sample_html else {}
            sample = (
                blobs.get("memberHomeData")
                or blobs.get("favorite_shelf")
                or next(iter(blobs.values()), None)
            )
            if sample is not None:
                try:
                    import orjson

                    orjson.loads(decrypt_cryptojs(sample, pw))
                except (DecryptError, ValueError) as exc:
                    self._passphrase_failed = True
                    log.warning("passphrase _pd(host) no abre el canario: %s", exc)
                    return None
            self._passphrase = pw
            log.info("passphrase AES derivado de _pd(%s)", "www.fragrantica.com")
            return pw

    def disable_shelves(self, reason: str) -> None:
        """Corta los POST de shelves por el resto del proceso (p.ej. 403)."""
        if not self._shelves_disabled:
            self._shelves_disabled = True
            log.warning("shelves deshabilitados: %s", reason)

    async def close(self) -> None:
        for session, _, _ in self._sessions.values():
            try:
                await session.close()
            except Exception:
                pass
        self._sessions.clear()

    async def __aenter__(self) -> Client:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()


def absolute(path: str) -> str:
    if path.startswith("http"):
        return path
    return f"{BASE_URL}{path if path.startswith('/') else '/' + path}"
