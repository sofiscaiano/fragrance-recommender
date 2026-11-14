"""Inferencia por request: la sesión entra al historial y se vuelve a rankear."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from fragrantica_rec.config import PipelineConfig, RankerConfig
from fragrantica_rec.data import ITEM_COL, RATING_COL, USER_COL, observed_catalog
from fragrantica_rec.serving import (
    ServingModel,
    build_request_history,
    export_serving_artifact,
    recommend_user,
)
from fragrantica_rec.two_stage.columns import ColumnBuilder, attach_relevance
from fragrantica_rec.two_stage.ranker import LambdaRanker
from fragrantica_rec.two_stage.retrieval import (
    CandidateFusion,
    build_default_retrievers,
    fit_retrievers,
    per_source_depth,
)


def _catalog(perfumes: list[str]) -> pd.DataFrame:
    brands = ["Chanel", "Dior", "Guerlain"]
    families = ["Floral", "Woody", "Oriental"]
    return pd.DataFrame(
        {
            ITEM_COL: perfumes,
            "name": [f"Perfume {item}" for item in perfumes],
            "brand": [brands[index % 3] for index in range(len(perfumes))],
            "gender": ["women" if index % 2 == 0 else "men" for index in range(len(perfumes))],
            "olfactive_family": [families[index % 3] for index in range(len(perfumes))],
            "launch_year": [2000 + (index % 10) for index in range(len(perfumes))],
            "perfumers": ["Alberto Morillas"] * len(perfumes),
            "accords": ["floral"] * len(perfumes),
            "notes": ["rosa"] * len(perfumes),
            "description": [
                "floral aldehydico" if index % 2 == 0 else "madera seca"
                for index in range(len(perfumes))
            ],
        }
    )


def _interactions(perfumes: list[str]) -> pd.DataFrame:
    rows = []
    for index, perfume in enumerate(perfumes):
        if index < 4:
            user = "u1"
            rating = 5
        elif index < 8:
            user = "u2"
            rating = 4
        else:
            user = "u3" if index % 2 == 0 else "u4"
            rating = 3
        rows.append((user, perfume, f"2020-01-{(index % 27) + 1:02d}", rating))
    frame = pd.DataFrame(rows, columns=[USER_COL, ITEM_COL, "timestamp", RATING_COL])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    return frame


def _fit_ranker(model: ServingModel, interactions: pd.DataFrame) -> LambdaRanker:
    users = tuple(interactions[USER_COL].unique())
    depth = per_source_depth(
        model.rrf_cutoff,
        rrf_k=model.rrf_k,
        n_sources=len(model.retrievers),
    )
    frames = [
        retriever.recommend(users, interactions, depth) for retriever in model.retrievers
    ]
    frames = [frame for frame in frames if not frame.empty]
    candidates = pd.concat(frames, ignore_index=True)
    fusion = CandidateFusion(weights=model.weights, rrf_k=model.rrf_k)
    fused = fusion.fuse(candidates, model.rrf_cutoff)
    features = model.feature_builder.transform(fused.candidates, fused.source_candidates)
    target = (
        fused.candidates.groupby(USER_COL, sort=False).head(1)[[USER_COL, ITEM_COL]].copy()
    )
    target[RATING_COL] = 5
    labeled = attach_relevance(features, target)
    return LambdaRanker(
        RankerConfig(
            n_estimators=15,
            early_stopping_rounds=5,
            min_child_samples=1,
            num_leaves=7,
        )
    ).fit(labeled, labeled)


@pytest.fixture(scope="module")
def fitted() -> tuple[ServingModel, pd.DataFrame, list[str]]:
    perfumes = [f"p{index:02d}" for index in range(30)]
    interactions = _interactions(perfumes)
    observed = observed_catalog(interactions, _catalog(perfumes))
    retrievers = build_default_retrievers(
        enabled=("popularidad", "item_cosine", "als", "bpr", "tfidf"),
        item_cosine=SimpleNamespace(half_life_days=365.0),
        als=SimpleNamespace(factors=4, iterations=2, regularization=0.1, half_life_days=365.0),
        bpr=SimpleNamespace(
            factors=4,
            iterations=2,
            learning_rate=0.01,
            regularization=0.01,
            half_life_days=365.0,
        ),
        tfidf=SimpleNamespace(max_features=40, half_life_days=365.0),
    )
    fitted_sources = fit_retrievers(retrievers, interactions, observed)
    builder = ColumnBuilder().fit(interactions, observed)
    model = ServingModel(
        ranker=LambdaRanker(),
        retrievers=fitted_sources,
        feature_builder=builder,
        weights={retriever.source_name: 1.0 for retriever in fitted_sources},
        rrf_cutoff=20,
        rrf_k=60.0,
    )
    model.ranker = _fit_ranker(model, interactions)
    return model, interactions, perfumes


def test_export_serving_exige_el_ranker_evaluado(tmp_path: Path) -> None:
    config = PipelineConfig(data_dir=tmp_path, artifacts_dir=tmp_path)
    with pytest.raises(FileNotFoundError, match="evaluate"):
        export_serving_artifact(config)


def test_usuario_conocido_no_repide_lo_visto(
    fitted: tuple[ServingModel, pd.DataFrame, list[str]],
) -> None:
    model, interactions, _perfumes = fitted
    history = interactions.loc[interactions[USER_COL] == "u1"]
    seen = set(history[ITEM_COL])
    before = model.feature_builder.user_stats_.copy()
    recommended = recommend_user(model, "u1", history)

    assert len(recommended) == 10
    assert len(set(recommended)) == 10
    assert set(recommended).isdisjoint(seen)
    assert model.feature_builder.user_stats_.equals(before)


def test_la_sesion_reemplaza_la_nota_y_saca_el_perfume(
    fitted: tuple[ServingModel, pd.DataFrame, list[str]],
) -> None:
    model, interactions, _perfumes = fitted
    stored = interactions.loc[interactions[USER_COL] == "u1"].copy()
    history = build_request_history(stored, "u1", [("p00", 1), ("p10", 5)])

    replaced = history.loc[history[ITEM_COL] == "p00"]
    assert len(replaced) == 1
    assert int(replaced[RATING_COL].iloc[0]) == 1
    assert history.loc[history[ITEM_COL] == "p10", "timestamp"].iloc[0] == history["timestamp"].max()
    recommended = recommend_user(model, "u1", history)
    assert set(recommended).isdisjoint({"p00", "p10"})


def test_usuario_nuevo_con_notas_no_devuelve_lo_puntuado(
    fitted: tuple[ServingModel, pd.DataFrame, list[str]],
) -> None:
    model, _interactions, perfumes = fitted
    empty = pd.DataFrame(columns=[USER_COL, ITEM_COL, "timestamp", RATING_COL])
    empty["timestamp"] = pd.to_datetime(empty["timestamp"])
    history = build_request_history(empty, "nuevo", [("p00", 5), ("p01", 4)])
    recommended = recommend_user(model, "nuevo", history)

    assert len(recommended) == 10
    assert set(recommended) <= set(perfumes)
    assert set(recommended).isdisjoint({"p00", "p01"})
