"""Tests de las fases 4 y 6 (locales, sin red).

La consolidacion nunca se ejecuto contra el slice real porque la fase 3 no
corrio y todas las interacciones tienen member_id nulo. Estos tests cubren
ese camino y el feliz, para no descubrir un bug de DuckDB a mitad del export.
"""

from pathlib import Path

import pyarrow.parquet as pq

from fragrantica.config import DatasetConfig
from fragrantica.frontier import Frontier
from fragrantica.models import Interaction, Item, User, WardrobeItem
from fragrantica.pipeline.consolidate import consolidate
from fragrantica.storage import ParquetWriter


def _cfg(**kwargs) -> DatasetConfig:
    return DatasetConfig(username_salt="test-salt", **kwargs)


def _write(staging: Path, name: str, records: list) -> None:
    with ParquetWriter(staging, name, flush_every=1000) as w:
        w.add_many(records)


def _item(pid: int, scraped: int = 5) -> Item:
    return Item(
        perfume_id=pid,
        url=f"https://www.fragrantica.com/perfume/X/X-{pid}.html",
        name=f"P{pid}",
        reviews_scraped=scraped,
    )


def _user(mid: int, slug: str, n: int = 5) -> User:
    return User(member_id=mid, username_slug=slug, n_reviews_scraped=n)


def _inter(
    rid: int | None,
    pid: int,
    slug: str,
    mid: int | None = None,
    source: str = "perfume_page",
    rating: int | None = 4,
) -> Interaction:
    return Interaction(
        review_id=rid,
        perfume_id=pid,
        member_id=mid,
        username_slug=slug,
        rating=rating,
        source=source,  # type: ignore[arg-type]
    )


def test_null_member_id_drops_everything(tmp_path: Path) -> None:
    """El estado actual del slice: fase 3 no corrio, ninguna FK se resuelve."""
    staging, final = tmp_path / "staging", tmp_path / "final"
    _write(staging, "items", [_item(1)])
    _write(staging, "interactions_from_perfume", [_inter(10, 1, "alice")])
    fr = Frontier(tmp_path / "f.db")

    rep = consolidate(staging, final, fr, _cfg(k_core=1, sensitivity_k_values=(1,)))

    assert rep.interactions_raw == 1
    assert rep.dropped_null_member == 1
    assert rep.interactions_clean == 0
    assert rep.kcore_interactions == 0
    fr.close()


def test_phase4_backfills_member_id_from_slug_map(tmp_path: Path) -> None:
    """La pagina de perfume no trae member_id; la fase 4 lo resuelve por slug."""
    staging, final = tmp_path / "staging", tmp_path / "final"
    _write(staging, "items", [_item(1), _item(2)])
    _write(
        staging,
        "interactions_from_perfume",
        [_inter(10, 1, "alice"), _inter(11, 2, "alice")],
    )
    _write(staging, "users", [_user(99, "alice", n=2)])
    fr = Frontier(tmp_path / "f.db")
    fr.record_member_id("alice", 99)

    rep = consolidate(staging, final, fr, _cfg(k_core=1, sensitivity_k_values=(1,)))

    assert rep.dropped_null_member == 0
    assert rep.interactions_clean == 2
    assert rep.kcore_users == 1
    assert rep.kcore_items == 2
    table = pq.read_table(final / "interactions.parquet")
    assert table.column("member_id").to_pylist() == [99, 99]
    assert "username_slug" not in table.column_names
    assert "user_hash" in table.column_names
    fr.close()


def test_dedup_prefers_profile_page(tmp_path: Path) -> None:
    staging, final = tmp_path / "staging", tmp_path / "final"
    _write(staging, "items", [_item(1)])
    _write(
        staging,
        "interactions_from_perfume",
        [_inter(10, 1, "alice", rating=3, source="perfume_page")],
    )
    _write(
        staging,
        "interactions_from_profile",
        [_inter(10, 1, "alice", mid=99, rating=5, source="profile_page")],
    )
    _write(staging, "users", [_user(99, "alice", n=1)])
    fr = Frontier(tmp_path / "f.db")
    fr.record_member_id("alice", 99)

    rep = consolidate(staging, final, fr, _cfg(k_core=1, sensitivity_k_values=(1,)))

    assert rep.interactions_raw == 2
    assert rep.interactions_deduped == 1
    ratings = pq.read_table(final / "interactions.parquet").column("rating").to_pylist()
    assert ratings == [5]
    fr.close()


