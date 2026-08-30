"""Wardrobe y votos sin review, a partir del JSON ya descifrado.

El HTML del perfil solo trae el conteo (`:wardrobe-count`) y un componente
Vue vacio (`<member-shelfs-modern type="wardrobe|myvotes">`). Los items viven
en `POST /ajax.php?user_shelves`. El parser no asume un esquema rigido: el
payload no se pudo congelar todavia (el sitio esta penalizando la IP), asi
que se recorre el JSON buscando objetos con `parfem_id` / `perfume_id`.

Clasificacion:
- contexto `myvotes` / `votes`, o un blob de votos con rating -> `source=vote`
- `have`/`had`/`want` o contexto wardrobe -> `source=wardrobe`
- estantes `custom` se ignoran: no son la coleccion ni el voto, y duplicarian
  senal si el usuario tambien los tiene en el wardrobe

`review_id` queda en None: estas filas no son reviews. El dedup de la fase 6
es por (member_id, perfume_id) y prefiere review > voto > wardrobe.
"""

from __future__ import annotations

from typing import Any, Iterator, Literal

from ..models import Interaction
from .votes import normalise_votes

_PID_KEYS = ("parfem_id", "perfume_id", "perfumeId")
_VOTE_HINTS = ("vote", "myvotes", "my_votes", "i_rated")
_WARDROBE_HINTS = ("wardrobe", "have", "had", "want", "shelf_wardrobe")
_SKIP_HINTS = ("custom",)


def parse_shelves(
    payload: Any,
    *,
    member_id: int,
    slug: str,
) -> list[Interaction]:
    out: list[Interaction] = []
    seen: set[tuple[str, int]] = set()
    for obj, kind in _walk(payload, None):
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
        if source == "wardrobe" and votes["relation"] == "unknown":
            rel = obj.get("relation") or obj.get("status") or obj.get("ownership")
            votes["relation"] = rel if rel in ("have", "had", "want") else "unknown"

        ts = obj.get("vrijeme") or obj.get("timestamp") or obj.get("time")
        timestamp = int(ts) if isinstance(ts, (int, float)) and ts > 0 else None

        out.append(
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
                source=source,
            )
        )
    return out


def _walk(obj: Any, kind: str | None) -> Iterator[tuple[dict, str | None]]:
    if isinstance(obj, dict):
        here = _kind_from_label(obj) or kind
        if _perfume_id(obj) is not None:
            yield obj, here
        for key, val in obj.items():
            child_kind = _kind_from_name(str(key)) or here
            yield from _walk(val, child_kind)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk(item, kind)


def _perfume_id(obj: dict) -> int | None:
    for key in _PID_KEYS:
        v = obj.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            continue
        try:
            pid = int(v)
        except (TypeError, ValueError):
            continue
        if pid > 0:
            return pid
    return None


def _kind_from_label(obj: dict) -> str | None:
    for key in ("type", "shelf", "shelf_type", "name", "id", "slug"):
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
    # Item con id y sin etiqueta: entra como wardrobe (feedback implicito).
    return "wardrobe"
