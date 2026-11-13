"""Catálogo en memoria: items, perfiles y perfumes ya vistos."""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import duckdb

from fragrantica_serving.ranking import (
    PAGE_SIZE,
    TREND_WINDOW_SECONDS,
    Item,
    Preferences,
    Tab,
    counts_for_floor,
    percentile_75,
    rank_items,
)

_GENDER_ORDER = {"women": 0, "men": 1, "unisex": 2}


@dataclass(frozen=True)
class Profile:
    member_id: int
    username: str
    avatar_url: str | None


@dataclass(frozen=True)
class Session:
    username: str
    conocido: bool
    avatar_url: str | None
    member_id: int | None


@dataclass(frozen=True)
class Options:
    brands: tuple[str, ...]
    genders: tuple[str, ...]
    perfumers: tuple[str, ...]
    families: tuple[str, ...]


@dataclass(frozen=True)
class Recommendation:
    username: str
    conocido: bool
    avatar_url: str | None
    tab: Tab
    perfumes: list[Item]


class ModelUnavailable(RuntimeError):
    """«Para vos» se pidió sin el artefacto del two-stage cargado."""


class PersonalRanking(Protocol):
    """Top del modelo. Las notas de la sesión ya van en ``ratings``."""

    def rank(
        self,
        member_id: int | None,
        ratings: Sequence[tuple[int, int]],
        exclude: set[int],
    ) -> list[int]:
        """Ids en el orden del modelo, sin repetir ni devolver ``exclude``."""


class Catalog:
    def __init__(
        self,
        items: list[Item],
        profiles: Mapping[str, Profile],
        seen: Mapping[int, set[int]],
        recent_counts: Mapping[int, int] | None = None,
        personal: PersonalRanking | None = None,
    ) -> None:
        self.items = items
        self.profiles = dict(profiles)
        self.seen = seen
        self.recent_counts = dict(recent_counts or {})
        self.vote_floor = percentile_75(counts_for_floor(items))
        self.options = _options(items)
        self.personal = personal

    def session(self, username: str) -> Session:
        slug = username.strip().lower()
        profile = self.profiles.get(slug)
        if profile is None:
            return Session(username=slug, conocido=False, avatar_url=None, member_id=None)
        return Session(
            username=profile.username,
            conocido=True,
            avatar_url=profile.avatar_url,
            member_id=profile.member_id,
        )

    def recommend(
        self,
        username: str,
        tab: Tab,
        ratings: Iterable[int],
        preferences: Preferences,
        notas: Mapping[int, int] | None = None,
    ) -> Recommendation:
        found = self.session(username)
        exclude = set(ratings)
        if found.member_id is not None:
            exclude.update(self.seen.get(found.member_id, ()))
        if tab == "para_vos":
            perfumes = self._personal(found.member_id, exclude, notas or {})
        else:
            # La encuesta es solo para quien no está en el dataset.
            active = Preferences() if found.conocido else preferences
            perfumes = rank_items(
                self.items,
                tab,
                exclude=exclude,
                preferences=active,
                vote_floor=self.vote_floor,
                recent_counts=self.recent_counts,
            )
        return Recommendation(
            username=found.username,
            conocido=found.conocido,
            avatar_url=found.avatar_url,
            tab=tab,
            perfumes=perfumes,
        )

    def _personal(
        self,
        member_id: int | None,
        exclude: set[int],
        notas: Mapping[int, int],
    ) -> list[Item]:
        """Orden del two-stage. No aplica el piso de nota ni la encuesta."""

        if self.personal is None:
            raise ModelUnavailable(
                "El modelo todavía no está cargado. Falta artifacts/serving.joblib."
            )
        scored = [
            (perfume_id, int(notas[perfume_id]))
            for perfume_id in exclude
            if perfume_id in notas
        ]
        order = self.personal.rank(member_id, scored, exclude)
        by_id = {item.perfume_id: item for item in self.items}
        chosen: list[Item] = []
        seen: set[int] = set()
        for perfume_id in order:
            if perfume_id in exclude or perfume_id in seen or perfume_id not in by_id:
                continue
            seen.add(perfume_id)
            chosen.append(by_id[perfume_id])
            if len(chosen) == PAGE_SIZE:
                break
        return chosen


def data_dir() -> Path:
    raw = os.environ.get("FRAGRANTICA_DATA")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[3] / "scraper" / "data" / "final"


def load_catalog(directory: Path | None = None) -> Catalog:
    root = (directory or data_dir()).resolve()
    required = (
        "items.parquet",
        "users.parquet",
        "interactions.parquet",
        "wardrobe.parquet",
        "PRIVATE_user_mapping.parquet",
    )
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Faltan archivos en {root}: {', '.join(missing)}")

    con = duckdb.connect()
    try:
        items = _load_items(con, root / "items.parquet")
        profiles = _load_profiles(con, root)
        seen = _load_seen(con, root)
        recent_counts = _load_recent_counts(con, root / "interactions.parquet")
    finally:
        con.close()
    return Catalog(items, profiles, seen, recent_counts)


