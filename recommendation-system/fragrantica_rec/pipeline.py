"""Orquestación end-to-end del recomendador en dos etapas."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from .baselines import PopularityRecommender
from .config import PipelineConfig
from .data import ITEM_COL, USER_COL, observed_catalog
from .metrics import (
    ndcg_at_k,
    ndcg_per_user,
    retrieval_hits,
    retrieval_metrics,
    rows_against_reference,
)
from .split_data import (
    SplitData,
    example_users,
    load_split,
    validation_folds,
)
from .tuning import (
    record_tuned_hyperparameters,
    require_tuned_hyperparameters,
    restrict_to_example_users,
    tune_pipeline,
)
from .two_stage.columns import ColumnBuilder, RankerTable, attach_relevance
from .two_stage.ranker import LambdaRanker
from .two_stage.retrieval import (
    CandidateFusion,
    FusionResult,
    fit_retrievers,
    per_source_depth,
    retrieve_all,
    retrievers_from_config,
)

LOGGER = logging.getLogger(__name__)

_TWO_STAGE_DIAGNOSTICS = (
    "retrieval_folds.csv",
    "feature_ablations.csv",
    "feature_importance.csv",
    "evaluated_pipeline.joblib",
    "final_pipeline.joblib",
)


def clear_foreign_diagnostics(artifacts: Path, model: str) -> None:
    """Quita diagnósticos de two_stage cuando corre otro modelo.

    No borra ``tuned_hyperparameters.json`` ni ``tuning_history.json``:
    two_stage vuelve a buscar ahí un tuneo de la misma config.
    """

    if model == "two_stage":
        return
    directory = Path(artifacts)
    for name in _TWO_STAGE_DIAGNOSTICS:
        path = directory / name
        if path.is_file():
            path.unlink()


@dataclass(frozen=True)
class FoldMaterial:
    """Artefactos previos a la fusión para un fold."""

    fold: int
    train: pd.DataFrame
    target: pd.DataFrame
    catalog: pd.DataFrame
    source_candidates: pd.DataFrame
    feature_builder: ColumnBuilder


@dataclass(frozen=True)
class EvaluationReport:
    """Métricas del hold-out que se comparan entre corridas."""

    model_ndcg_at_10: float
    baseline_ndcg_at_10: float
    retrieval_recall: float
    retrieval_oracle_ndcg_at_10: float
    candidate_budget: int
    evaluation_users: int


@dataclass
class TrainedPipeline:
    """Componentes necesarios para puntuar un fold o el catálogo final."""

    ranker: LambdaRanker
    weights: dict[str, float]
    rrf_cutoff: int
    fold_metrics: list[dict[str, float]]
    ablation_metrics: list[dict[str, object]]
    hyperparameters_origin: str = "default"
    hyperparameters_run_name: str = ""


def _collect_material(
    train: pd.DataFrame,
    target: pd.DataFrame,
    users: tuple[str, ...],
    books: pd.DataFrame,
    config: PipelineConfig,
    fold: int,
    per_source: int,
    readers: pd.DataFrame | None = None,
) -> FoldMaterial:
    """Entrena las fuentes y el builder de un fold, sin fusionar todavía."""

    LOGGER.info(
        "Entrenando retrievers del fold %s para %s usuarios",
        fold,
        len(users),
    )
    catalog = observed_catalog(train, books)
    retrievers = fit_retrievers(retrievers_from_config(config), train, catalog)
    source_candidates = retrieve_all(
        retrievers,
        users,
        train,
        per_source=per_source,
    )
    builder = ColumnBuilder().fit(train, catalog, readers)
    return FoldMaterial(
        fold=fold,
        train=train,
        target=target,
        catalog=catalog,
        source_candidates=source_candidates,
        feature_builder=builder,
    )


def _active_source_names(config: PipelineConfig) -> tuple[str, ...]:
    """Nombres de las fuentes que esta corrida entrena."""

    return config.retrieval.enabled_sources()


def _weights_for_active_sources(
    weights: dict[str, float],
    config: PipelineConfig,
) -> dict[str, float]:
    """Descarta pesos de fuentes que el pipeline ya no entrena."""

    active = set(_active_source_names(config))
    missing = sorted(active - set(weights))
    if missing:
        raise ValueError(
            f"No hay peso para {', '.join(missing)}: la fusión la ignoraría. "
            "Corré evaluate --tune con estas fuentes."
        )
    kept = {source: weight for source, weight in weights.items() if source in active}
    dropped = sorted(set(weights) - active)
    if dropped:
        LOGGER.info(
            "Se ignoran pesos de fuentes inactivas: %s",
            ", ".join(dropped),
        )
    if not kept:
        raise ValueError("No hay pesos para las fuentes activas")
    return kept


def _material_to_features(
    material: FoldMaterial,
    fusion: CandidateFusion,
    cutoff: int,
) -> tuple[RankerTable, FusionResult]:
    """Fusiona candidatos, arma features y les pone la relevancia del target."""

    fused = fusion.fuse(material.source_candidates, cutoff)
    features = material.feature_builder.transform(
        fused.candidates,
        fused.source_candidates,
    )
    labeled = attach_relevance(
        features,
        material.target,
        query_suffix=f"__fold_{material.fold}",
    )
    return labeled, fused


def _concat_feature_sets(sets: list[RankerTable]) -> RankerTable:
    """Apila folds y rellena con NaN las columnas que faltan en alguno."""

    if not sets:
        raise ValueError("No hay folds de features para concatenar")
    feature_columns = tuple(
        sorted({column for feature_set in sets for column in feature_set.feature_columns})
    )
    frames = []
    for feature_set in sets:
        frame = feature_set.frame.copy()
        for column in feature_columns:
            if column not in frame:
                frame[column] = np.nan
        frames.append(frame)
    return RankerTable(
        frame=pd.concat(frames, ignore_index=True, sort=False),
        feature_columns=feature_columns,
    )


def train_ranker_from_history(
    interactions: pd.DataFrame,
    books: pd.DataFrame,
    config: PipelineConfig,
    *,
    readers: pd.DataFrame | None = None,
    tune: bool = False,
    execute_ablations: bool = True,
) -> TrainedPipeline:
    """Entrena LambdaRank exclusivamente con pseudo-futuros rolling."""

    if tune:
        saved = None
        hyperparameters_origin = "tune"
        from .tracking import active_run_name

        hyperparameters_run_name = active_run_name()
        depth_cutoff = int(config.retrieval.search.rrf_cutoff.high)
    else:
        saved = require_tuned_hyperparameters(config)
        hyperparameters_origin = "saved"
        hyperparameters_run_name = saved.run_name
        depth_cutoff = saved.rrf_cutoff

    folds = validation_folds(interactions, config)
    if len(folds) < 2:
        raise ValueError("Se requieren al menos dos folds rolling para entrenar")
    per_source = per_source_depth(
        depth_cutoff,
        rrf_k=config.retrieval.rrf_k,
        n_sources=len(retrievers_from_config(config)),
    )
    materials = [
        _collect_material(
            fold.train,
            fold.target,
            fold.query_users,
            books,
            config,
            fold.fold,
            per_source,
            readers,
        )
        for fold in folds
    ]

    overrides: dict[str, Any] = {}
    if tune:
        selection = tune_pipeline(materials, config)
        fusion = CandidateFusion(
            weights=selection.weights,
            rrf_k=config.retrieval.rrf_k,
        )
        cutoff = selection.rrf_cutoff
        overrides = selection.ranker
    else:
        assert saved is not None
        fusion = CandidateFusion(
            weights=_weights_for_active_sources(saved.weights, config),
            rrf_k=config.retrieval.rrf_k,
        )
        cutoff = saved.rrf_cutoff
        overrides = dict(saved.ranker)
    weights = dict(fusion.weights)

    built = [_material_to_features(material, fusion, cutoff) for material in materials]
    LOGGER.info("Candidatos fusionados; entrenando LambdaRank")
    feature_sets = [features for features, _ in built]
    train_set = _concat_feature_sets(feature_sets[:-1])
    validation_set = feature_sets[-1]
    ranker_validation = validation_set
    if config.tune_on_example_users:
        ranker_validation, example_target = restrict_to_example_users(
            validation_set,
            materials[-1].target,
            example_users(config),
        )
        LOGGER.info(
            "El early stopping del último fold usa %s lectores de %s",
            example_target[USER_COL].nunique(),
            config.example_path,
        )
    ranker = LambdaRanker(
        config.ranker,
        random_state=config.random_seed,
        overrides=overrides,
    ).fit(train_set, ranker_validation)
    ablation_metrics: list[dict[str, object]] = []
    if execute_ablations:
        LOGGER.info("LambdaRank principal entrenado; ejecutando ablaciones")
        feature_ablations = run_ablations(
            train_set,
            validation_set,
            materials[-1].target,
            config,
        )
        source_ablation_rows = []
        validation_sources = materials[-1].source_candidates
        for source in sorted(validation_sources["source"].unique()):
            without_source = validation_sources[
                validation_sources["source"] != source
            ]
            ablated_candidates = fusion.fuse(without_source, cutoff).candidates
            metrics = retrieval_metrics(
                ablated_candidates,
                materials[-1].target,
            )
            source_ablation_rows.append(
                {
                    "stage": "retrieval",
                    "ablation": f"without_{source}",
                    "ndcg_at_10": metrics.oracle_ndcg,
                    "features": None,
                    "recall": metrics.recall,
                }
            )
        _, full_fusion = built[-1]
        full_retrieval = retrieval_metrics(
            full_fusion.candidates,
            materials[-1].target,
        )
        ablation_metrics = feature_ablations.to_dict(
            orient="records"
        ) + rows_against_reference(
            source_ablation_rows,
            stage="retrieval",
            ndcg_at_10=full_retrieval.oracle_ndcg,
            recall=full_retrieval.recall,
        )
    else:
        LOGGER.info("LambdaRank final entrenado; se omiten ablaciones repetidas")

    if tune:
        record_tuned_hyperparameters(
            config,
            rrf_cutoff=cutoff,
            weights=weights,
            ranker=overrides,
        )

    fold_metrics = []
    for material, (features, fused) in zip(materials, built, strict=True):
        metrics = retrieval_metrics(fused.candidates, material.target)
        fold_metrics.append(
            {
                "fold": float(material.fold),
                "recall": metrics.recall,
                "weighted_recall": metrics.weighted_recall,
                "oracle_ndcg_at_10": metrics.oracle_ndcg,
                "mean_candidates": metrics.mean_candidates,
            }
        )
    return TrainedPipeline(
        ranker=ranker,
        weights=weights,
        rrf_cutoff=cutoff,
        fold_metrics=fold_metrics,
        ablation_metrics=ablation_metrics,
        hyperparameters_origin=hyperparameters_origin,
        hyperparameters_run_name=hyperparameters_run_name,
    )


def _score_history(
    trained: TrainedPipeline,
    train: pd.DataFrame,
    users: tuple[str, ...],
    books: pd.DataFrame,
    config: PipelineConfig,
    readers: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, FusionResult, RankerTable]:
    """Recupera, fusiona y rankea un historial con el modelo ya entrenado."""

    material = _collect_material(
        train,
        target=train.iloc[0:0].copy(),
        users=users,
        books=books,
        config=config,
        fold=999,
        per_source=per_source_depth(
            trained.rrf_cutoff,
            rrf_k=config.retrieval.rrf_k,
            n_sources=len(retrievers_from_config(config)),
        ),
        readers=readers,
    )
    fusion = CandidateFusion(
        weights=trained.weights,
        rrf_k=config.retrieval.rrf_k,
    )
    fused = fusion.fuse(material.source_candidates, trained.rrf_cutoff)
    features = material.feature_builder.transform(
        fused.candidates,
        fused.source_candidates,
    )
    recommendations = trained.ranker.predict(features)
    return recommendations, fused, features


def evaluate(
    config: PipelineConfig | None = None,
    *,
    tune: bool = False,
    save_artifacts: bool = True,
) -> tuple[EvaluationReport, TrainedPipeline | None]:
    """Evalúa una sola vez sobre el leave-last-k exterior."""

    from .tracking import log_evaluation, log_summary_artifacts, track_command

    config = config or PipelineConfig()
    with track_command("evaluate", config, tune=tune):
        report, trained = _evaluate(config, tune=tune, save_artifacts=save_artifacts)
        log_evaluation(report)
        if save_artifacts:
            log_summary_artifacts(Path(config.artifacts_dir), model=config.model)
        return report, trained


def _evaluate(
    config: PipelineConfig,
    *,
    tune: bool,
    save_artifacts: bool,
) -> tuple[EvaluationReport, TrainedPipeline | None]:
    """Corre el modelo sobre el hold-out y, si corresponde, escribe artifacts/."""

    from .models import build_model

    split = load_split(config, holdout=True)
    LOGGER.info(
        "Holdout listo: %s usuarios y %s interacciones de test",
        len(split.evaluation_users),
        len(split.test),
    )
    model = build_model(config.model, config)
    model.fit(split, tune=tune)
    recommendations = model.recommend(split.evaluation_users)
    LOGGER.info("Ranking del holdout completado")
    k = config.split.holdout_k
    top = recommendations[recommendations["rank"] <= k].copy()

    popularity = PopularityRecommender().fit(
        split.history,
        set(observed_catalog(split.history, split.books)[ITEM_COL]),
    )
    baseline = popularity.recommend(
        split.evaluation_users,
        split.history,
        n=k,
    )
    baseline_per_user = ndcg_per_user(baseline, split.test, k=k)
    model_per_user = ndcg_per_user(top, split.test, k=k)
    recall, oracle, budget = _retrieval_of(model, split)
    report = EvaluationReport(
        model_ndcg_at_10=float(model_per_user.mean()) if len(model_per_user) else 0.0,
        baseline_ndcg_at_10=(
            float(baseline_per_user.mean()) if len(baseline_per_user) else 0.0
        ),
        retrieval_recall=recall,
        retrieval_oracle_ndcg_at_10=oracle,
        candidate_budget=budget,
        evaluation_users=len(split.evaluation_users),
    )

    if save_artifacts:
        from .tracking import with_run_name, write_run_marker

        artifacts = Path(config.artifacts_dir)
        artifacts.mkdir(parents=True, exist_ok=True)
        clear_foreign_diagnostics(artifacts, config.model)
        write_run_marker(artifacts)
        (artifacts / "config.json").write_text(
            json.dumps(with_run_name(config.as_dict()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (artifacts / "data_quality.json").write_text(
            json.dumps(
                with_run_name(asdict(split.quality)),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (artifacts / "evaluation.json").write_text(
            json.dumps(with_run_name(asdict(report)), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _stamp_frame(top).to_csv(
            artifacts / "evaluation_recommendations.csv", index=False
        )
        _write_retrieval_hits(artifacts, model, split)
        trained = getattr(model, "trained", None)
        if isinstance(trained, TrainedPipeline):
            _stamp_frame(pd.DataFrame(trained.fold_metrics)).to_csv(
                artifacts / "retrieval_folds.csv", index=False
            )
            _stamp_frame(trained.ranker.feature_importance()).to_csv(
                artifacts / "feature_importance.csv", index=False
            )
            _stamp_frame(pd.DataFrame(trained.ablation_metrics)).to_csv(
                artifacts / "feature_ablations.csv", index=False
            )
            joblib.dump(trained, artifacts / "evaluated_pipeline.joblib")
    trained = getattr(model, "trained", None)
    return report, trained if isinstance(trained, TrainedPipeline) else None


def _write_retrieval_hits(artifacts: Path, model: object, split: SplitData) -> None:
    """Guarda, por libro de test, si el retrieval lo trajo. Borra el archivo viejo si no aplica."""

    path = artifacts / "evaluation_retrieval_hits.csv"
    fused = getattr(model, "fused", None)
    if fused is None:
        if path.is_file():
            path.unlink()
        return
    _stamp_frame(retrieval_hits(fused.candidates, split.test)).to_csv(path, index=False)


def _retrieval_of(model: object, split: SplitData) -> tuple[float, float, int]:
    """Recall, NDCG oracle y corte de candidatos. Ceros si el modelo no recupera."""

    fused = getattr(model, "fused", None)
    trained = getattr(model, "trained", None)
    if fused is None or not isinstance(trained, TrainedPipeline):
        return 0.0, 0.0, 0
    metrics = retrieval_metrics(fused.candidates, split.test)
    return metrics.recall, metrics.oracle_ndcg, trained.rrf_cutoff


def _stamp_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Agrega la corrida activa como columna, sin tocar el frame original."""

    from .tracking import active_run_name

    run_name = active_run_name()
    if not run_name:
        return frame
    stamped = frame.copy()
    stamped.insert(0, "run_name", run_name)
    return stamped


