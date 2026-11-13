"""Ranking de popularidad y de mejor puntaje, sin modelo.

El voto de Fragrantica es 1–5 (odio, disgusto, ok, me gusta, me encanta).
Entran perfumes con promedio de al menos 3, o sea ok.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

MIN_RATING = 3.0
PAGE_SIZE = 20
# Ventana móvil desde la interacción fechada más nueva del dataset.
TREND_WINDOW_SECONDS = 365 * 24 * 60 * 60
Tab = Literal["populares", "mejor_puntuados", "trending"]


@dataclass(frozen=True)
class Item:
    perfume_id: int
    name: str
    brand: str
    gender: str
    olfactive_family: str
    perfumers: tuple[str, ...]
    launch_year: int | None
    rating_value: float
    rating_count: int
    description: str
    image_url: str
    url: str


@dataclass(frozen=True)
class Preferences:
    """Filtros de la encuesta. Vacío en una dimensión significa no filtrar.

    Dentro de cada dimensión alcanza con coincidir con cualquiera.
    Entre dimensiones se cumplen todas las que tengan alguna elección.
    """

    brands: frozenset[str] = field(default_factory=frozenset)
    genders: frozenset[str] = field(default_factory=frozenset)
    perfumers: frozenset[str] = field(default_factory=frozenset)
    families: frozenset[str] = field(default_factory=frozenset)

    def matches(self, item: Item) -> bool:
        if self.brands and item.brand not in self.brands:
            return False
        if self.genders and item.gender not in self.genders:
            return False
        if self.perfumers and self.perfumers.isdisjoint(item.perfumers):
            return False
        if self.families and item.olfactive_family not in self.families:
            return False
        return True


def percentile_75(values: Sequence[int]) -> float:
    """Percentil 75 con interpolación lineal: posición (n - 1) * 0.75."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * 0.75
    low = int(position)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[low + 1] * weight


def counts_for_floor(items: Sequence[Item]) -> list[int]:
    """Votos que definen el piso: solo perfumes con rating de al menos ok."""
    return [item.rating_count for item in items if item.rating_value >= MIN_RATING]


def rank_items(
    items: Sequence[Item],
    tab: Tab,
    *,
    exclude: set[int],
    preferences: Preferences,
    vote_floor: float,
    recent_counts: Mapping[int, int] | None = None,
    limit: int = PAGE_SIZE,
) -> list[Item]:
    """Devuelve hasta `limit` perfumes. Si hay menos, devuelve los que haya.

    `vote_floor` es el del catálogo completo. No se recalcula sobre el
    subconjunto que deja la encuesta. `recent_counts` son interacciones
    fechadas dentro del último año; sin fecha no cuentan como tendencia.
    """
    counts = recent_counts or {}
    pool = [
        item
        for item in items
        if item.rating_value >= MIN_RATING
        and item.perfume_id not in exclude
        and preferences.matches(item)
    ]
    if tab == "mejor_puntuados":
        pool = [item for item in pool if item.rating_count >= vote_floor]
        pool.sort(key=lambda item: (-item.rating_value, -item.rating_count, item.perfume_id))
    elif tab == "trending":
        pool = [item for item in pool if counts.get(item.perfume_id, 0) > 0]
        pool.sort(
            key=lambda item: (-counts[item.perfume_id], -item.rating_value, item.perfume_id)
        )
    else:
        pool.sort(key=lambda item: (-item.rating_count, -item.rating_value, item.perfume_id))
    return pool[:limit]
