"""Wardrobe y votos sin review, a partir del JSON ya descifrado.

El HTML del perfil solo trae el conteo (`:wardrobe-count`) y un componente
Vue vacio. Los items viven en `POST /ajax.php?user_shelves`.

Esquema verificado (ajax 200, @bansheesmile): lista de estantes
`{type, field, value, name, perfumes:[{id, naslov, dizajner, url}]}`.
- type=wardrobe, field=relation, value=have|had|want -> WardrobeItem
- type=myvotes, field=rating, value=1..5 -> Interaction source=vote
- field=for_test (y custom) se ignoran: no son la coleccion ni el voto

El walker viejo (claves `parfem_id` anidadas) se conserva como fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Literal

from ..models import Interaction, WardrobeItem
from .votes import normalise_votes

_PID_KEYS = ("parfem_id", "perfume_id", "perfumeId")
_VOTE_HINTS = ("vote", "myvotes", "my_votes", "i_rated")
_WARDROBE_HINTS = ("wardrobe", "have", "had", "want", "shelf_wardrobe")
_SKIP_HINTS = ("custom", "for_test", "for test")


@dataclass
class ParsedShelves:
    votes: list[Interaction] = field(default_factory=list)
    wardrobe: list[WardrobeItem] = field(default_factory=list)


def parse_shelves(
    payload: Any,
    *,
    member_id: int,
    slug: str,
) -> ParsedShelves:
    out = ParsedShelves()
    seen: set[tuple[str, int]] = set()
    for obj, kind, ctx in _walk(payload, None, {}):
        if kind == "skip":
            continue
        pid = _perfume_id(obj)
        if pid is None:
            continue
        source = _classify(obj, kind)
        if source is None:
            continue
        key = (source, pid)
        if key in seen:
            continue
        seen.add(key)

        ts = obj.get("vrijeme") or obj.get("timestamp") or obj.get("time")
        timestamp = int(ts) if isinstance(ts, (int, float)) and ts > 0 else None

        if source == "wardrobe":
            rel = (
                obj.get("relation")
                or obj.get("status")
                or obj.get("ownership")
                or ctx.get("relation")
            )
            out.wardrobe.append(
                WardrobeItem(
                    member_id=member_id,
                    username_slug=slug,
                    perfume_id=pid,
                    relation=rel if rel in ("have", "had", "want") else "unknown",
                    timestamp=timestamp,
                )
            )
            continue

        raw_votes = obj.get("perfume_votes")
        if not isinstance(raw_votes, dict):
            raw_votes = {
                k: obj[k]
                for k in (
                    "rating", "winter", "spring", "summer", "autumn",
                    "day", "night", "longevity", "sillage", "gender", "relation",
                )
                if k in obj
            }
        votes = normalise_votes(raw_votes if raw_votes else None)
        if votes["rating"] is None and ctx.get("rating") is not None:
            votes["rating"] = ctx["rating"]
        out.votes.append(
            Interaction(
                review_id=None,
                perfume_id=pid,
                member_id=member_id,
                username_slug=slug,
                rating=votes["rating"],
                relation=votes["relation"],
                longevity=votes["longevity"],
                sillage=votes["sillage"],
                gender_vote=votes["gender"],
                season_winter=votes["winter"],
                season_spring=votes["spring"],
                season_summer=votes["summer"],
                season_autumn=votes["autumn"],
                day=votes["day"],
                night=votes["night"],
                timestamp=timestamp,
                review_text=None,
                source="vote",
            )
        )
    return out


def _walk(
    obj: Any,
    kind: str | None,
    ctx: dict[str, Any],
) -> Iterator[tuple[dict, str | None, dict[str, Any]]]:
    if isinstance(obj, dict):
        here = _kind_from_label(obj) or kind
        child_ctx = dict(ctx)
        field = str(obj.get("field") or "").lower()
        if field == "relation" and obj.get("value") in ("have", "had", "want"):
            child_ctx["relation"] = obj["value"]
        if field == "rating":
            try:
                rating = int(obj["value"])
            except (TypeError, ValueError, KeyError):
                rating = None
            if rating is not None and 1 <= rating <= 5:
                child_ctx["rating"] = rating
        if field in ("for_test", "custom") or _kind_from_name(str(obj.get("name") or "")) == "skip":
            here = "skip"
        if _perfume_id(obj) is not None:
            yield obj, here, child_ctx
        for key, val in obj.items():
            child_kind = _kind_from_name(str(key)) or here
            yield from _walk(val, child_kind, child_ctx)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk(item, kind, ctx)


def _perfume_id(obj: dict) -> int | None:
    for key in _PID_KEYS:
        pid = _as_positive_int(obj.get(key))
        if pid is not None:
            return pid
    # Ajax user_shelves: el item usa `id` (no parfem_id). Solo si parece perfume.
    if "naslov" in obj or "dizajner" in obj or (
        isinstance(obj.get("url"), str) and "/perfume/" in obj["url"]
    ):
        return _as_positive_int(obj.get("id"))
    return None


def _as_positive_int(v: object) -> int | None:
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return None
    try:
        pid = int(v)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _kind_from_label(obj: dict) -> str | None:
    for key in ("type", "shelf", "shelf_type", "name", "slug"):
        if key in obj:
            k = _kind_from_name(str(obj[key]))
            if k:
                return k
    return None


def _kind_from_name(name: str) -> str | None:
    n = name.lower()
    if any(h in n for h in _SKIP_HINTS):
        return "skip"
    if any(h in n for h in _VOTE_HINTS):
        return "vote"
    if any(h in n for h in _WARDROBE_HINTS):
        return "wardrobe"
    return None


def _classify(obj: dict, kind: str | None) -> Literal["wardrobe", "vote"] | None:
    if kind == "skip":
        return None
    if kind == "vote":
        return "vote"
    if kind == "wardrobe":
        return "wardrobe"
    votes = obj.get("perfume_votes") if isinstance(obj.get("perfume_votes"), dict) else obj
    rating = votes.get("rating") if isinstance(votes, dict) else None
    try:
        if rating is not None and int(rating) > 0:
            return "vote"
    except (TypeError, ValueError):
        pass
    rel = obj.get("relation") or obj.get("status")
    if rel in ("have", "had", "want"):
        return "wardrobe"
    return "wardrobe"
