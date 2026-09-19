"""OpenTelemetry para el daemon: metricas + spans cortos + logs.

Sin `OTEL_EXPORTER_OTLP_ENDPOINT` (o con OTEL_SDK_DISABLED=true) todo es
no-op: el SDK esta en las dependencias, pero no se inicializa. El crawl
no cambia.
"""

from __future__ import annotations

import logging
import os
import warnings
from contextlib import contextmanager, nullcontext
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from .frontier import Frontier
    from .pipeline.daemon import DaemonState

log = logging.getLogger(__name__)

_SERVICE = "fragrantica-scraper"
_ENABLED = False

_http_requests: Any = None
_http_failures: Any = None
_http_duration: Any = None
_records_written: Any = None
_daemon_blocks: Any = None
_cooldowns: Any = None
_cooldown_duration: Any = None
_tracer: Any = None
_log_handler: logging.Handler | None = None
_logger_provider: Any = None

_snapshot: dict[str, Any] = {
    "frontier": {},
    "shelves": {},
    "phase": 0,
    "cooldown_remaining": 0.0,
    "via": "home",
    "shelves_via": "home",
}


def otel_enabled() -> bool:
    return _ENABLED


def egress_via(cfg: Any | None = None, *, shelves: bool = False) -> str:
    """`home` / `proxy` / `shelves_proxy`. Nunca la URL: puede traer credenciales."""
    if cfg is None:
        from .config import CRAWL

        cfg = CRAWL
    if shelves and getattr(cfg, "shelves_proxies", ()):
        return "shelves_proxy"
    if getattr(cfg, "proxies", ()):
        return "proxy"
    return "home"


def kind_from_url(url: str, *, method: str = "GET") -> str:
    """Clasifica el request para las metricas. Sin usernames ni query."""
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
    """(outcome, status_label) para las metricas.

    El interstitial es del cuerpo, no un codigo: un 200 con 'Just a moment'
    no es un OK. Gana sobre el status. 403/503 sin marcadores de waiting
    room quedan como codigo, no se mezclan con el challenge.
    """
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


def setup_otel(*, force: bool = False) -> bool:
    """Inicializa OTLP. False = no-op (sin endpoint, o disabled)."""
    global _ENABLED, _http_requests, _http_failures, _http_duration, _records_written
    global _daemon_blocks, _cooldowns, _cooldown_duration, _tracer

    if _ENABLED:
        return True
    if os.environ.get("OTEL_SDK_DISABLED", "").strip().lower() in {"1", "true", "yes"}:
        return False
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint and not force:
        return False

    try:
        from opentelemetry import metrics, trace
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        log.info("OTel: SDK no importable; metricas desactivadas")
        return False

    service = os.environ.get("OTEL_SERVICE_NAME", _SERVICE).strip() or _SERVICE
    resource = Resource.create({"service.name": service})

    try:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
    except ImportError:
        log.info("OTel: exporter OTLP no instalado; metricas desactivadas")
        return False

    metric_kwargs: dict[str, Any] = {}
    trace_kwargs: dict[str, Any] = {}
    if endpoint:
        metric_kwargs["endpoint"] = _join_otlp(endpoint, "v1/metrics")
        trace_kwargs["endpoint"] = _join_otlp(endpoint, "v1/traces")

    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(**metric_kwargs),
        export_interval_millis=10_000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)
    meter = metrics.get_meter(_SERVICE)

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(**trace_kwargs)))
    trace.set_tracer_provider(tracer_provider)
    _tracer = trace.get_tracer(_SERVICE)

    _http_requests = meter.create_counter(
        "fragrantica.http.requests",
        description="Requests HTTP del crawl (GET/POST/probe)",
        unit="{request}",
    )
    _http_failures = meter.create_counter(
        "fragrantica.http.failures",
        description="Fallos HTTP por status code (429, 403, interstitial, …)",
        unit="{request}",
    )
    _http_duration = meter.create_histogram(
        "fragrantica.http.duration",
        description="Duracion del round-trip HTTP, sin el jitter de cortesia",
        unit="s",
    )
    _records_written = meter.create_counter(
        "fragrantica.records.written",
        description="Filas escritas a staging",
        unit="{row}",
    )
    _daemon_blocks = meter.create_counter(
        "fragrantica.daemon.blocks",
        description="StopCrawl del daemon (429 o interstitial)",
        unit="{event}",
    )
    _cooldowns = meter.create_counter(
        "fragrantica.daemon.cooldowns",
        description="Esperas de cooldown iniciadas (pagina o shelves)",
        unit="{event}",
    )
    _cooldown_duration = meter.create_histogram(
        "fragrantica.daemon.cooldown.duration",
        description="Duracion de cada cooldown (la espera, no el probe)",
        unit="s",
        explicit_bucket_boundaries_advisory=[
            300.0, 600.0, 900.0, 1800.0, 3600.0, 7200.0, 10800.0, 21600.0,
        ],
    )
    meter.create_observable_gauge(
        "fragrantica.frontier.size",
        callbacks=[_observe_frontier],
        description="Filas del frontier por kind y status",
        unit="{url}",
    )
    meter.create_observable_gauge(
        "fragrantica.shelves.size",
        callbacks=[_observe_shelves],
        description="Jobs de wardrobe por status",
        unit="{job}",
    )
    meter.create_observable_gauge(
        "fragrantica.daemon.cooldown_remaining",
        callbacks=[_observe_cooldown],
        description="Segundos de cooldown restantes (0 si esta crawleando)",
        unit="s",
    )
    meter.create_observable_gauge(
        "fragrantica.daemon.phase",
        callbacks=[_observe_phase],
        description="Fase activa del daemon (1 marcas, 2 perfume, 3 perfiles)",
        unit="{phase}",
    )

    _refresh_via(None)
    _install_log_pipeline(resource, endpoint)

    _ENABLED = True
    log.info("OTel activo -> %s (service.name=%s)", endpoint or "(default)", service)
    return True


