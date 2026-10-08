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
import re
import time
from collections import deque
from dataclasses import dataclass
from urllib.parse import urlparse

from curl_cffi import requests as cffi

from .config import BASE_URL, CRAWL, CrawlConfig

PROBE_URL = f"{BASE_URL}/perfume/Dior/Sauvage-31861.html"
# Sesion aparte del GET: sale por FRAGRANTICA_SHELVES_PROXY si esta definido.
SHELVES_WORKER = -1

log = logging.getLogger(__name__)


class ChallengeDetected(Exception):
    """Cloudflare devolvio un interstitial en vez de contenido."""


class RateLimited(Exception):
    """HTTP 429: el sitio nos esta pidiendo explicitamente que bajemos el ritmo.

    Se distingue del challenge a proposito. Un 403/interstitial puede ser solo
    esa URL (el canario lo distingue); un 429 es el cupo de esa IP. Con un
    pool de puertos se enfria ese puerto y se sigue por otro. La pausa global
    queda para cuando no queda ninguno libre, o cuando no hay proxy.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class FetchError(Exception):
    """Fallo transitorio: vale reintentar."""


class NotFound(Exception):
    """404 real: no vale reintentar."""


# user:pass@ en un mensaje de curl no puede llegar al log ni al frontier.
_PROXY_USERINFO = re.compile(r"://[^\s/@]+:[^\s/@]+@")


def proxy_label(proxy: str) -> str:
    """host:port, sin userinfo."""
    parsed = urlparse(proxy)
    host = parsed.hostname or "proxy"
    if parsed.port:
        return f"{host}:{parsed.port}"
    return host


def _redact(text: str) -> str:
    return _PROXY_USERINFO.sub("://", text)


def _retry_after(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


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


@dataclass
class _LiveSession:
    session: cffi.AsyncSession
    count: int
    profile: str
    proxy: str | None


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
    from .observability import classify_http, http_span, record_http

    proxy = random.choice(cfg.proxies) if cfg.proxies else None
    started = time.monotonic()
    with http_span("probe", "GET"):
        resp = cffi.Session(impersonate="chrome", proxy=proxy).get(PROBE_URL, timeout=30)
    elapsed = time.monotonic() - started
    body = resp.text or ""
    nbytes = len(body)
    if resp.status_code == 429:
        outcome, status = classify_http(429)
        record_http("probe", outcome, elapsed, status=status)
        return ProbeResult(resp.status_code, nbytes, False, "429")
    interstitial = looks_like_challenge(body)
    if resp.status_code in (403, 503) or interstitial:
        outcome, status = classify_http(resp.status_code, interstitial=interstitial)
        record_http("probe", outcome, elapsed, status=status)
        return ProbeResult(resp.status_code, nbytes, False, "challenge")
    if resp.status_code == 200 and nbytes > 100_000:
        outcome, status = classify_http(200)
        record_http("probe", outcome, elapsed, status=status)
        return ProbeResult(resp.status_code, nbytes, True, None)
    outcome, status = classify_http(resp.status_code)
    record_http("probe", "error", elapsed, status=status)
    return ProbeResult(resp.status_code, nbytes, False, "other")


class Client:
    """Pool de sesiones con rotacion de fingerprint y cortesia incorporada."""

    def __init__(self, cfg: CrawlConfig = CRAWL) -> None:
        self.cfg = cfg
        self._sessions: dict[int, _LiveSession] = {}
        # Puerto sticky por worker. Se enfria el que falla; no se rota en sano.
        self._pin: dict[int, str] = {}
        self._cooled: dict[str, dict[str, float]] = {"page": {}, "shelves": {}}
        self._block_reason: dict[str, str] = {}
        self._outcomes: deque[bool] = deque(maxlen=cfg.challenge_window)
        self._paused_until = 0.0
        self._lock = asyncio.Lock()
        self._passphrase_lock = asyncio.Lock()
        # Passphrase AES = _pd(host). None = todavia no se calculo;
        # _passphrase_failed evita reintentar si el canario no abre.
        self._passphrase: str | None = None
        self._passphrase_failed = False
        self._shelves_disabled = False
        self._shelves_paused_until = 0.0
        self._shelves_decrypt_fails = 0
        # Sin proxy de shelves, GET y POST no se solapan: es la misma IP.
        self._serial_io = asyncio.Lock()

    # -- gestion de sesiones ------------------------------------------------

    def _pool_for(self, worker: int) -> tuple[str, tuple[str, ...]]:
        if worker == SHELVES_WORKER and self.cfg.shelves_proxies:
            return "shelves", self.cfg.shelves_proxies
        return "page", self.cfg.proxies

    def _pin_worker(self, worker: int) -> int:
        # Sin proxy propio, el POST de wardrobe sale por la misma IP que el GET.
        # Un pin distinto abriria un segundo puerto y duplicaria el cupo.
        if worker == SHELVES_WORKER and not self.cfg.shelves_proxies:
            return 0
        return worker

    def _healthy(self, pool_name: str, pool: tuple[str, ...]) -> list[str]:
        now = time.time()
        cooled = self._cooled[pool_name]
        fresh = [p for p in pool if cooled.get(p, 0) <= now]
        # Los que nunca fallaron (0) van primero; despues el que lleva mas
        # tiempo libre. El orden del config desempata, asi el pin es estable.
        fresh.sort(key=lambda p: (cooled.get(p, 0), pool.index(p)))
        return fresh

    def _proxy_for(self, worker: int) -> str | None:
        """Puerto sticky. Solo cambia cuando el actual esta en cooldown."""
        pool_name, pool = self._pool_for(worker)
        if not pool:
            return None
        pin_worker = self._pin_worker(worker)
        current = self._pin.get(pin_worker)
        now = time.time()
        if current in pool and self._cooled[pool_name].get(current, 0) <= now:
            return current
        healthy = self._healthy(pool_name, pool)
        if not healthy:
            raise self._exhausted(pool_name)
        pick = healthy[0]
        self._pin[pin_worker] = pick
        return pick

    def _exhausted(self, pool_name: str) -> Exception:
        """Ningun puerto libre. No caer a la IP de casa: tambien se quema."""
        reason = self._block_reason.get(pool_name, "429")
        which = "wardrobe" if pool_name == "shelves" else "paginas"
        msg = f"todos los puertos del proxy de {which} en cooldown ({reason})"
        if reason == "challenge":
            return ChallengeDetected(msg)
        return RateLimited(msg)

    def _current_proxy(self, worker: int) -> str | None:
        live = self._sessions.get(worker)
        if live is not None and live.proxy:
            return live.proxy
        return self._pin.get(self._pin_worker(worker))

    async def _drop_proxy(self, proxy: str) -> None:
        for worker, live in list(self._sessions.items()):
            if live.proxy != proxy:
                continue
            try:
                await live.session.close()
            except Exception:
                pass
            del self._sessions[worker]
        for worker, pinned in list(self._pin.items()):
            if pinned == proxy:
                del self._pin[worker]

    async def retire_egress(
        self,
        worker: int,
        reason: str,
        *,
        seconds: float | None = None,
    ) -> bool:
        """Enfria el puerto actual. True si queda otro libre para seguir.

        `reason` es `429`, `challenge` o `network`. Un solo puerto (o salida
        directa) no rota: ahi manda la pausa del daemon. `seconds` pisa el
        cooldown cuando el sitio manda un Retry-After mas largo.
        """
        pool_name, pool = self._pool_for(worker)
        if len(pool) < 2:
            return False
        current = self._current_proxy(worker)
        if not current or current not in pool:
            return False
        if seconds is None:
            seconds = (
                self.cfg.cooldown_challenge
                if reason == "challenge"
                else self.cfg.cooldown_429
            )
        self._cooled[pool_name][current] = time.time() + seconds
        self._block_reason[pool_name] = reason
        await self._drop_proxy(current)
        healthy = self._healthy(pool_name, pool)
        log.warning(
            "proxy %s en cooldown %.0fs (%s); %d/%d puertos libres",
            proxy_label(current),
            seconds,
            reason,
            len(healthy),
            len(pool),
        )
        return bool(healthy)

    def _new_session(self, worker: int) -> _LiveSession:
        profile = random.choice(self.cfg.impersonate_profiles)
        proxy = self._proxy_for(worker)
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
        via = f" via {proxy_label(proxy)}" if proxy else ""
        log.debug("worker %d: sesion nueva con perfil %s%s", worker, profile, via)
        return _LiveSession(session=session, count=0, profile=profile, proxy=proxy)

    async def _session_for(self, worker: int) -> cffi.AsyncSession:
        # El perfil TLS rota cada N requests. El puerto no: cambiar de IP con
        # el cupo sano dispara interstitial en una IP recien usada.
        entry = self._sessions.get(worker)
        if entry is None or entry.count >= self.cfg.requests_per_session:
            if entry is not None:
                try:
                    await entry.session.close()
                except Exception:
                    pass
            entry = self._new_session(worker)
        entry.count += 1
        self._sessions[worker] = entry
        return entry.session

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

    async def _respect_breaker(self, *, worker: int = 0) -> None:
        now = time.time()
        # El POST de wardrobe por FRAGRANTICA_SHELVES_PROXY no comparte IP
        # con el GET. Un 429 de pagina (pause_all) no tiene que dormir esos
        # POST: la barra quedaba "sin pausa" y el done no avanzaba.
        shelves_on_own_ip = worker == SHELVES_WORKER and bool(self.cfg.shelves_proxies)
        if not shelves_on_own_ip and now < self._paused_until:
            await asyncio.sleep(self._paused_until - now)
            return
        if shelves_on_own_ip:
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
        rotate: bool = True,
    ) -> FetchResult:
        """GET. El reintento de la URL lo maneja el frontier.

        Si este puerto responde 429 o se cae la conexion y hay otro, se enfria
        y el mismo GET sigue por ahi. Un interstitial sube tal cual: el canario
        tiene que correr en esta sesion, no en una IP nueva. `rotate=False` es
        ese canario: un 429 ahi no puede saltar de puerto y dar un falso OK.
        """
        return await self._request(
            "GET", url, worker=worker, referer=referer, kind=kind, rotate=rotate,
        )

    async def canary_ok(self, *, worker: int = 0) -> bool:
        """Sauvage por la misma sesion TLS. True = HTML real, no waiting room.

        Distinto de `fragrantica probe`, que abre un Session nuevo. Si el
        canario pasa y la URL del lote no, esa ficha va a cuarentena.
        """
        try:
            await self.fetch(PROBE_URL, worker=worker, rotate=False)
            return True
        except ChallengeDetected:
            return False

    async def post(
        self,
        url: str,
        *,
        data: dict[str, str],
        worker: int = SHELVES_WORKER,
        referer: str | None = None,
    ) -> FetchResult:
        """POST form-urlencoded (ajax). Sale por SHELVES_WORKER / proxy de shelves."""
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
        rotate: bool = True,
    ) -> FetchResult:
        if self.cfg.shelves_proxies:
            return await self._request_unlocked(
                method, url, worker=worker, referer=referer, kind=kind, data=data,
                rotate=rotate,
            )
        async with self._serial_io:
            return await self._request_unlocked(
                method, url, worker=worker, referer=referer, kind=kind, data=data,
                rotate=rotate,
            )

    async def _request_unlocked(
        self,
        method: str,
        url: str,
        *,
        worker: int,
        referer: str | None,
        kind: str,
        data: dict[str, str] | None = None,
        rotate: bool = True,
    ) -> FetchResult:
        """Una tentativa por puerto. La URL fallida la reintenta el frontier.

        429 y error de red son de este puerto: se enfria y se repite el mismo
        request en el siguiente, con el jitter de siempre. El interstitial no
        rota aca. Puede ser solo esta ficha, y el canario tiene que ver la
        misma sesion TLS. Recien si el canario falla, el runner enfria el puerto.
        """
        from .observability import classify_http, http_span, kind_from_url, record_http

        _, pool = self._pool_for(worker)
        # Un intento por puerto. Si el ultimo tambien falla, retire devuelve
        # False y la excepcion sale antes de agotar el for.
        budget = max(1, len(pool))
        headers: dict[str, str] = {}
        if referer:
            headers["Referer"] = referer
        if kind == "json":
            headers["Accept"] = "application/json, text/javascript, */*;q=0.1"
            headers["X-Requested-With"] = "XMLHttpRequest"
            headers["Sec-Fetch-Dest"] = "empty"
            headers["Sec-Fetch-Mode"] = "cors"
            headers["Sec-Fetch-Site"] = "same-origin"

        metric_kind = kind_from_url(url, method=method)

        for _ in range(budget):
            await self._respect_breaker(worker=worker)
            await asyncio.sleep(random.uniform(self.cfg.delay_min, self.cfg.delay_max))
            try:
                session = await self._session_for(worker)
            except (RateLimited, ChallengeDetected):
                raise

            started = time.monotonic()
            with http_span(metric_kind, method):
                try:
                    if method == "POST":
                        resp = await session.post(
                            url, data=data or {}, headers=headers or None, allow_redirects=True,
                        )
                    else:
                        resp = await session.get(
                            url, headers=headers or None, allow_redirects=True,
                        )
                except Exception as exc:
                    outcome, status = classify_http(0, network_error=True)
                    record_http(
                        metric_kind, outcome, time.monotonic() - started, status=status,
                    )
                    switched = (
                        rotate
                        and self._can_rotate_network(worker)
                        and await self.retire_egress(worker, "network")
                    )
                    if switched:
                        continue
                    self._record(False)
                    detail = _redact(str(exc))
                    # Con pool, un corte en todos los puertos no es culpa de la
                    # URL: RateLimited no le suma intentos en el frontier.
                    if rotate and len(pool) >= 2:
                        raise RateLimited(
                            f"todos los puertos del proxy fallaron al conectar: {detail}"
                        ) from None
                    raise FetchError(f"error de red en {url}: {detail}") from None

                elapsed = time.monotonic() - started
                body = resp.text or ""

                if resp.status_code == 404:
                    self._record(True)  # 404 es una respuesta valida, no un bloqueo
                    outcome, status = classify_http(404)
                    record_http(metric_kind, outcome, elapsed, status=status)
                    raise NotFound(url)

                if resp.status_code == 429:
                    outcome, status = classify_http(429)
                    record_http(metric_kind, outcome, elapsed, status=status)
                    retry_after = _retry_after(resp.headers.get("Retry-After"))
                    switched = (
                        rotate
                        and self._can_rotate_429(worker, kind)
                        and await self.retire_egress(
                            worker,
                            "429",
                            seconds=max(self.cfg.cooldown_429, retry_after or 0),
                        )
                    )
                    if switched:
                        # El breaker no cuenta este 429: es la IP vieja, no la nueva.
                        continue
                    self._record(False)
                    # pause_all es para 429 de pagina (ritmo de IP). En ajax el
                    # cupo es del endpoint: frenar el HTML 5 min recreaba el 70/19.
                    if kind != "json":
                        self.pause_all(
                            retry_after or self.cfg.rate_limit_pause,
                            f"HTTP 429 en {url}",
                        )
                    raise RateLimited(f"HTTP 429 en {url}", retry_after)

                interstitial = looks_like_challenge(body, kind=kind)
                if resp.status_code in (403, 503) or interstitial:
                    self._record(False)
                    outcome, status = classify_http(
                        resp.status_code, interstitial=interstitial
                    )
                    record_http(metric_kind, outcome, elapsed, status=status)
                    raise ChallengeDetected(
                        f"HTTP {resp.status_code} / interstitial en {url}"
                    )

                if resp.status_code >= 500:
                    # 5xx del origen: rotar de IP multiplica la carga y no
                    # cambia la respuesta. 503 ya cayo en el branch de challenge.
                    self._record(True)
                    outcome, status = classify_http(resp.status_code)
                    record_http(metric_kind, outcome, elapsed, status=status)
                    raise FetchError(f"HTTP {resp.status_code} en {url}")

                if resp.status_code != 200:
                    self._record(True)
                    outcome, status = classify_http(resp.status_code)
                    record_http(metric_kind, outcome, elapsed, status=status)
                    raise FetchError(f"HTTP inesperado {resp.status_code} en {url}")

                self._record(True)
                outcome, status = classify_http(200)
                record_http(metric_kind, outcome, elapsed, status=status)
                return FetchResult(
                    url=url, status=resp.status_code, body=body, elapsed=elapsed,
                )

        raise RateLimited(f"HTTP 429 en {url}")

    def _can_rotate_429(self, worker: int, kind: str) -> bool:
        """El 429 de ajax en la IP del HTML no quema ese puerto.

        Medido: el cupo de `/user_shelves` no es el de las paginas. Rotarlo
        tiraria una IP que todavia sirve para perfiles.
        """
        if kind == "json" and worker == SHELVES_WORKER and not self.cfg.shelves_proxies:
            return False
        return len(self._pool_for(worker)[1]) >= 2

    def _can_rotate_network(self, worker: int) -> bool:
        return len(self._pool_for(worker)[1]) >= 2

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

    def pause_shelves(self, reason: str, *, now: float | None = None) -> None:
        """Pausa temporal de los POST tras un 429 de ajax.

        El HTML del perfil sigue: ahi vive el member_id. Reanudar ajax a
        los 15 min (cooldown del daemon) pedía ~19 perfiles con la ventana
        llena y volvia a 429.
        """
        t = now if now is not None else time.time()
        until = t + self.cfg.shelves_cooldown
        if until > self._shelves_paused_until:
            self._shelves_paused_until = until
            log.warning(
                "shelves en pausa %.0f min: %s",
                self.cfg.shelves_cooldown / 60,
                reason,
            )
            from .observability import egress_via, record_cooldown

            record_cooldown(
                reason="429",
                duration_s=self.cfg.shelves_cooldown,
                phase=3,
                via=egress_via(self.cfg, shelves=True),
                kind="shelves",
            )

    def shelves_paused(self, *, now: float | None = None) -> bool:
        t = now if now is not None else time.time()
        return t < self._shelves_paused_until

    def shelves_pause_remaining(self, *, now: float | None = None) -> float:
        t = now if now is not None else time.time()
        return max(0.0, self._shelves_paused_until - t)

    def should_fetch_shelves(self, *, now: float | None = None) -> bool:
        """False si fetch_shelves esta apagado, 403 permanente, o pausa 429."""
        if not self.cfg.fetch_shelves or self._shelves_disabled:
            return False
        t = now if now is not None else time.time()
        if t < self._shelves_paused_until:
            return False
        if self._shelves_paused_until > 0:
            log.info("shelves reanudados: vencio la pausa de ajax 429")
            self._shelves_paused_until = 0.0
        return True

    async def close(self) -> None:
        for live in self._sessions.values():
            try:
                await live.session.close()
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
