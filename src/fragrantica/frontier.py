"""Frontier persistente: maquina de estados del crawl en SQLite.

Todo el estado vive en disco, commiteado transaccionalmente. Esa es la
propiedad que hace la reanudacion confiable: un kill -9 o un corte de energia
no pierde nada, porque nunca hubo estado critico solo en memoria.

Maquina de estados:

    pending --claim--> in_progress --ok--------> done
                            |
                            +--error transitoria--> failed --backoff--> pending
                            |                          |
                            |                    (attempts >= MAX)
                            |                          v
                            |                        dead
                            +--404 / sin reviews-----> skipped
                            +--interstitial + canario OK -> deferred (reintento largo)
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

Kind = Literal["designer", "perfume", "profile"]
Status = Literal["pending", "in_progress", "done", "failed", "skipped", "dead", "deferred"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS frontier (
    url            TEXT PRIMARY KEY,
    kind           TEXT NOT NULL,
    entity_id      TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',
    attempts       INTEGER NOT NULL DEFAULT 0,
    last_error     TEXT,
    next_retry_at  INTEGER,
    claimed_at     INTEGER,
    priority       INTEGER NOT NULL DEFAULT 100,
    updated_at     INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_claimable
    ON frontier(kind, status, priority, next_retry_at);

CREATE INDEX IF NOT EXISTS idx_entity
    ON frontier(kind, entity_id);

-- Mapa username_slug -> member_id, poblado en la fase 3 y consumido por la
-- fase 4 para resolver la FK de interactions.
CREATE TABLE IF NOT EXISTS member_ids (
    username_slug TEXT PRIMARY KEY,
    member_id     INTEGER NOT NULL
);
"""