def _join_otlp(endpoint: str, path: str) -> str:
    base = endpoint.rstrip("/")
    if base.endswith("/v1/metrics") or base.endswith("/v1/traces") or base.endswith("/v1/logs"):
        return base
    return f"{base}/{path}"


def _install_log_pipeline(resource: Any, endpoint: str) -> None:
    """Reenvia logging.info/warning/error del paquete fragrantica a OTLP."""
    global _log_handler, _logger_provider
    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.sdk._logs import LoggerProvider
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    except ImportError:
        log.info("OTel: exporter de logs no disponible; solo metricas/traces")
        return

    log_kwargs: dict[str, Any] = {}
    if endpoint:
        log_kwargs["endpoint"] = _join_otlp(endpoint, "v1/logs")
    provider = LoggerProvider(resource=resource)
    provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(**log_kwargs))
    )
    set_logger_provider(provider)
    _logger_provider = provider
    _log_handler = install_log_handler(provider)


def install_log_handler(logger_provider: Any) -> logging.Handler:
    """Puente logging -> OTel. Solo `fragrantica.*`; la consola sigue con Rich."""
    from opentelemetry.sdk._logs import LoggingHandler

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger("fragrantica").addHandler(handler)
    return handler


def attach_snapshot(
    *,
    frontier: Frontier | None = None,
    state: DaemonState | None = None,
    phase: int | None = None,
    cooldown_remaining: float | None = None,
    cfg: Any = None,
) -> None:
    """Actualiza gauges desde el hilo del crawl (no desde el exporter)."""
    _refresh_via(cfg)
    if frontier is not None:
        _snapshot["frontier"] = {
            f"{kind}:{status}": n for (kind, status), n in frontier.stats().items()
        }
        _snapshot["shelves"] = dict(frontier.shelves_stats())
    if phase is not None:
        _snapshot["phase"] = int(phase)
    if cooldown_remaining is not None:
        _snapshot["cooldown_remaining"] = float(max(0.0, cooldown_remaining))
    elif state is not None:
        from .config import CRAWL
        from .pipeline.daemon import remaining_wait

        _snapshot["cooldown_remaining"] = remaining_wait(
            state.last_block_at,
            state.last_reason,
            state.consecutive_blocks,
            cfg=cfg or CRAWL,
        )


def _refresh_via(cfg: Any) -> None:
    from .config import CRAWL

    crawl = cfg or CRAWL
    _snapshot["via"] = egress_via(crawl)
    _snapshot["shelves_via"] = egress_via(crawl, shelves=True)


def _phase_label() -> str:
    return str(int(_snapshot.get("phase") or 0))


def _via_label(kind: str) -> str:
    if kind == "shelves":
        return str(_snapshot.get("shelves_via") or "home")
    return str(_snapshot.get("via") or "home")


_OK_OUTCOMES = frozenset({"200", "ok", "already_have", "skip"})


def _failure_status_code(outcome: str, status: str) -> str | None:
    """Etiqueta para Maple: el codigo, o `interstitial` si el cuerpo era challenge."""
    if outcome in _OK_OUTCOMES:
        return None
    if outcome == "interstitial":
        return "interstitial"
    if status not in {"", "none"}:
        return status
    return outcome or "error"


