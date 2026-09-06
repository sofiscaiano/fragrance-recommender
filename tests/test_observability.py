"""OTel es opt-in: sin endpoint ni extra, el crawl no cambia."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from fragrantica.frontier import Frontier
from fragrantica.config import CrawlConfig
from fragrantica.observability import (
    attach_snapshot,
    bind_test_instruments,
    classify_http,
    egress_via,
    install_log_handler,
    kind_from_url,
    otel_enabled,
    record_block,
    record_cooldown,
    record_http,
    record_records,
    record_runner_outcome,
    reset_for_tests,
    setup_otel,
)
from fragrantica.pipeline.daemon import next_phase


@pytest.fixture(autouse=True)
def _reset_otel() -> None:
    reset_for_tests()
    yield
    reset_for_tests()


class _FakeCounter:
    def __init__(self) -> None:
        self.adds: list[tuple[int, dict]] = []

    def add(self, n: int, attrs: dict) -> None:
        self.adds.append((n, dict(attrs)))


class _FakeHist:
    def __init__(self) -> None:
        self.records: list[tuple[float, dict]] = []

    def record(self, value: float, attrs: dict) -> None:
        self.records.append((value, dict(attrs)))


def test_setup_otel_noop_without_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    before = {k for k in sys.modules if k.startswith("opentelemetry")}
    assert setup_otel() is False
    assert otel_enabled() is False
    after = {k for k in sys.modules if k.startswith("opentelemetry")}
    assert after == before


def test_setup_otel_respects_sdk_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")
    before = {k for k in sys.modules if k.startswith("opentelemetry")}
    assert setup_otel() is False
    after = {k for k in sys.modules if k.startswith("opentelemetry")}
    assert after == before


def test_importing_daemon_and_cli_does_not_load_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    before = {k for k in sys.modules if k.startswith("opentelemetry")}
    import fragrantica.cli  # noqa: F401
    import fragrantica.pipeline.daemon  # noqa: F401
    import fragrantica.pipeline.runner  # noqa: F401

    after = {k for k in sys.modules if k.startswith("opentelemetry")}
    assert after == before
    assert otel_enabled() is False


def test_kind_from_url() -> None:
    assert kind_from_url("https://www.fragrantica.com/designers/Dior.html") == "designer"
    assert kind_from_url("https://www.fragrantica.com/perfume/Dior/Sauvage-31861.html") == "perfume"
    assert kind_from_url("https://www.fragrantica.com/@quilter") == "profile"
    assert kind_from_url("https://www.fragrantica.com/ajax.php?user_shelves", method="POST") == "shelves"
    assert kind_from_url("https://example.com/") == "other"


def test_classify_http() -> None:
    assert classify_http(200) == ("200", "200")
    assert classify_http(429) == ("429", "429")
    assert classify_http(403) == ("403", "403")
    assert classify_http(200, interstitial=True) == ("interstitial", "200")
    assert classify_http(403, interstitial=True) == ("interstitial", "403")
    assert classify_http(0, network_error=True) == ("error", "0")
    assert classify_http(502) == ("error", "502")


def test_egress_via() -> None:
    assert egress_via(CrawlConfig(proxies=(), shelves_proxies=())) == "home"
    assert egress_via(CrawlConfig(proxies=("http://p",), shelves_proxies=())) == "proxy"
    assert (
        egress_via(CrawlConfig(proxies=(), shelves_proxies=("http://s",)), shelves=True)
        == "shelves_proxy"
    )
    # Sin proxy de shelves, el POST sale por la misma via que el HTML.
    assert (
        egress_via(CrawlConfig(proxies=("http://p",), shelves_proxies=()), shelves=True)
        == "proxy"
    )


def test_record_http_increments_fake_counter() -> None:
    requests = _FakeCounter()
    failures = _FakeCounter()
    duration = _FakeHist()
    bind_test_instruments(requests=requests, failures=failures, duration=duration)
    record_http("perfume", "200", 0.42, status=200)
    record_http("profile", "429", 1.2, status=429)
    record_http("perfume", "interstitial", 0.3, status=200)
    record_http("perfume", "403", 0.2, status=403)
    record_runner_outcome("already_have", "perfume")
    assert requests.adds == [
        (1, {"kind": "perfume", "outcome": "200", "status": "200", "phase": "0", "via": "home"}),
        (1, {"kind": "profile", "outcome": "429", "status": "429", "phase": "0", "via": "home"}),
        (1, {"kind": "perfume", "outcome": "interstitial", "status": "200", "phase": "0", "via": "home"}),
        (1, {"kind": "perfume", "outcome": "403", "status": "403", "phase": "0", "via": "home"}),
        (1, {"kind": "perfume", "outcome": "already_have", "status": "none", "phase": "0", "via": "home"}),
    ]
    assert failures.adds == [
        (1, {"status_code": "429", "kind": "profile", "phase": "0", "via": "home"}),
        (1, {"status_code": "interstitial", "kind": "perfume", "phase": "0", "via": "home"}),
        (1, {"status_code": "403", "kind": "perfume", "phase": "0", "via": "home"}),
    ]
    assert duration.records == [
        (0.42, {"kind": "perfume"}),
        (1.2, {"kind": "profile"}),
        (0.3, {"kind": "perfume"}),
        (0.2, {"kind": "perfume"}),
    ]


def test_record_http_uses_snapshot_phase_and_via() -> None:
    from fragrantica import observability as obs

    requests = _FakeCounter()
    bind_test_instruments(requests=requests)
    obs._snapshot["phase"] = 2
    obs._snapshot["via"] = "proxy"
    record_http("perfume", "429", 0.1, status=429)
    assert requests.adds[0][1]["phase"] == "2"
    assert requests.adds[0][1]["via"] == "proxy"


def test_record_cooldown() -> None:
    counter = _FakeCounter()
    hist = _FakeHist()
    bind_test_instruments(cooldowns=counter, cooldown_duration=hist)
    record_cooldown(reason="429", duration_s=300, phase=2, via="home")
    record_cooldown(
        reason="429", duration_s=2700, phase=3, via="shelves_proxy", kind="shelves"
    )
    assert counter.adds == [
        (1, {"reason": "429", "phase": "2", "via": "home", "kind": "page"}),
        (1, {"reason": "429", "phase": "3", "via": "shelves_proxy", "kind": "shelves"}),
    ]
    assert hist.records[0] == (300.0, {"reason": "429", "phase": "2", "via": "home", "kind": "page"})


def test_record_records_maps_writer_names() -> None:
    records = _FakeCounter()
    bind_test_instruments(records=records)
    record_records("interactions_from_perfume", 3)
    record_records("wardrobe", 2)
    record_records("items", 0)
    assert records.adds == [
        (3, {"table": "interactions"}),
        (2, {"table": "wardrobe"}),
    ]


def test_record_block() -> None:
    blocks = _FakeCounter()
    bind_test_instruments(blocks=blocks)
    record_block("429")
    record_block("challenge")
    assert blocks.adds == [
        (1, {"reason": "429"}),
        (1, {"reason": "challenge"}),
    ]


def test_attach_snapshot_from_frontier(tmp_path: Path) -> None:
    from fragrantica import observability as obs

    fr = Frontier(tmp_path / "f.db")
    fr.add("https://x/p", "perfume", "1")
    attach_snapshot(frontier=fr, phase=2, cooldown_remaining=15.0)
    assert obs._snapshot["phase"] == 2
    assert obs._snapshot["cooldown_remaining"] == 15.0
    assert obs._snapshot["frontier"]["perfume:pending"] == 1
    fr.close()


def test_next_phase_unchanged_with_otel_hooks(tmp_path: Path) -> None:
    """Los gauges no alteran la eleccion de fase."""
    bind_test_instruments(requests=_FakeCounter())
    fr = Frontier(tmp_path / "f.db")
    assert next_phase(fr) is None
    fr.add("https://x/@a", "profile", "a")
    attach_snapshot(frontier=fr, phase=3)
    assert next_phase(fr) == 3
    fr.close()


def test_in_memory_meter_if_sdk_installed() -> None:
    pytest.importorskip("opentelemetry.sdk.metrics")
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader

    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("test")
    counter = meter.create_counter("fragrantica.http.requests")
    bind_test_instruments(requests=counter)
    record_http("perfume", "200", 0.1, status=200)
    found = False
    want = {
        "kind": "perfume",
        "outcome": "200",
        "status": "200",
        "phase": "0",
        "via": "home",
    }
    for resource_metrics in reader.get_metrics_data().resource_metrics:
        for scope in resource_metrics.scope_metrics:
            for metric in scope.metrics:
                for point in metric.data.data_points:
                    if dict(point.attributes) == want:
                        assert point.value == 1
                        found = True
    provider.shutdown()
    assert found


def test_python_logs_bridge_to_otel() -> None:
    pytest.importorskip("opentelemetry.sdk._logs")
    import logging

    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import (
        InMemoryLogRecordExporter,
        SimpleLogRecordProcessor,
    )

    exporter = InMemoryLogRecordExporter()
    provider = LoggerProvider()
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    handler = install_log_handler(provider)
    try:
        logging.getLogger("fragrantica.pipeline.daemon").warning(
            "pausa global de 300s: HTTP 429"
        )
        logging.getLogger("curl_cffi").warning("no debe ir a otel")
        finished = exporter.get_finished_logs()
        bodies = [str(item.log_record.body) for item in finished]
        assert any("pausa global" in b for b in bodies)
        assert all("no debe ir a otel" not in b for b in bodies)
        assert any(item.log_record.severity_text == "WARN" for item in finished)
    finally:
        logging.getLogger("fragrantica").removeHandler(handler)
        provider.shutdown()


def test_setup_otel_noop_does_not_attach_log_handler() -> None:
    import logging

    n = len(logging.getLogger("fragrantica").handlers)
    assert setup_otel() is False
    assert len(logging.getLogger("fragrantica").handlers) == n
