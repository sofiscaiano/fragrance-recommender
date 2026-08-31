"""Configuracion central del scraper."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_URL = "https://www.fragrantica.com"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("FRAGRANTICA_DATA_DIR", PROJECT_ROOT / "data"))


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


def _env_csv(name: str) -> tuple[str, ...]:
    return tuple(
        p.strip() for p in os.environ.get(name, "").split(",") if p.strip()
    )


@dataclass(frozen=True)
class CrawlConfig:
    """Parametros de red y de cortesia.

    Los defaults son deliberadamente conservadores: el objetivo es no degradar
    el servicio del sitio, no maximizar throughput.
    """

    # Un solo worker. El 429 es ritmo AGREGADO: 6 en paralelo (~5 req/s)
    # lo dispararon a los ~150 requests. Subir concurrency duplica conexiones
    # TLS desde la misma IP; bajar el delay de un worker no.
    concurrency: int = 1

    # Jitter uniforme por worker. Un delay fijo es en si mismo una firma de bot,
    # mas detectable que ir un poco mas rapido de forma irregular.
    delay_min: float = field(default_factory=lambda: _env_float("FRAGRANTICA_DELAY_MIN", 5))
    delay_max: float = field(default_factory=lambda: _env_float("FRAGRANTICA_DELAY_MAX", 10))

    timeout: float = 45.0
    max_attempts: int = 6
    backoff_base: float = 15.0
    backoff_cap: float = 900.0

    # Pausa global cuando el sitio responde 429. Es una senal explicita sobre
    # nuestro ritmo agregado, asi que frena a todos los workers.
    rate_limit_pause: float = 300.0
    breaker_pause: float = 180.0

    # Tras un interstitial, un canario (Sauvage) en la MISMA sesion. Si el
    # canario pasa, esta URL va a `deferred` y el lote sigue. Si el canario
    # tambien falla, es la IP: StopCrawl. 12 h para reintentar la cuarentena.
    quarantine_seconds: float = field(
        default_factory=lambda: _env_float("FRAGRANTICA_QUARANTINE", 43200.0)
    )

    # Perfiles de impersonacion TLS de curl_cffi. Se rotan por sesion, no por
    # request: cambiar de fingerprint dentro de una misma sesion con cookies
    # persistentes seria incoherente y mas sospechoso que no rotar.
    impersonate_profiles: tuple[str, ...] = (
        "chrome",
        "chrome131",
        "firefox133",
        "safari18_0",
    )
    requests_per_session: int = 40

    # El daemon no pega contra el interstitial: espera, un probe, y reanuda.
    # 429 pide menos espera que un challenge de IP; ambos crecen en
    # exponencial hasta cooldown_cap (el martilleo corto es lo que escala a 403).
    cooldown_429: float = field(default_factory=lambda: _env_float("FRAGRANTICA_COOLDOWN_429", 900.0))
    cooldown_challenge: float = field(
        default_factory=lambda: _env_float("FRAGRANTICA_COOLDOWN_CHALLENGE", 1800.0)
    )
    cooldown_cap: float = field(default_factory=lambda: _env_float("FRAGRANTICA_COOLDOWN_CAP", 21600.0))

    # Capa 3 del plan: una IP nueva (hotspot o residencial) cuando Cloudflare
    # penalizo la nuestra. Vacio = salir directo. Varias URLs separadas por coma.
    proxies: tuple[str, ...] = field(default_factory=lambda: _env_csv("FRAGRANTICA_PROXY"))

    # Solo el POST de wardrobe. Independiente de FRAGRANTICA_PROXY: si HTML
    # y ajax salen por la misma IP, el 70/19 se muda al residencial.
    # Vacio = el POST usa la misma salida que el GET (casa o FRAGRANTICA_PROXY).
    shelves_proxies: tuple[str, ...] = field(
        default_factory=lambda: _env_csv("FRAGRANTICA_SHELVES_PROXY")
    )

    # Si la tasa de challenges supera este umbral, el circuit breaker frena.
    challenge_rate_threshold: float = 0.05
    challenge_window: int = 100

    lease_timeout_seconds: int = 900

    # Un POST extra por perfil a `/ajax.php?user_shelves` (robots.txt lo
    # prohibe; decision explicita de incluir wardrobe y votos sin review).
    # Si el descifrado falla, la fase 3 sigue con las reviews del HTML.
    fetch_shelves: bool = True

    # Pausa de los POST (no del HTML) tras un 429 en user_shelves. Una noche
    # de fase 3 midio bursts exactos de 70 y 19 perfiles: 15 min no vacian
    # la ventana de Cloudflare y el burst corto pide con el cupo caliente.
    # 45 min deja caer el burst de 70; el HTML sigue recolectando member_id.
    shelves_cooldown: float = field(
        default_factory=lambda: _env_float("FRAGRANTICA_SHELVES_COOLDOWN", 2700.0)
    )


@dataclass(frozen=True)
class DatasetConfig:
    """Umbrales de filtrado.

    Separacion deliberada entre porton de crawl y filtro de dataset: filtrar de
    mas durante el crawl es irreversible (habria que volver a la red), mientras
    que filtrar al exportar es gratis y reproducible.
    """

    # Porton de crawl: permisivo. Solo descarta lo que con certeza no sirve.
    crawl_min_item_reviews: int = 1

    # Filtro de dataset: estricto. k-core iterativo hasta punto fijo.
    k_core: int = 5

    # Cortes adicionales para el reporte de sensibilidad al umbral.
    sensitivity_k_values: tuple[int, ...] = (3, 5, 10)

    # Salt para hashear usernames en el export publico.
    username_salt: str = field(
        default_factory=lambda: os.environ.get("FRAGRANTICA_SALT", "cambiar-en-produccion")
    )


# Cantidad de reviews que el sitio renderiza para un visitante anonimo. Si una
# pagina trae este numero, asumimos que esta truncada y el resto del archivo
# queda detras del login (verificado en el reconocimiento).
REVIEW_PAGE_CAP = 200

CRAWL = CrawlConfig()
DATASET = DatasetConfig()