def record_http(
    kind: str,
    outcome: str,
    duration_s: float,
    *,
    status: str | int | None = None,
) -> None:
    status_label = str(status) if status is not None else "none"
    attrs = {
        "kind": kind,
        "outcome": outcome,
        "status": status_label,
        "phase": _phase_label(),
        "via": _via_label(kind),
    }
    if _http_requests is not None:
        _http_requests.add(1, attrs)
    if _http_duration is not None and duration_s >= 0:
        _http_duration.record(duration_s, {"kind": kind})
    code = _failure_status_code(outcome, status_label)
    if code is not None and _http_failures is not None:
        _http_failures.add(
            1,
            {
                "status_code": code,
                "kind": kind,
                "phase": attrs["phase"],
                "via": attrs["via"],
            },
        )


def record_records(table: str, n: int) -> None:
    if n <= 0 or _records_written is None:
        return
    _records_written.add(n, {"table": _table_name(table)})


def record_block(reason: str) -> None:
    if _daemon_blocks is not None:
        _daemon_blocks.add(1, {"reason": reason})


def record_cooldown(
    *,
    reason: str,
    duration_s: float,
    phase: int | str,
    via: str,
    kind: str = "page",
) -> None:
    """Una espera (pagina o shelves). Count + histograma de duracion."""
    attrs = {
        "reason": reason,
        "phase": str(int(phase)),
        "via": via,
        "kind": kind,
    }
    if _cooldowns is not None:
        _cooldowns.add(1, attrs)
    if _cooldown_duration is not None and duration_s >= 0:
        _cooldown_duration.record(float(duration_s), attrs)


def record_runner_outcome(outcome: str, kind: str) -> None:
    """AlreadyHave / SkipItem / 404 del runner (no siempre hay HTTP)."""
    record_http(kind, outcome, -1.0)


def _table_name(writer: str) -> str:
    if writer.startswith("interactions"):
        return "interactions"
    if writer == "item_frontier":
        return "item_frontier"
    return writer


@contextmanager
def start_span(name: str, **attrs: Any) -> Iterator[Any]:
    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name) as span:
        for key, value in attrs.items():
            if value is None:
                continue
            span.set_attribute(key, value)
        yield span


def http_span(kind: str, method: str):
    if _tracer is None:
        return nullcontext(None)
    return start_span("http.fetch", **{"fragrantica.kind": kind, "http.method": method})


def _obs(value: float, **attrs: str) -> Any:
    from opentelemetry.metrics import Observation

    return Observation(value, attrs)


def _observe_frontier(_options: Any) -> list[Any]:
    out = []
    for key, n in _snapshot.get("frontier", {}).items():
        kind, _, status = str(key).partition(":")
        out.append(_obs(float(n), kind=kind, status=status))
    return out


def _observe_shelves(_options: Any) -> list[Any]:
    return [
        _obs(float(n), status=str(status))
        for status, n in _snapshot.get("shelves", {}).items()
    ]


def _observe_cooldown(_options: Any) -> list[Any]:
    return [_obs(float(_snapshot.get("cooldown_remaining") or 0.0))]


def _observe_phase(_options: Any) -> list[Any]:
    return [_obs(float(_snapshot.get("phase") or 0))]


def reset_for_tests() -> None:
    """Solo tests: vuelve al no-op y limpia el snapshot."""
    global _ENABLED, _http_requests, _http_failures, _http_duration, _records_written
    global _daemon_blocks, _cooldowns, _cooldown_duration, _tracer, _log_handler
    global _logger_provider
    if _log_handler is not None:
        logging.getLogger("fragrantica").removeHandler(_log_handler)
        _log_handler = None
    if _logger_provider is not None:
        try:
            _logger_provider.shutdown()
        except Exception:
            pass
        _logger_provider = None
    _ENABLED = False
    _http_requests = None
    _http_failures = None
    _http_duration = None
    _records_written = None
    _daemon_blocks = None
    _cooldowns = None
    _cooldown_duration = None
    _tracer = None
    _snapshot.update(
        {
            "frontier": {},
            "shelves": {},
            "phase": 0,
            "cooldown_remaining": 0.0,
            "via": "home",
            "shelves_via": "home",
        }
    )


def bind_test_instruments(
    *,
    requests: Any = None,
    failures: Any = None,
    duration: Any = None,
    records: Any = None,
    blocks: Any = None,
    cooldowns: Any = None,
    cooldown_duration: Any = None,
) -> None:
    """Inyecta counters fake para tests, sin el SDK."""
    global _http_requests, _http_failures, _http_duration, _records_written
    global _daemon_blocks, _cooldowns, _cooldown_duration, _ENABLED
    _http_requests = requests
    _http_failures = failures
    _http_duration = duration
    _records_written = records
    _daemon_blocks = blocks
    _cooldowns = cooldowns
    _cooldown_duration = cooldown_duration
    _ENABLED = True
