"""CLI del recomendador en dos etapas."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, replace
from pathlib import Path
from typing import Annotated

import typer

from fragrantica_rec.config import ARTIFACTS_DIR, DATA_DIR, PipelineConfig
from fragrantica_rec.pipeline import evaluate as evaluate_pipeline
from fragrantica_rec.serving import export_serving_artifact

app = typer.Typer(
    help="Recomendador de perfumes en dos etapas",
    invoke_without_command=True,
)

DataOption = Annotated[
    Path, typer.Option("--data", help="Carpeta con interactions.parquet e items.parquet")
]
ArtifactsOption = Annotated[
    Path, typer.Option("--artifacts", help="Directorio de artefactos y log")
]
TuneOption = Annotated[
    bool,
    typer.Option(
        "--tune",
        help=(
            "Busca con Optuna y lo agrega al historial. Sin este flag, two_stage "
            "reutiliza un tuneo de la misma config; si no hay, pide correr --tune"
        ),
    ),
]
SeedOption = Annotated[
    int | None,
    typer.Option("--seed", help="Semilla. Sin el flag se usa PipelineConfig.random_seed"),
]
NoteOption = Annotated[
    str,
    typer.Option("--note", help="Descripción obligatoria de esta corrida"),
]
LabelGainOption = Annotated[
    str | None,
    typer.Option(
        "--label-gain",
        help=(
            "Ganancia de LambdaRank: linear (0..5) o exponential (2^rel-1). "
            "Sin el flag se usa RankerConfig.label_gain. Cambiarla exige --tune"
        ),
    ),
]
TwoTowerSourceOption = Annotated[
    bool | None,
    typer.Option(
        "--two-tower-source/--no-two-tower-source",
        help="Prende o apaga el two-tower como fuente de retrieval",
    ),
]
EaseSourceOption = Annotated[
    bool | None,
    typer.Option(
        "--ease-source/--no-ease-source",
        help="Prende o apaga EASE como fuente de retrieval",
    ),
]


def _configure_logging(artifacts: Path) -> None:
    """Log a consola y a ``artifacts/run.log``."""

    artifacts.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(artifacts / "run.log", encoding="utf-8"),
        ],
        force=True,
    )


def _config(
    data: Path,
    artifacts: Path,
    seed: int | None,
    note: str,
    label_gain: str | None,
    two_tower_source: bool | None = None,
    ease_source: bool | None = None,
) -> PipelineConfig:
    """Arma la config de la corrida con las rutas y la nota."""

    base = PipelineConfig()
    retrieval = base.retrieval
    if two_tower_source is not None:
        retrieval = replace(retrieval, two_tower_source=two_tower_source)
    if ease_source is not None:
        retrieval = replace(retrieval, ease_source=ease_source)
    ranker = base.ranker
    if label_gain is not None:
        ranker = replace(ranker, label_gain=label_gain)
    config = replace(
        base,
        data_dir=data,
        artifacts_dir=artifacts,
        run_note=note,
        ranker=ranker,
        retrieval=retrieval,
    )
    if seed is not None:
        config = replace(config, random_seed=seed)
    return config


def _run(
    *,
    data: Path,
    artifacts: Path,
    tune: bool,
    seed: int | None,
    note: str,
    label_gain: str | None,
    two_tower_source: bool | None = None,
    ease_source: bool | None = None,
) -> None:
    """Evalúa el holdout con la misma configuración."""

    if not note.strip():
        raise typer.BadParameter("La corrida exige --note con una descripción.")
    _configure_logging(artifacts)
    config = _config(
        data,
        artifacts,
        seed,
        note,
        label_gain,
        two_tower_source,
        ease_source,
    )
    logger = logging.getLogger(__name__)
    logger.info(
        "Modelo two_stage. Fuentes: %s",
        ", ".join(config.retrieval.enabled_sources()),
    )
    logger.info(
        "Comando evaluate (tune=%s, seed=%s, label_gain=%s). Log en %s",
        tune,
        config.random_seed,
        config.ranker.label_gain,
        artifacts / "run.log",
    )
    report, _ = evaluate_pipeline(config, tune=tune)
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))


@app.callback()
def main(
    ctx: typer.Context,
    data: DataOption = DATA_DIR,
    artifacts: ArtifactsOption = ARTIFACTS_DIR,
    tune: TuneOption = False,
    seed: SeedOption = None,
    note: NoteOption = "",
    label_gain: LabelGainOption = None,
) -> None:
    """Sin subcomando, evalúa. two_stage reutiliza el último tuneo."""

    if ctx.invoked_subcommand is None:
        _run(
            data=data,
            artifacts=artifacts,
            tune=tune,
            seed=seed,
            note=note,
            label_gain=label_gain,
        )


@app.command()
def evaluate(
    data: DataOption = DATA_DIR,
    artifacts: ArtifactsOption = ARTIFACTS_DIR,
    tune: TuneOption = False,
    seed: SeedOption = None,
    note: NoteOption = ...,
    label_gain: LabelGainOption = None,
    two_tower_source: TwoTowerSourceOption = None,
    ease_source: EaseSourceOption = None,
) -> None:
    """Evalúa las últimas interacciones de cada usuario y escribe artifacts/."""

    _run(
        data=data,
        artifacts=artifacts,
        tune=tune,
        seed=seed,
        note=note,
        label_gain=label_gain,
        two_tower_source=two_tower_source,
        ease_source=ease_source,
    )


@app.command("export-serving")
def export_serving(
    data: DataOption = DATA_DIR,
    artifacts: ArtifactsOption = ARTIFACTS_DIR,
    seed: SeedOption = None,
) -> None:
    """Ajusta las fuentes sobre todo el historial y escribe serving.joblib.

    El LambdaRank es el de evaluated_pipeline.joblib. No vuelve a entrenarlo.
    """

    _configure_logging(artifacts)
    config = _config(
        data,
        artifacts,
        seed,
        note="export serving",
        label_gain=None,
    )
    path = export_serving_artifact(config)
    print(path)


if __name__ == "__main__":
    app()
