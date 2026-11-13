"""Inferencia de un usuario con las fuentes ya ajustadas.

El ranker sale de ``evaluated_pipeline.joblib``: es el LambdaRank de la
corrida de evaluación, entrenado sin las últimas 10 reviews. Esas reviews ya
ocurrieron, así que las fuentes y el builder se ajustan sobre todo el
historial. Cada request agrega las notas de la sesión a ese historial y
vuelve a rankear. No reentrena LambdaRank ni las fuentes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from .baselines import PopularityRecommender
from .config import PipelineConfig
from .data import (
    DATE_COL,
    ITEM_COL,
    RATING_COL,
    USER_COL,
    load_dataset,
    observed_catalog,
)
from .two_stage.columns import ColumnBuilder
from .two_stage.ranker import LambdaRanker
from .two_stage.retrieval import (
    CANDIDATE_COLUMNS,
    CandidateFusion,
    ImplicitMFRetriever,
    fit_retrievers,
    per_source_depth,
    retrievers_from_config,
)

LOGGER = logging.getLogger(__name__)

SERVING_FILENAME = "serving.joblib"
EVALUATED_FILENAME = "evaluated_pipeline.joblib"
TOP_N = 20


@dataclass
class ServingModel:
    """Ranker, fuentes y builder listos para puntuar sin volver a ajustar."""

    ranker: LambdaRanker
    retrievers: list[Any]
    feature_builder: ColumnBuilder
    weights: dict[str, float]
    rrf_cutoff: int
    rrf_k: float


def export_serving_artifact(
    config: PipelineConfig,
    *,
    pipeline_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """Ajusta las fuentes sobre toda la historia y guarda ``serving.joblib``."""

    artifacts = Path(config.artifacts_dir)
    pipeline = Path(pipeline_path or artifacts / EVALUATED_FILENAME)
    if not pipeline.is_file():
        raise FileNotFoundError(
            f"No existe {pipeline}. Corré evaluate antes de export-serving."
        )

    trained = joblib.load(pipeline)
    bundle = load_dataset(config.data_dir)
    interactions = bundle.interactions
    catalog = observed_catalog(interactions, bundle.books)
    LOGGER.info(
        "Ajustando fuentes de serving sobre %s interacciones",
        len(interactions),
    )
    retrievers = fit_retrievers(
        retrievers_from_config(config),
        interactions,
        catalog,
    )
    builder = ColumnBuilder().fit(interactions, catalog, bundle.readers)
    model = ServingModel(
        ranker=trained.ranker,
        retrievers=retrievers,
        feature_builder=builder,
        weights=dict(trained.weights),
        rrf_cutoff=int(trained.rrf_cutoff),
        rrf_k=float(config.retrieval.rrf_k),
    )
    destination = Path(output_path or artifacts / SERVING_FILENAME)
    destination.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, destination)
    LOGGER.info("Artefacto de serving guardado en %s", destination)
    return destination


def load_serving_model(path: str | Path) -> ServingModel:
    """Lee el artefacto exportado y deja listo el two-tower, si está."""

    model = joblib.load(path)
    if not isinstance(model, ServingModel):
        raise TypeError(f"{path} no contiene un ServingModel")
    for retriever in model.retrievers:
        warm = getattr(retriever, "warm", None)
        if warm is not None:
            warm()
    return model


@dataclass
class ServingIndex:
    """Modelo en memoria e historial por usuario de la matriz."""

    model: ServingModel
    history: dict[str, pd.DataFrame]
    catalog_ids: set[str]

    def recommend(
        self,
        user_id: str,
        ratings: list[tuple[str, int]],
        *,
        extra_seen: set[str] | None = None,
    ) -> list[str]:
        """Top del usuario. La sesión reemplaza notas del historial y queda última."""

        stored = self.history.get(str(user_id), _empty_history())
        usable = [
            (item_id, rating)
            for item_id, rating in ratings
            if item_id in self.catalog_ids
        ]
        history = build_request_history(stored, str(user_id), usable)
        return recommend_user(
            self.model,
            str(user_id),
            history,
            extra_seen=extra_seen,
        )


def load_serving_index(artifact: str | Path, data_dir: str | Path) -> ServingIndex:
    """Carga el joblib y el historial una vez, al prender el proceso."""

    model = load_serving_model(artifact)
    bundle = load_dataset(data_dir)
    history_frame = bundle.interactions[[USER_COL, ITEM_COL, DATE_COL, RATING_COL]]
    history = {
        str(user): frame.reset_index(drop=True)
        for user, frame in history_frame.groupby(USER_COL, sort=False)
    }
    catalog_ids = set(bundle.books[ITEM_COL].astype(str))
    LOGGER.info(
        "Serving listo: %s perfumes, %s usuarios con historial",
        len(catalog_ids),
        len(history),
    )
    return ServingIndex(model=model, history=history, catalog_ids=catalog_ids)


def build_request_history(
    stored: pd.DataFrame,
    user_id: str,
    ratings: list[tuple[str, int]],
) -> pd.DataFrame:
    """Historial de la base más la sesión. La sesión reemplaza y queda última."""

    columns = [USER_COL, ITEM_COL, DATE_COL, RATING_COL]
    if stored.empty:
        base = _empty_history()
    else:
        base = stored.loc[stored[USER_COL].astype(str) == user_id, columns].copy()
        base[DATE_COL] = pd.to_datetime(base[DATE_COL])
        base[RATING_COL] = pd.to_numeric(base[RATING_COL]).astype("int8")
    if not ratings:
        return base.reset_index(drop=True)

    if base.empty or base[DATE_COL].isna().all():
        start = pd.Timestamp("2026-01-01")
    else:
        start = pd.Timestamp(base[DATE_COL].max())
    rows = [
        {
            USER_COL: user_id,
            ITEM_COL: item_id,
            DATE_COL: start + pd.Timedelta(days=offset),
            RATING_COL: rating,
        }
        for offset, (item_id, rating) in enumerate(ratings, start=1)
    ]
    session = pd.DataFrame(rows, columns=columns)
    session[RATING_COL] = session[RATING_COL].astype("int8")
    session[DATE_COL] = pd.to_datetime(session[DATE_COL])
    if not base.empty:
        base = base.loc[~base[ITEM_COL].astype(str).isin(session[ITEM_COL])].copy()
    return pd.concat([base, session], ignore_index=True)


def recommend_user(
    model: ServingModel,
    user_id: str,
    history: pd.DataFrame,
    *,
    extra_seen: set[str] | None = None,
    n: int = TOP_N,
) -> list[str]:
    """Hasta ``n`` perfumes. No ajusta fuentes ni escribe el builder."""

    if n < 1:
        raise ValueError("n debe ser positivo")
    user_id = str(user_id)
    profile = _profile(history, user_id)
    blocked = set(profile[ITEM_COL].astype(str)) | {str(item) for item in (extra_seen or ())}
    per_source = per_source_depth(
        model.rrf_cutoff,
        rrf_k=model.rrf_k,
        n_sources=len(model.retrievers),
    )
    frames = _source_frames(model.retrievers, user_id, profile, per_source)
    frames = [frame for frame in frames if not frame.empty]
    if frames:
        candidates = pd.concat(frames, ignore_index=True)
    else:
        candidates = pd.DataFrame(columns=CANDIDATE_COLUMNS)

    fusion = CandidateFusion(weights=model.weights, rrf_k=model.rrf_k)
    fused = fusion.fuse(candidates, model.rrf_cutoff)
    chosen: list[str] = []
    if not fused.candidates.empty:
        features = _builder_for_request(model.feature_builder, profile).transform(
            fused.candidates,
            fused.source_candidates,
        )
        _ensure_ranker_columns(features.frame, model.ranker.feature_columns_)
        ranked = model.ranker.predict(features)
        for item_id in ranked[ITEM_COL].astype(str):
            if item_id in blocked or item_id in chosen:
                continue
            chosen.append(item_id)
            if len(chosen) == n:
                break

    if len(chosen) < n:
        chosen = _fill_with_popularity(
            model,
            user_id,
            blocked | set(chosen),
            chosen,
            n,
        )
    return chosen


def _empty_history() -> pd.DataFrame:
    """Historial vacío con las columnas y los tipos del resto del pipeline."""

    return pd.DataFrame(
        {
            USER_COL: pd.Series(dtype="str"),
            ITEM_COL: pd.Series(dtype="str"),
            DATE_COL: pd.Series(dtype="datetime64[ns]"),
            RATING_COL: pd.Series(dtype="int8"),
        }
    )


def _profile(history: pd.DataFrame, user_id: str) -> pd.DataFrame:
    """Filas de un usuario, con fecha y rating ya tipados."""

    columns = [USER_COL, ITEM_COL, DATE_COL, RATING_COL]
    if history.empty:
        return _empty_history()
    profile = history.loc[history[USER_COL].astype(str) == user_id, columns].copy()
    if profile.empty:
        return _empty_history()
    profile[DATE_COL] = pd.to_datetime(profile[DATE_COL])
    profile[RATING_COL] = pd.to_numeric(profile[RATING_COL]).astype("int8")
    return profile.reset_index(drop=True)


def _source_frames(
    retrievers: list[Any],
    user_id: str,
    history: pd.DataFrame,
    n: int,
) -> list[pd.DataFrame]:
    """Pide cada fuente en este hilo.

    El two-tower vive en otro proceso. Llamarlo desde un pool de hilos deja
    el pedido colgado en macOS: el hijo no llega a leer la cola.
    """

    return [_recommend_source(retriever, user_id, history, n) for retriever in retrievers]


def _recommend_source(
    retriever: Any,
    user_id: str,
    history: pd.DataFrame,
    n: int,
) -> pd.DataFrame:
    """Candidatos de una fuente con el historial de este pedido.

    ALS recalcula el factor. BPR lo corre hacia las notas nuevas. El resto
    arma el perfil con ese historial.
    """

    if isinstance(retriever, ImplicitMFRetriever) and retriever.algorithm == "als":
        return retriever.recommend_fold_in(user_id, history, n)
    if isinstance(retriever, ImplicitMFRetriever) and retriever.algorithm == "bpr":
        return retriever.recommend_with_history(user_id, history, n)
    return retriever.recommend([user_id], history, n)


def _builder_for_request(
    builder: ColumnBuilder,
    history: pd.DataFrame,
) -> ColumnBuilder:
    """Copia superficial: las tablas de usuario son nuevas, el resto se comparte."""

    clone = ColumnBuilder(recent_n=builder.recent_n, smoothing=builder.smoothing)
    clone.__dict__ = dict(builder.__dict__)
    frames = builder.user_frames_for(history)
    clone.user_stats_ = frames["user_stats"]
    clone.user_author_ = frames["user_author"]
    clone.user_genre_ = frames["user_genre"]
    clone.user_last_ = frames["user_last"]
    clone.user_recent_author_ = frames["user_recent_author"]
    clone.user_recent_genre_ = frames["user_recent_genre"]
    return clone


def _ensure_ranker_columns(frame: pd.DataFrame, columns: tuple[str, ...]) -> None:
    """Rellena con NaN las features que el ranker espera y este request no trae."""

    for column in columns:
        if column not in frame:
            frame[column] = np.nan


def _fill_with_popularity(
    model: ServingModel,
    user_id: str,
    blocked: set[str],
    chosen: list[str],
    n: int,
) -> list[str]:
    """Completa el top con popularidad, sin repetir ni devolver lo ya bloqueado."""

    popularity = _popularity(model)
    blocker = pd.DataFrame({USER_COL: user_id, ITEM_COL: list(blocked)})
    extra = popularity.recommend([user_id], blocker, n)
    for item_id in extra[ITEM_COL].astype(str):
        if item_id in blocked or item_id in chosen:
            continue
        chosen.append(item_id)
        if len(chosen) == n:
            break
    return chosen


def _popularity(model: ServingModel) -> PopularityRecommender:
    """Fuente de popularidad guardada en el artefacto."""

    for retriever in model.retrievers:
        if isinstance(retriever, PopularityRecommender):
            return retriever
    raise RuntimeError("El artefacto no incluye la fuente de popularidad")