class TwoStage:
    """Retrieval + LambdaRank. La validación es el último fold rolling."""

    name = "two_stage"

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.trained: TrainedPipeline | None = None
        self.fused: FusionResult | None = None
        self._split: SplitData | None = None

    def fit(self, split: SplitData, *, tune: bool = False) -> None:
        """Entrena retrieval y LambdaRank. Las ablaciones solo corren en evaluate."""

        self._split = split
        self.trained = train_ranker_from_history(
            split.history,
            split.books,
            self.config,
            readers=split.readers,
            tune=tune,
            execute_ablations=split.holdout,
        )

    def recommend(self, users: tuple[str, ...] | list[str]) -> pd.DataFrame:
        """Rankea a esos lectores y guarda los candidatos fusionados."""

        if self.trained is None or self._split is None:
            raise RuntimeError("El modelo debe entrenarse antes de recomendar")
        recommendations, fused, _ = _score_history(
            self.trained,
            self._split.history,
            tuple(users),
            self._split.books,
            self.config,
            readers=self._split.readers,
        )
        self.fused = fused
        return recommendations


def run_ablations(
    train_features: RankerTable,
    validation_features: RankerTable,
    validation_truth: pd.DataFrame,
    config: PipelineConfig,
) -> pd.DataFrame:
    """Compara familias de features manteniendo fijo el conjunto candidato."""

    groups = {
        "without_retrieval": lambda column: not column.startswith(
            ("score_", "rank_", "present_", "reciprocal_", "rrf_", "retrieval_")
        ),
        "without_sequence": lambda column: not any(
            token in column
            for token in (
                "recent_",
                "transition_",
                "same_last_",
                "publication_age",
                "edition_vs_user_mean_year",
            )
        ),
    }
    reference_columns = train_features.feature_columns
    reference_ranker = LambdaRanker(
        config.ranker,
        random_state=config.random_seed,
    ).fit(
        RankerTable(train_features.frame, reference_columns),
        RankerTable(validation_features.frame, reference_columns),
    )
    reference_score = ndcg_at_k(
        reference_ranker.predict(
            RankerTable(validation_features.frame, reference_columns)
        ),
        validation_truth,
    )
    rows = []
    for name, keep in groups.items():
        columns = tuple(column for column in reference_columns if keep(column))
        train_subset = RankerTable(train_features.frame, columns)
        validation_subset = RankerTable(validation_features.frame, columns)
        ranker = LambdaRanker(
            config.ranker,
            random_state=config.random_seed,
        ).fit(train_subset, validation_subset)
        score = ndcg_at_k(ranker.predict(validation_subset), validation_truth)
        rows.append(
            {
                "stage": "ranker",
                "ablation": name,
                "ndcg_at_10": score,
                "features": len(columns),
                "recall": None,
            }
        )
    return pd.DataFrame(
        rows_against_reference(
            rows,
            stage="ranker",
            ndcg_at_10=reference_score,
            features=float(len(reference_columns)),
        )
    )
