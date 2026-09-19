"""Tests de idempotencia de escritura y de deteccion de challenge."""

from pathlib import Path

import pyarrow.parquet as pq

from fragrantica.http_client import looks_like_challenge
from fragrantica.models import Interaction
from fragrantica.storage import ParquetWriter

FX = Path(__file__).parent / "fixtures"


def test_writer_flushes_atomically(tmp_path):
    w = ParquetWriter(tmp_path, "interactions", flush_every=2)
    for i in range(5):
        w.add(Interaction(review_id=i + 1, perfume_id=10, username_slug="u"))
    w.flush()
    files = list((tmp_path / "interactions").glob("*.parquet"))
    assert files
    # Ningun .tmp sobreviviente: el rename se completo.
    assert not list((tmp_path / "interactions").glob("*.tmp"))
    total = sum(pq.read_table(f).num_rows for f in files)
    assert total == 5


def test_orphan_tmp_is_cleaned_on_startup(tmp_path):
    """Un .tmp de una corrida que murio antes del rename no debe quedar."""
    d = tmp_path / "items"
    d.mkdir(parents=True)
    orphan = d / "part-dead.parquet.tmp"
    orphan.write_bytes(b"basura incompleta")
    ParquetWriter(tmp_path, "items")
    assert not orphan.exists()


def test_nested_fields_are_serialised(tmp_path):
    from fragrantica.models import Accord, Item

    w = ParquetWriter(tmp_path, "items", flush_every=100)
    w.add(
        Item(
            perfume_id=1,
            url="https://x",
            name="X",
            accords=[Accord(name="woody", intensity=90.0)],
            perfumers=["A", "B"],
        )
    )
    w.flush()
    table = pq.read_table(next((tmp_path / "items").glob("*.parquet")))
    row = table.to_pylist()[0]
    assert "woody" in row["accords"]
    assert "A" in row["perfumers"]


# -- deteccion de challenge -----------------------------------------------


def test_real_page_is_not_flagged_as_challenge():
    """El script de Cloudflare esta embebido en TODAS las paginas, incluso las
    buenas. Buscarlo directamente da falsos positivos."""
    body = (FX / "perfume_sauvage.html").read_text()
    assert "challenge-platform" in body  # el script esta presente
    assert looks_like_challenge(body) is False  # y aun asi la pagina es valida


def test_interstitial_is_flagged():
    html = "<html><head><title>Just a moment...</title></head><body></body></html>"
    assert looks_like_challenge(html)
    assert looks_like_challenge(html, kind="json")


def test_short_empty_body_is_flagged():
    assert looks_like_challenge("<html><body></body></html>")


def test_json_ajax_body_is_not_flagged_as_challenge():
    """Un payload {ct,iv,s} es corto y no tiene <main: la heuristic HTML lo
    marcaría como interstitial y tiraríamos todos los shelves."""
    body = '{"ct":"abc","iv":"00","s":"11"}'
    assert looks_like_challenge(body) is True  # kind=html, cuerpo corto
    assert looks_like_challenge(body, kind="json") is False
