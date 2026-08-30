"""Tests de la maquina de estados del frontier.

Cubren especificamente los escenarios de reanudacion: fallo con reintento
diferido, dead-letter tras agotar intentos, y recuperacion de una caida dura.
"""

import time

import pytest

from fragrantica.frontier import Frontier, backoff_delay


@pytest.fixture
def fr(tmp_path):
    f = Frontier(tmp_path / "test.db")
    yield f
    f.close()


def test_add_is_idempotent(fr):
    assert fr.add("https://x/1", "perfume", "1") is True
    assert fr.add("https://x/1", "perfume", "1") is False
    assert fr.stats() == {("perfume", "pending"): 1}


def test_claim_marks_in_progress_and_is_exclusive(fr):
    fr.add("https://x/1", "perfume", "1")
    first = fr.claim("perfume", 5)
    assert len(first) == 1
    # Ya reclamado: un segundo claim no lo devuelve.
    assert fr.claim("perfume", 5) == []
    assert fr.in_flight_count("perfume") == 1


def test_done_is_terminal(fr):
    fr.add("https://x/1", "perfume", "1")
    row = fr.claim("perfume", 1)[0]
    fr.mark_done(row["url"])
    assert fr.stats() == {("perfume", "done"): 1}
    assert fr.pending_count("perfume") == 0


def test_failed_item_returns_to_queue_after_backoff(fr):
    """Un item que falla no bloquea la cola ni se pierde."""
    fr.add("https://x/1", "perfume", "1")
    row = fr.claim("perfume", 1)[0]

    outcome = fr.mark_failed(row["url"], "timeout", max_attempts=5, backoff=60)
    assert outcome == "failed"
    # Con el backoff vigente todavia no es elegible.
    assert fr.pending_count("perfume") == 0
    assert fr.claim("perfume", 1) == []

    # Con backoff vencido vuelve a estar disponible.
    fr.mark_failed(row["url"], "timeout", max_attempts=5, backoff=0)
    assert fr.pending_count("perfume") == 1
    again = fr.claim("perfume", 1)
    assert len(again) == 1
    assert again[0]["attempts"] == 2


def test_dead_letter_after_max_attempts(fr):
    fr.add("https://x/1", "perfume", "1")
    for _ in range(4):
        fr.claim("perfume", 1)
        outcome = fr.mark_failed("https://x/1", "boom", max_attempts=5, backoff=0)
        assert outcome == "failed"
    fr.claim("perfume", 1)
    assert fr.mark_failed("https://x/1", "boom", max_attempts=5, backoff=0) == "dead"
    assert len(fr.dead_letters()) == 1
    assert fr.pending_count("perfume") == 0


def test_retry_dead_requeues(fr):
    fr.add("https://x/1", "perfume", "1")
    fr.claim("perfume", 1)
    fr.mark_failed("https://x/1", "boom", max_attempts=1, backoff=0)
    assert len(fr.dead_letters()) == 1
    assert fr.retry_dead() == 1
    assert fr.pending_count("perfume") == 1


def test_skipped_is_not_retried(fr):
    """Descarte deliberado (404, item sin reviews): distinto de un fallo."""
    fr.add("https://x/1", "perfume", "1")
    fr.claim("perfume", 1)
    fr.mark_skipped("https://x/1", "sin reviews")
    assert fr.stats() == {("perfume", "skipped"): 1}
    assert fr.pending_count("perfume") == 0
    assert fr.claim("perfume", 1) == []


def test_hard_crash_recovery_via_lease_expiry(fr):
    """El escenario del kill -9 con requests en vuelo.

    Sin esto las URLs quedarian in_progress para siempre y se perderian.
    """
    fr.add("https://x/1", "perfume", "1")
    fr.add("https://x/2", "perfume", "2")
    claimed = fr.claim("perfume", 2)
    assert len(claimed) == 2
    assert fr.pending_count("perfume") == 0  # simula el proceso muerto

    # Un lease todavia vigente no se toca: otro proceso puede estar trabajando.
    assert fr.reclaim_stale(lease_timeout=900) == 0

    # Envejecemos los leases artificialmente.
    fr.conn.execute("UPDATE frontier SET claimed_at = ?", (int(time.time()) - 1000,))
    assert fr.reclaim_stale(lease_timeout=900) == 2
    assert fr.pending_count("perfume") == 2


def test_requeue_does_not_count_an_attempt(fr):
    """Un 429 no dice nada sobre esta URL, solo sobre nuestro ritmo.

    Si le contara un intento, una URL sana terminaria en dead-letter por un
    problema ajeno.
    """
    fr.add("https://x/1", "perfume", "1")
    fr.claim("perfume", 1)
    for _ in range(10):
        fr.requeue("https://x/1", "HTTP 429", delay=0)
        fr.claim("perfume", 1)
    row = fr.conn.execute("SELECT attempts, status FROM frontier").fetchone()
    assert row["attempts"] == 0
    assert not fr.dead_letters()


