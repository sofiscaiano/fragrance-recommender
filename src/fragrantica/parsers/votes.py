"""Normalizacion del blob de votos que acompana a cada review.

El blob crudo se ve asi:

    {"rating":4,"winter":1,"spring":1,"summer":1,"autumn":1,"day":1,
     "night":1,"longevity":3,"sillage":2,"gender":null,"relation":"had"}

Hay una trampa importante verificada en los datos: **0 significa "no voto", no
el valor cero**. En la pagina de Sauvage, las 51 reviews con rating=0 tienen
ademas longevity=0, sillage=0 y todas las estaciones en 0; son usuarios que
escribieron texto sin votar nada.

Si se dejara pasar, un rating=0 entraria al recomendador como la peor
calificacion posible en vez de como un dato ausente. Eso sesgaria a la baja
todas las medias de item y de usuario, ademas de inventar senal negativa que
nunca existio.

La semantica no es uniforme entre campos:

- `rating`, `longevity`, `sillage`  ->  escalas 1-5: el 0 es ausencia -> None
- `winter`/`spring`/`summer`/`autumn`/`day`/`night`  ->  flags binarios: el 0 SI
  significa "no lo eligio"... pero solo si el usuario voto algo. Si no voto
  nada, esos ceros son ausencia y tambien van a None.
- `gender` -> ya viene null cuando no hay voto
"""

from __future__ import annotations

from typing import Any

from ..models import Relation

# Escalas ordinales 1-5: el 0 es "sin voto".
_ORDINAL_FIELDS = ("rating", "longevity", "sillage")

# Flags binarios 0/1 de contexto.
_BINARY_FIELDS = ("winter", "spring", "summer", "autumn", "day", "night")


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = int(value)
    return v if -10 <= v <= 10 else None


def cast_no_votes(blob: dict[str, Any]) -> bool:
    """True si el usuario no voto ninguna dimension.

    En ese caso los ceros del blob son ausencia de dato, no valores.
    """
    for field in _ORDINAL_FIELDS + _BINARY_FIELDS:
        if (_as_int(blob.get(field)) or 0) != 0:
            return False
    return blob.get("gender") is None


def normalise_relation(raw: Any) -> Relation:
    if raw in ("have", "had", "want"):
        return raw  # type: ignore[return-value]
    return "unknown"


def normalise_votes(blob: dict[str, Any] | None) -> dict[str, Any]:
    """Devuelve los campos de voto listos para el modelo Interaction."""
    blob = blob or {}
    voted = not cast_no_votes(blob)

    out: dict[str, Any] = {"relation": normalise_relation(blob.get("relation"))}

    for field in _ORDINAL_FIELDS:
        v = _as_int(blob.get(field))
        # 0 nunca es un valor valido en una escala 1-5.
        out[field] = v if (v is not None and v > 0) else None

    for field in _BINARY_FIELDS:
        v = _as_int(blob.get(field))
        out[field] = v if (voted and v is not None) else None

    out["gender"] = _as_int(blob.get("gender"))
    return out
