"""Adaptador del two-stage a los ids enteros de la API."""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from fragrantica_serving.catalog import Catalog

LOGGER = logging.getLogger("uvicorn.error")


def model_path() -> Path:
    """``FRAGRANTICA_MODEL`` o el ``serving.joblib`` del recomendador."""

    raw = os.environ.get("FRAGRANTICA_MODEL")
    if raw:
        return Path(raw)
    return (
        Path(__file__).resolve().parents[3]
        / "recommendation-system"
        / "artifacts"
        / "serving.joblib"
    )


def attach_model(catalog: Catalog, directory: Path) -> None:
    """Carga el artefacto si existe. Sin archivo, «Para vos» responde 503."""

    path = model_path()
    if not path.is_file():
        LOGGER.warning("Sin modelo en %s. «Para vos» no va a responder.", path)
        return
    _ensure_recommender_path()
    from fragrantica_rec.serving import load_serving_index

    LOGGER.info("Cargando modelo %s", path)
    started = time.perf_counter()
    catalog.personal = ModelRanking(load_serving_index(path, directory))
    LOGGER.info("Modelo listo en %.1f s", time.perf_counter() - started)


class ModelRanking:
    """Historial guardado más las notas de la sesión, en cada request."""

    def __init__(self, index: object) -> None:
        self.index = index

    def rank(
        self,
        member_id: int | None,
        ratings: Sequence[tuple[int, int]],
        exclude: set[int],
    ) -> list[int]:
        user_id = str(member_id) if member_id is not None else "nuevo"
        catalog_ids = self.index.catalog_ids
        scored = [
            (str(perfume_id), int(rating))
            for perfume_id, rating in ratings
            if str(perfume_id) in catalog_ids
        ]
        ordered = self.index.recommend(
            user_id,
            scored,
            extra_seen={str(perfume_id) for perfume_id in exclude},
        )
        chosen: list[int] = []
        for item_id in ordered:
            try:
                perfume_id = int(item_id)
            except (TypeError, ValueError):
                continue
            if perfume_id in exclude:
                continue
            chosen.append(perfume_id)
        return chosen


def _ensure_recommender_path() -> None:
    """El paquete vive al lado de la API. El editable install también lo resuelve."""

    root = Path(__file__).resolve().parents[3] / "recommendation-system"
    text = str(root)
    if text not in sys.path:
        sys.path.insert(0, text)