def test_kcore_cascades_until_fixed_point(tmp_path: Path) -> None:
    """Un usuario con 2 reviews no alcanza k=2 si uno de esos items tambien cae."""
    staging, final = tmp_path / "staging", tmp_path / "final"
    # alice: items 1,2   bob: item 1 solamente
    # k=2: bob cae -> item 1 queda con 1 review -> item 1 cae -> alice queda con 1 -> alice cae
    _write(staging, "items", [_item(1), _item(2)])
    _write(
        staging,
        "interactions_from_perfume",
        [
            _inter(1, 1, "alice"),
            _inter(2, 2, "alice"),
            _inter(3, 1, "bob"),
        ],
    )
    _write(staging, "users", [_user(1, "alice"), _user(2, "bob")])
    fr = Frontier(tmp_path / "f.db")
    fr.record_member_id("alice", 1)
    fr.record_member_id("bob", 2)

    rep = consolidate(staging, final, fr, _cfg(k_core=2, sensitivity_k_values=(2,)))

    assert rep.interactions_clean == 3
    assert rep.kcore_interactions == 0
    fr.close()


def test_kcore_keeps_dense_subgraph(tmp_path: Path) -> None:
    staging, final = tmp_path / "staging", tmp_path / "final"
    items = [_item(i) for i in (1, 2, 3)]
    users = [_user(u, f"u{u}") for u in (10, 20, 30)]
    inters = []
    rid = 0
    for u, slug in ((10, "u10"), (20, "u20"), (30, "u30")):
        for pid in (1, 2, 3):
            rid += 1
            inters.append(_inter(rid, pid, slug))
    _write(staging, "items", items)
    _write(staging, "users", users)
    _write(staging, "interactions_from_perfume", inters)
    fr = Frontier(tmp_path / "f.db")
    for u, slug in ((10, "u10"), (20, "u20"), (30, "u30")):
        fr.record_member_id(slug, u)

    rep = consolidate(staging, final, fr, _cfg(k_core=3, sensitivity_k_values=(1, 3)))

    assert rep.kcore_interactions == 9
    assert rep.kcore_users == 3
    assert rep.kcore_items == 3
    assert (final / "dataset_card.md").exists()
    assert (final / "PRIVATE_user_mapping.parquet").exists()
    fr.close()


def test_dedup_prefers_review_over_vote(tmp_path: Path) -> None:
    staging, final = tmp_path / "staging", tmp_path / "final"
    _write(staging, "items", [_item(1)])
    _write(
        staging,
        "interactions_from_perfume",
        [_inter(10, 1, "alice", rating=3, source="perfume_page")],
    )
    _write(
        staging,
        "interactions_from_profile",
        [_inter(None, 1, "alice", mid=99, rating=5, source="vote")],
    )
    _write(staging, "users", [_user(99, "alice", n=1)])
    fr = Frontier(tmp_path / "f.db")
    fr.record_member_id("alice", 99)

    rep = consolidate(staging, final, fr, _cfg(k_core=1, sensitivity_k_values=(1,)))

    assert rep.interactions_raw == 2
    assert rep.interactions_deduped == 1
    table = pq.read_table(final / "interactions.parquet")
    assert table.column("rating").to_pylist() == [3]
    assert table.column("source").to_pylist() == ["perfume_page"]
    fr.close()


def test_wardrobe_is_a_separate_table(tmp_path: Path) -> None:
    """have/had/want no se colapsa con la review: conviven en archivos distintos."""
    staging, final = tmp_path / "staging", tmp_path / "final"
    _write(staging, "items", [_item(1), _item(2)])
    _write(
        staging,
        "interactions_from_perfume",
        [_inter(10, 1, "alice", rating=3, source="perfume_page")],
    )
    _write(
        staging,
        "wardrobe",
        [
            WardrobeItem(member_id=99, username_slug="alice", perfume_id=1, relation="have"),
            WardrobeItem(member_id=99, username_slug="alice", perfume_id=2, relation="want"),
        ],
    )
    _write(staging, "users", [_user(99, "alice", n=1)])
    fr = Frontier(tmp_path / "f.db")
    fr.record_member_id("alice", 99)

    rep = consolidate(staging, final, fr, _cfg(k_core=1, sensitivity_k_values=(1,)))

    assert rep.interactions_raw == 1
    assert rep.interactions_deduped == 1
    assert rep.wardrobe_rows == 2
    inter = pq.read_table(final / "interactions.parquet")
    assert inter.column("source").to_pylist() == ["perfume_page"]
    assert "wardrobe" not in inter.column("source").to_pylist()
    wardrobe = pq.read_table(final / "wardrobe.parquet")
    relations = set(zip(wardrobe.column("perfume_id").to_pylist(), wardrobe.column("relation").to_pylist()))
    assert relations == {(1, "have"), (2, "want")}
    assert "username_slug" not in wardrobe.column_names
    assert "user_hash" in wardrobe.column_names
    fr.close()