def _load_items(con: duckdb.DuckDBPyConnection, path: Path) -> list[Item]:
    rows = con.execute(
        """
        SELECT perfume_id, url, name, brand, gender, launch_year, olfactive_family,
               perfumers, rating_value, rating_count, image_url, description
        FROM read_parquet(?)
        """,
        [str(path)],
    ).fetchall()
    items: list[Item] = []
    for row in rows:
        (
            perfume_id,
            url,
            name,
            brand,
            gender,
            launch_year,
            family,
            perfumers,
            rating_value,
            rating_count,
            image_url,
            description,
        ) = row
        if perfume_id is None or rating_value is None or rating_count is None:
            continue
        items.append(
            Item(
                perfume_id=int(perfume_id),
                name=_text(name),
                brand=_text(brand),
                gender=_text(gender),
                olfactive_family=_text(family),
                perfumers=_perfumers(perfumers),
                launch_year=int(launch_year) if launch_year is not None else None,
                rating_value=float(rating_value),
                rating_count=int(rating_count),
                description=_text(description),
                image_url=_text(image_url),
                url=_text(url),
            )
        )
    return items


def _load_profiles(con: duckdb.DuckDBPyConnection, root: Path) -> dict[str, Profile]:
    avatars: dict[int, str | None] = {}
    for member_id, avatar_url in con.execute(
        "SELECT member_id, avatar_url FROM read_parquet(?)",
        [str(root / "users.parquet")],
    ).fetchall():
        if member_id is None:
            continue
        avatars[int(member_id)] = _text(avatar_url) or None

    profiles: dict[str, Profile] = {}
    for member_id, username in con.execute(
        "SELECT member_id, username_slug FROM read_parquet(?)",
        [str(root / "PRIVATE_user_mapping.parquet")],
    ).fetchall():
        if member_id is None or not username:
            continue
        slug = str(username).strip().lower()
        if not slug:
            continue
        member = int(member_id)
        profiles[slug] = Profile(
            member_id=member,
            username=slug,
            avatar_url=avatars.get(member),
        )
    return profiles


def _load_recent_counts(con: duckdb.DuckDBPyConnection, path: Path) -> dict[int, int]:
    """Interacciones por perfume en el año que termina en la fecha más nueva.

    Las filas sin timestamp no entran: no se puede saber si son recientes.
    """
    latest = con.execute(
        "SELECT max(timestamp) FROM read_parquet(?) WHERE timestamp IS NOT NULL",
        [str(path)],
    ).fetchone()
    if latest is None or latest[0] is None:
        return {}
    cutoff = int(latest[0]) - TREND_WINDOW_SECONDS
    counts: dict[int, int] = {}
    for perfume_id, total in con.execute(
        """
        SELECT perfume_id, count(*)
        FROM read_parquet(?)
        WHERE timestamp >= ?
        GROUP BY 1
        """,
        [str(path), cutoff],
    ).fetchall():
        if perfume_id is None:
            continue
        counts[int(perfume_id)] = int(total)
    return counts


def _load_seen(con: duckdb.DuckDBPyConnection, root: Path) -> dict[int, set[int]]:
    seen: dict[int, set[int]] = defaultdict(set)
    query = """
        SELECT member_id, perfume_id FROM read_parquet(?)
        UNION
        SELECT member_id, perfume_id FROM read_parquet(?)
    """
    cursor = con.execute(
        query,
        [str(root / "interactions.parquet"), str(root / "wardrobe.parquet")],
    )
    while True:
        batch = cursor.fetchmany(100_000)
        if not batch:
            break
        for member_id, perfume_id in batch:
            if member_id is None or perfume_id is None:
                continue
            seen[int(member_id)].add(int(perfume_id))
    return seen


def _options(items: Iterable[Item]) -> Options:
    brands: set[str] = set()
    genders: set[str] = set()
    perfumers: set[str] = set()
    family_counts: Counter[str] = Counter()
    for item in items:
        if item.brand:
            brands.add(item.brand)
        if item.gender:
            genders.add(item.gender)
        if item.olfactive_family:
            family_counts[item.olfactive_family] += 1
        perfumers.update(name for name in item.perfumers if name)
    # Unos pocos perfumes traen un fragmento de la descripción en vez de la
    # familia. Esos valores aparecen una sola vez; las familias reales, no.
    families = {name for name, count in family_counts.items() if count >= 2}
    return Options(
        brands=tuple(sorted(brands, key=str.casefold)),
        genders=tuple(sorted(genders, key=lambda gender: (_GENDER_ORDER.get(gender, 9), gender))),
        perfumers=tuple(sorted(perfumers, key=str.casefold)),
        families=tuple(sorted(families, key=str.casefold)),
    )


def _perfumers(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    data: object = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return ()
    if not isinstance(data, list):
        return ()
    return tuple(str(name) for name in data if isinstance(name, str) and name.strip())


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value)