class Frontier:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=60.0, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    # -- alta de trabajo ----------------------------------------------------

    def add(self, url: str, kind: Kind, entity_id: str, priority: int = 100) -> bool:
        """Encola una URL. Idempotente: reencolar algo ya visto no lo resetea."""
        now = int(time.time())
        cur = self.conn.execute(
            """
            INSERT INTO frontier (url, kind, entity_id, status, priority, updated_at)
            VALUES (?, ?, ?, 'pending', ?, ?)
            ON CONFLICT(url) DO NOTHING
            """,
            (url, kind, entity_id, priority, now),
        )
        return cur.rowcount > 0

    def add_many(self, rows: list[tuple[str, Kind, str, int]]) -> int:
        now = int(time.time())
        with self._tx() as conn:
            before = conn.execute("SELECT count(*) FROM frontier").fetchone()[0]
            conn.executemany(
                """
                INSERT INTO frontier (url, kind, entity_id, status, priority, updated_at)
                VALUES (?, ?, ?, 'pending', ?, ?)
                ON CONFLICT(url) DO NOTHING
                """,
                [(u, k, e, p, now) for u, k, e, p in rows],
            )
            after = conn.execute("SELECT count(*) FROM frontier").fetchone()[0]
        return after - before

    # -- recuperacion de caida dura -----------------------------------------

    def reclaim_stale(self, lease_timeout: int) -> int:
        """Devuelve a la cola el trabajo abandonado por un proceso muerto.

        Este es el mecanismo que hace segura la reanudacion tras un kill -9:
        las URLs que quedaron 'in_progress' con requests en vuelo vuelven a
        'pending' en vez de quedar bloqueadas para siempre.
        """
        cutoff = int(time.time()) - lease_timeout
        with self._tx() as conn:
            cur = conn.execute(
                """
                UPDATE frontier
                   SET status='pending', claimed_at=NULL, updated_at=?
                 WHERE status='in_progress' AND (claimed_at IS NULL OR claimed_at < ?)
                """,
                (int(time.time()), cutoff),
            )
        return cur.rowcount

    # -- consumo ------------------------------------------------------------

    def claim(self, kind: Kind, n: int = 1) -> list[sqlite3.Row]:
        """Reclama hasta n URLs de forma atomica."""
        now = int(time.time())
        with self._tx() as conn:
            rows = conn.execute(
                """
                SELECT * FROM frontier
                 WHERE kind = ?
                   AND status IN ('pending', 'failed', 'deferred')
                   AND (next_retry_at IS NULL OR next_retry_at <= ?)
                 ORDER BY priority ASC, attempts ASC
                 LIMIT ?
                """,
                (kind, now, n),
            ).fetchall()
            if rows:
                conn.executemany(
                    "UPDATE frontier SET status='in_progress', claimed_at=?, updated_at=? WHERE url=?",
                    [(now, now, r["url"]) for r in rows],
                )
        return list(rows)

    def mark_done(self, url: str) -> None:
        self.conn.execute(
            "UPDATE frontier SET status='done', claimed_at=NULL, last_error=NULL, updated_at=? WHERE url=?",
            (int(time.time()), url),
        )

    def mark_skipped(self, url: str, reason: str) -> None:
        """Decision deliberada (404 real, item sin reviews). No se reintenta."""
        self.conn.execute(
            "UPDATE frontier SET status='skipped', claimed_at=NULL, last_error=?, updated_at=? WHERE url=?",
            (reason, int(time.time()), url),
        )

    def mark_deferred(self, url: str, error: str, delay: float) -> None:
        """Cuarentena: el canario paso, esta URL es la rara.

        No cuenta intento (igual que requeue). No entra en waiting_count, asi
        el runner no se queda 12 h dormido y el daemon puede pasar a fase 3.
        Cuando vence next_retry_at, claim() la vuelve a tomar.
        """
        now = int(time.time())
        self.conn.execute(
            """UPDATE frontier SET status='deferred', last_error=?, claimed_at=NULL,
               next_retry_at=?, updated_at=? WHERE url=?""",
            (error[:500], now + int(delay), now, url),
        )

    def requeue(self, url: str, error: str, delay: float) -> None:
        """Devuelve una URL a la cola SIN contarle un intento.

        Para el caso del 429: el rate limit no dice nada sobre esta URL en
        particular, solo sobre nuestro ritmo agregado. Contarle un intento la
        mandaria a dead-letter por un problema ajeno.
        """
        now = int(time.time())
        self.conn.execute(
            """UPDATE frontier SET status='pending', last_error=?, claimed_at=NULL,
               next_retry_at=?, updated_at=? WHERE url=?""",
            (error[:500], now + int(delay), now, url),
        )

    def mark_failed(self, url: str, error: str, max_attempts: int, backoff: float) -> Status:
        """Fallo transitorio: vuelve a la cola con backoff, o muere.

        El item que falla no bloquea la cola ni se pierde: el worker sigue con
        el siguiente y este vuelve a ser elegible cuando vence el backoff.
        """
        now = int(time.time())
        with self._tx() as conn:
            row = conn.execute("SELECT attempts FROM frontier WHERE url=?", (url,)).fetchone()
            attempts = (row["attempts"] if row else 0) + 1
            if attempts >= max_attempts:
                conn.execute(
                    """UPDATE frontier SET status='dead', attempts=?, last_error=?,
                       claimed_at=NULL, next_retry_at=NULL, updated_at=? WHERE url=?""",
                    (attempts, error[:500], now, url),
                )
                return "dead"
            conn.execute(
                """UPDATE frontier SET status='failed', attempts=?, last_error=?,
                   claimed_at=NULL, next_retry_at=?, updated_at=? WHERE url=?""",
                (attempts, error[:500], now + int(backoff), now, url),
            )
        return "failed"

    # -- member_id ----------------------------------------------------------

    def record_member_id(self, slug: str, member_id: int) -> None:
        self.conn.execute(
            "INSERT INTO member_ids (username_slug, member_id) VALUES (?, ?) "
            "ON CONFLICT(username_slug) DO UPDATE SET member_id=excluded.member_id",
            (slug.lower(), member_id),
        )

    def member_id_map(self) -> dict[str, int]:
        return {
            r["username_slug"]: r["member_id"]
            for r in self.conn.execute("SELECT username_slug, member_id FROM member_ids")
        }

    # -- observabilidad -----------------------------------------------------

    def stats(self, kind: Kind | None = None) -> dict[tuple[str, str], int]:
        sql = "SELECT kind, status, count(*) AS n FROM frontier"
        params: tuple = ()
        if kind:
            sql += " WHERE kind = ?"
            params = (kind,)
        sql += " GROUP BY kind, status"
        return {(r["kind"], r["status"]): r["n"] for r in self.conn.execute(sql, params)}

    def pending_count(self, kind: Kind) -> int:
        now = int(time.time())
        return self.conn.execute(
            """SELECT count(*) FROM frontier
                WHERE kind=? AND status IN ('pending','failed','deferred')
                  AND (next_retry_at IS NULL OR next_retry_at <= ?)""",
            (kind, now),
        ).fetchone()[0]

    def waiting_count(self, kind: Kind) -> int:
        """Trabajo encolado pero esperando que venza su backoff.

        Se cuenta aparte de pending_count porque el runner no debe terminar
        mientras haya items diferidos: si no, los abandonaria a mitad del
        reintento.
        """
        now = int(time.time())
        return self.conn.execute(
            """SELECT count(*) FROM frontier
                WHERE kind=? AND status IN ('pending','failed')
                  AND next_retry_at IS NOT NULL AND next_retry_at > ?""",
            (kind, now),
        ).fetchone()[0]

    def next_retry_eta(self, kind: Kind) -> int | None:
        row = self.conn.execute(
            """SELECT min(next_retry_at) FROM frontier
                WHERE kind=? AND status IN ('pending','failed') AND next_retry_at IS NOT NULL""",
            (kind,),
        ).fetchone()
        return row[0] if row and row[0] else None

    def in_flight_count(self, kind: Kind) -> int:
        return self.conn.execute(
            "SELECT count(*) FROM frontier WHERE kind=? AND status='in_progress'", (kind,)
        ).fetchone()[0]

    def dead_letters(self, kind: Kind | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM frontier WHERE status='dead'"
        params: tuple = ()
        if kind:
            sql += " AND kind=?"
            params = (kind,)
        return list(self.conn.execute(sql, params))

    def retry_dead(self, kind: Kind | None = None) -> int:
        """Devuelve los dead-letters a la cola, p.ej. para reintentar con otra IP."""
        sql = "UPDATE frontier SET status='pending', attempts=0, next_retry_at=NULL, updated_at=? WHERE status='dead'"
        params: list = [int(time.time())]
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        cur = self.conn.execute(sql, params)
        return cur.rowcount

    def reset_rate_limited(self, kind: Kind | None = None) -> int:
        """Devuelve a pending, sin intentos, todo lo que cayo por HTTP 429.

        El codigo viejo contaba el 429 como intento y mando URLs sanas a
        dead-letter. Un rate limit no dice nada sobre esa URL: hay que
        reintentarla cuando se levante la penalizacion, no castigarla.
        """
        now = int(time.time())
        sql = """
            UPDATE frontier
               SET status='pending', attempts=0, claimed_at=NULL,
                   next_retry_at=NULL, updated_at=?
             WHERE status IN ('failed', 'dead', 'in_progress', 'pending', 'deferred')
               AND (last_error LIKE '%429%'
                    OR last_error LIKE '%403%'
                    OR last_error LIKE '%interstitial%')
        """
        params: list = [now]
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        cur = self.conn.execute(sql, params)
        return cur.rowcount

    def entity_is_done(self, kind: Kind, entity_id: str) -> bool:
        """True si alguna URL de este entity ya se confirmo.

        Sirve para no re-pedir un perfume que se escribio a staging y cuyo
        lease vencio antes del mark_done, o que reaparecio con otra URL.
        """
        row = self.conn.execute(
            """SELECT 1 FROM frontier
                WHERE kind=? AND entity_id=? AND status='done' LIMIT 1""",
            (kind, entity_id),
        ).fetchone()
        return row is not None

    def listed_designer_slugs(self) -> set[str]:
        return {
            r["entity_id"]
            for r in self.conn.execute("SELECT entity_id FROM frontier WHERE kind='designer'")
        }

    def drop_perfumes_not_from(self, designer_slug: str, *, keep_done: bool = True) -> int:
        """Saca del frontier perfumes cuya URL no es de `designer_slug`.

        keep_done=True conserva los ya crawleados: borrar un `done` haria que
        una enumeracion posterior de esa marca lo vuelva a pedir.
        """
        like = f"%/perfume/{designer_slug}/%"
        sql = "DELETE FROM frontier WHERE kind='perfume' AND url NOT LIKE ?"
        params: list = [like]
        if keep_done:
            sql += " AND status != 'done'"
        cur = self.conn.execute(sql, params)
        return cur.rowcount

    def drop_profiles_except(self, slugs: set[str]) -> int:
        """Saca perfiles pending que no estan en `slugs`. No toca los done."""
        with self._tx() as conn:
            conn.execute(
                "CREATE TEMP TABLE IF NOT EXISTS keep_slugs (username_slug TEXT PRIMARY KEY)"
            )
            conn.execute("DELETE FROM keep_slugs")
            if slugs:
                conn.executemany(
                    "INSERT OR IGNORE INTO keep_slugs VALUES (?)",
                    [(s.lower(),) for s in slugs],
                )
            cur = conn.execute(
                """
                DELETE FROM frontier
                 WHERE kind='profile'
                   AND status != 'done'
                   AND entity_id NOT IN (SELECT username_slug FROM keep_slugs)
                """
            )
            n = cur.rowcount
            conn.execute("DROP TABLE keep_slugs")
        return n

    def close(self) -> None:
        self.conn.close()


def backoff_delay(attempts: int, base: float, cap: float) -> float:
    """Backoff exponencial con jitter completo."""
    import random

    return min(cap, base * (2 ** max(0, attempts - 1))) * random.uniform(0.5, 1.0)