def test_wardrobe_survives_kcore_drop(tmp_path: Path) -> None:
    """k=2 tira a alice de la matriz; su coleccion no deberia desaparecer."""
    staging, final = tmp_path / "staging", tmp_path / "final"
    _write(staging, "items", [_item(1), _item(2)])
    _write(staging, "interactions_from_perfume", [_inter(10, 1, "alice")])
    _write(
        staging,
        "wardrobe",
        [
            WardrobeItem(member_id=99, username_slug="alice", perfume_id=1, relation="have"),
            WardrobeItem(member_id=99, username_slug="alice", perfume_id=2, relation="had"),
        ],
    )
    _write(staging, "users", [_user(99, "alice", n=1)])
    fr = Frontier(tmp_path / "f.db")
    fr.record_member_id("alice", 99)

    rep = consolidate(staging, final, fr, _cfg(k_core=2, sensitivity_k_values=(2,)))

    assert rep.kcore_interactions == 0
    assert rep.wardrobe_rows == 2
    fr.close()


def test_null_review_id_does_not_collapse_all_votes(tmp_path: Path) -> None:
    """Si se deduplicara solo por review_id, dos votos con NULL serian uno."""
    staging, final = tmp_path / "staging", tmp_path / "final"
    _write(staging, "items", [_item(1), _item(2)])
    _write(
        staging,
        "interactions_from_profile",
        [
            _inter(None, 1, "alice", mid=99, rating=5, source="vote"),
            _inter(None, 2, "alice", mid=99, rating=4, source="vote"),
        ],
    )
    _write(staging, "users", [_user(99, "alice", n=2)])
    fr = Frontier(tmp_path / "f.db")
    fr.record_member_id("alice", 99)

    rep = consolidate(staging, final, fr, _cfg(k_core=1, sensitivity_k_values=(1,)))

    assert rep.interactions_deduped == 2
    assert rep.kcore_interactions == 2
    fr.close()


def test_mixed_null_and_bigint_user_parquet_schema(tmp_path: Path) -> None:
    """Un part todo-null infiere NULL; otro con signature_perfume_id infiere BIGINT."""
    staging, final = tmp_path / "staging", tmp_path / "final"
    _write(staging, "items", [_item(1)])
    _write(staging, "interactions_from_perfume", [_inter(10, 1, "alice")])
    with ParquetWriter(staging, "users", flush_every=1) as w:
        w.add(_user(99, "alice", n=1))
        w.add(
            User(
                member_id=100,
                username_slug="bob",
                n_reviews_scraped=1,
                signature_perfume_id=31861,
            )
        )
    fr = Frontier(tmp_path / "f.db")
    fr.record_member_id("alice", 99)

    rep = consolidate(staging, final, fr, _cfg(k_core=1, sensitivity_k_values=(1,)))

    assert rep.users_clean == 2
    assert rep.interactions_clean == 1
    fr.close()


def test_consolidate_with_readonly_frontier_and_overwrite(tmp_path: Path) -> None:
    """La fase 6 lee member_ids en paralelo al daemon y pisa un final previo."""
    staging, final = tmp_path / "staging", tmp_path / "final"
    _write(staging, "items", [_item(1)])
    _write(staging, "users", [_user(99, "alice")])
    _write(staging, "interactions_from_perfume", [_inter(10, 1, "alice")])
    w = Frontier(tmp_path / "f.db")
    w.record_member_id("alice", 99)
    w.close()

    final.mkdir()
    (final / "items.parquet").write_bytes(b"stale")
    (final / "interactions.parquet").write_bytes(b"stale")

    ro = Frontier(tmp_path / "f.db", readonly=True)
    rep = consolidate(staging, final, ro, _cfg(k_core=1, sensitivity_k_values=(1,)))
    ro.close()

    assert rep.kcore_interactions == 1
    items = pq.read_table(final / "items.parquet")
    assert items.num_rows == 1
    assert (final / "dataset_card.md").read_text().startswith("# Dataset card")
    leftover = list((tmp_path / "_consolidate_work").glob("*")) if (tmp_path / "_consolidate_work").exists() else []
    assert leftover == []


def test_reset_rate_limited_clears_attempts(tmp_path: Path) -> None:
    fr = Frontier(tmp_path / "f.db")
    fr.add("https://x/1", "perfume", "1")
    fr.claim("perfume", 1)
    fr.mark_failed("https://x/1", "HTTP 429 en https://x/1", max_attempts=1, backoff=0)
    fr.add("https://x/2", "perfume", "2")
    fr.claim("perfume", 1)
    fr.mark_failed("https://x/2", "HTTP 403 / interstitial en https://x/2", max_attempts=1, backoff=0)
    assert len(fr.dead_letters()) == 2
    n = fr.reset_rate_limited("perfume")
    assert n == 2
    assert fr.pending_count("perfume") == 2
    assert not fr.dead_letters()
    rows = fr.conn.execute("SELECT attempts FROM frontier").fetchall()
    assert all(r["attempts"] == 0 for r in rows)
    fr.close()