def test_waiting_count_separates_deferred_work(fr):
    """El runner no debe terminar mientras haya items esperando backoff."""
    fr.add("https://x/1", "perfume", "1")
    fr.claim("perfume", 1)
    fr.requeue("https://x/1", "HTTP 429", delay=300)

    # No es elegible ahora...
    assert fr.pending_count("perfume") == 0
    assert fr.claim("perfume", 1) == []
    # ...pero sigue habiendo trabajo por hacer.
    assert fr.waiting_count("perfume") == 1
    assert fr.in_flight_count("perfume") == 0

    eta = fr.next_retry_eta("perfume")
    assert eta is not None and eta > time.time()


def test_waiting_count_zero_when_all_eligible(fr):
    fr.add("https://x/1", "perfume", "1")
    assert fr.waiting_count("perfume") == 0
    assert fr.pending_count("perfume") == 1


def test_priority_ordering(fr):
    """Los usuarios de items truncados se crawlean primero."""
    fr.add("https://x/low", "profile", "low", priority=60)
    fr.add("https://x/high", "profile", "high", priority=20)
    rows = fr.claim("profile", 2)
    assert [r["entity_id"] for r in rows] == ["high", "low"]


def test_member_id_map_roundtrip(fr):
    fr.record_member_id("Quilter", 3158387)
    fr.record_member_id("lanes100", 3146574)
    assert fr.member_id_map() == {"quilter": 3158387, "lanes100": 3146574}


def test_member_id_upsert(fr):
    fr.record_member_id("a", 1)
    fr.record_member_id("a", 2)
    assert fr.member_id_map() == {"a": 2}


def test_backoff_grows_and_is_capped():
    delays = [backoff_delay(n, base=4, cap=600) for n in range(1, 8)]
    assert delays[0] < delays[-1]
    assert all(d <= 600 for d in delays)


def test_state_survives_reopen(tmp_path):
    """El estado esta en disco, no en memoria: es lo que hace segura la reanudacion."""
    db = tmp_path / "f.db"
    f1 = Frontier(db)
    f1.add("https://x/1", "perfume", "1")
    f1.claim("perfume", 1)
    f1.mark_done("https://x/1")
    f1.add("https://x/2", "perfume", "2")
    f1.close()

    f2 = Frontier(db)
    assert f2.stats() == {("perfume", "done"): 1, ("perfume", "pending"): 1}
    f2.close()


def test_drop_perfumes_not_from_keeps_done(fr):
    fr.add("https://www.fragrantica.com/perfume/Dior/A-1.html", "perfume", "1")
    fr.add("https://www.fragrantica.com/perfume/Le-Labo/B-2.html", "perfume", "2")
    fr.add("https://www.fragrantica.com/perfume/Lattafa-Perfumes/C-3.html", "perfume", "3")
    fr.claim("perfume", 3)
    fr.mark_done("https://www.fragrantica.com/perfume/Le-Labo/B-2.html")
    n = fr.drop_perfumes_not_from("Dior", keep_done=True)
    assert n == 1  # Lattafa pending; Le-Labo done se conserva
    urls = {r[0] for r in fr.conn.execute("SELECT url FROM frontier")}
    assert "https://www.fragrantica.com/perfume/Dior/A-1.html" in urls
    assert "https://www.fragrantica.com/perfume/Le-Labo/B-2.html" in urls
    assert "https://www.fragrantica.com/perfume/Lattafa-Perfumes/C-3.html" not in urls


def test_drop_profiles_except(fr):
    fr.add("https://www.fragrantica.com/@alice", "profile", "alice")
    fr.add("https://www.fragrantica.com/@bob", "profile", "bob")
    fr.add("https://www.fragrantica.com/@carol", "profile", "carol")
    fr.claim("profile", 1)
    fr.mark_done("https://www.fragrantica.com/@alice")
    n = fr.drop_profiles_except({"bob"})
    assert n == 1  # carol pending fuera; alice done se conserva
    left = {r[0] for r in fr.conn.execute("SELECT entity_id FROM frontier WHERE kind='profile'")}
    assert left == {"alice", "bob"}


def test_requeue_done_profiles_leaves_never_visited_first(fr):
    fr.add("https://www.fragrantica.com/@alice", "profile", "alice", priority=60)
    fr.add("https://www.fragrantica.com/@bob", "profile", "bob", priority=60)
    fr.add("https://www.fragrantica.com/@carol", "profile", "carol", priority=60)
    fr.claim("profile", 1)
    fr.mark_done("https://www.fragrantica.com/@alice")
    fr.claim("profile", 1)  # bob queda in_progress
    n = fr.requeue_done_profiles()
    assert n == 2
    stats = fr.stats()
    assert stats[("profile", "pending")] == 3
    pri = {
        r["entity_id"]: r["priority"]
        for r in fr.conn.execute("SELECT entity_id, priority FROM frontier")
    }
    assert pri["alice"] == 90
    assert pri["bob"] == 90
    assert pri["carol"] == 60
    first = fr.claim("profile", 1)[0]["entity_id"]
    assert first == "carol"


def test_entity_is_done(fr):
    fr.add("https://x/1", "perfume", "31861")
    assert fr.entity_is_done("perfume", "31861") is False
    fr.claim("perfume", 1)
    fr.mark_done("https://x/1")
    assert fr.entity_is_done("perfume", "31861") is True
