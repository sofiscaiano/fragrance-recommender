"""Parámetros de las fuentes de ``two_stage``.

``two_stage`` lee el JSON de cada fuente, si existe, y no lo vuelve a buscar:
en la fusión solo elige el peso. Sin archivo, usa los valores de la config.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from .config import PipelineConfig

SOURCE_NAMES = ("item_cosine", "als", "bpr", "tfidf")


@dataclass(frozen=True)
class ItemCosineParameters:
    """Semivida del coseno. El perfil no tiene otros hiperparámetros."""

    half_life_days: float
    run_name: str = ""


@dataclass(frozen=True)
class AlsParameters:
    """Factores, pasos, regularización y semivida de ALS."""

    factors: int
    iterations: int
    regularization: float
    half_life_days: float
    run_name: str = ""


@dataclass(frozen=True)
class BprParameters:
    """Factores, pasos, learning rate, regularización y semivida de BPR."""

    factors: int
    iterations: int
    learning_rate: float
    regularization: float
    half_life_days: float
    run_name: str = ""


@dataclass(frozen=True)
class TfidfParameters:
    """Tope del vocabulario y semivida del perfil de texto."""

    max_features: int
    half_life_days: float
    run_name: str = ""


SourceParameters = ItemCosineParameters | AlsParameters | BprParameters | TfidfParameters

_FIELDS: dict[str, tuple[str, ...]] = {
    "item_cosine": ("half_life_days",),
    "als": ("factors", "iterations", "regularization", "half_life_days"),
    "bpr": ("factors", "iterations", "learning_rate", "regularization", "half_life_days"),
    "tfidf": ("max_features", "half_life_days"),
}
_INTEGERS = {
    "item_cosine": frozenset(),
    "als": frozenset({"factors", "iterations"}),
    "bpr": frozenset({"factors", "iterations"}),
    "tfidf": frozenset({"max_features"}),
}
_CLASSES: dict[str, type[SourceParameters]] = {
    "item_cosine": ItemCosineParameters,
    "als": AlsParameters,
    "bpr": BprParameters,
    "tfidf": TfidfParameters,
}


def source_hyperparameters_path(artifacts_dir: Path, name: str) -> Path:
    """Ruta del JSON de una fuente. No es el de two_stage ni el de otra."""

    _check_name(name)
    return Path(artifacts_dir) / f"{name}_hyperparameters.json"


def load_source_hyperparameters(path: Path, name: str) -> SourceParameters:
    """Lee el JSON de una fuente. Falla si el archivo existe pero no es válido."""

    _check_name(name)
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("el archivo no es un objeto")
        values = {
            field: _read_field(payload[field], field, integer=field in _INTEGERS[name])
            for field in _FIELDS[name]
        }
        run_name = payload.get("run_name", "")
        if not isinstance(run_name, str):
            raise TypeError("run_name debe ser texto")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Hiperparámetros de {name} inválidos en {path}") from exc
    return _CLASSES[name](**values, run_name=run_name)


def parameters_from_config(config: PipelineConfig, name: str) -> SourceParameters:
    """Valores fijos, los de una corrida sin archivo guardado."""

    _check_name(name)
    block = getattr(config, name)
    values = {field: getattr(block, field) for field in _FIELDS[name]}
    return _CLASSES[name](**values)


def resolve_source_parameters(
    config: PipelineConfig,
    name: str,
) -> tuple[SourceParameters, str]:
    """Devuelve el JSON de la fuente, o los valores fijos si ese archivo no existe."""

    path = source_hyperparameters_path(config.artifacts_dir, name)
    if path.is_file():
        return load_source_hyperparameters(path, name), "saved"
    return parameters_from_config(config, name), "default"


def item_cosine_source_parameters(config: PipelineConfig) -> ItemCosineParameters:
    """Semivida del coseno como fuente de two_stage."""

    parameters, _origin = resolve_source_parameters(config, "item_cosine")
    assert isinstance(parameters, ItemCosineParameters)
    return parameters


def als_source_parameters(config: PipelineConfig) -> AlsParameters:
    """Parámetros de ALS. two_stage no los vuelve a buscar."""

    parameters, _origin = resolve_source_parameters(config, "als")
    assert isinstance(parameters, AlsParameters)
    return parameters


def bpr_source_parameters(config: PipelineConfig) -> BprParameters:
    """Parámetros de BPR. No se comparten con ALS."""

    parameters, _origin = resolve_source_parameters(config, "bpr")
    assert isinstance(parameters, BprParameters)
    return parameters


def tfidf_source_parameters(config: PipelineConfig) -> TfidfParameters:
    """Tope de términos y semivida de TF-IDF."""

    parameters, _origin = resolve_source_parameters(config, "tfidf")
    assert isinstance(parameters, TfidfParameters)
    return parameters


def _check_name(name: str) -> None:
    if name not in _CLASSES:
        known = ", ".join(SOURCE_NAMES)
        raise ValueError(f"Fuente desconocida: {name}. Opciones: {known}")


def _read_field(value: Any, name: str, *, integer: bool) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} debe ser un número")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{name} debe ser finito")
    if integer:
        if isinstance(value, float) and not value.is_integer():
            raise ValueError(f"{name} debe ser entero")
        number = int(value)
        if number < 1:
            raise ValueError(f"{name} debe ser positivo")
        return number
    number = float(value)
    if number <= 0:
        raise ValueError(f"{name} debe ser positivo")
    return number


TWO_TOWER_HYPERPARAMETERS_FILE = "two_tower_hyperparameters.json"
_TWO_TOWER_FIELDS = ("embedding_dim", "learning_rate", "temperature", "min_item_reads")
_TWO_TOWER_INTEGERS = frozenset({"embedding_dim", "min_item_reads"})


@dataclass(frozen=True)
class TwoTowerParameters:
    """Dimensión, learning rate, temperatura y mínimo de lecturas del two-tower.

    Vive acá, y no en ``two_tower.py``, para que ``two_stage`` arme la fuente
    sin importar torch en el mismo proceso que LightGBM. El resto queda en
    ``TwoTowerConfig``.
    """

    embedding_dim: int
    learning_rate: float
    temperature: float
    min_item_reads: int
    run_name: str = ""


def two_tower_hyperparameters_path(artifacts_dir: Path) -> Path:
    """Ruta del JSON del two-tower. No es el de two_stage."""

    return Path(artifacts_dir) / TWO_TOWER_HYPERPARAMETERS_FILE


def load_two_tower_hyperparameters(path: Path) -> TwoTowerParameters:
    """Lee el JSON del two-tower. Falla si el archivo existe pero no es válido."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("el archivo no es un objeto")
        values = {
            field: _read_field(
                payload[field],
                field,
                integer=field in _TWO_TOWER_INTEGERS,
            )
            for field in _TWO_TOWER_FIELDS
        }
        run_name = payload.get("run_name", "")
        if not isinstance(run_name, str):
            raise TypeError("run_name debe ser texto")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Hiperparámetros de two_tower inválidos en {path}") from exc
    return TwoTowerParameters(**values, run_name=run_name)


def apply_two_tower_parameters(
    config: PipelineConfig,
    parameters: TwoTowerParameters,
) -> PipelineConfig:
    """Devuelve la config con los cuatro valores del JSON ya puestos."""

    block = replace(
        config.two_tower,
        embedding_dim=int(parameters.embedding_dim),
        learning_rate=float(parameters.learning_rate),
        temperature=float(parameters.temperature),
        min_item_reads=int(parameters.min_item_reads),
    )
    return replace(config, two_tower=block)


def resolved_two_tower_config(config: PipelineConfig) -> tuple[PipelineConfig, str, str]:
    """Config con el JSON ya aplicado. Sin archivo, devuelve la config tal cual.

    El proceso hijo recibe esta config y no vuelve a abrir el JSON.
    """

    path = two_tower_hyperparameters_path(config.artifacts_dir)
    if not path.is_file():
        return config, "default", ""
    saved = load_two_tower_hyperparameters(path)
    return apply_two_tower_parameters(config, saved), "saved", saved.run_name


def two_tower_resolved_values(config: PipelineConfig) -> dict[str, Any]:
    """Valores con los que se entrena la torre."""

    resolved, _origin, _run_name = resolved_two_tower_config(config)
    return asdict(resolved.two_tower)
