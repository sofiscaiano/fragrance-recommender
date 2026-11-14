"""EASE: matriz ítem-ítem de Steck (WWW 2019).

Con la matriz de interacciones X (lectores × libros) se aprende B tal que
la predicción es X B, la diagonal de B es cero y el ajuste es error
cuadrático más una penalización L2.

X guarda el rating. Una lectura que no está vale 0. Al puntuar, el perfil
del lector es ese rating por la recencia: la similitud entre libros no
depende de cuándo se leyeron, y el ranking sí. Meter la recencia en X
cambiaría el número a reconstruir, no el peso del error.

`EaseRetriever`, en `two_stage/retrieval.py`, usa esta matriz como fuente
de `two_stage`. No rellena con popularidad: esa lista ya es otra fuente.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse

from .config import EaseConfig, PipelineConfig
from .data import DATE_COL, ITEM_COL, RATING_COL, USER_COL, object_ids

LOGGER = logging.getLogger(__name__)
EASE_HYPERPARAMETERS_FILE = "ease_hyperparameters.json"
# Con 5 lecturas el catálogo pasa de ~12.000 libros y la Gram densa deja de
# entrar cómoda en memoria.
MAX_ITEMS = 12_000
_SCORE_BATCH = 512


@dataclass(frozen=True)
class EaseParameters:
    """λ y el mínimo de lecturas. El perfil de consulta no se busca."""

    reg_lambda: float
    min_interactions: int
    run_name: str = ""


@dataclass(frozen=True)
class EaseSpectrum:
    """Autovalores de XᵀX. Alcanza para puntuar cualquier λ sin rearma B."""

    item_ids: np.ndarray
    eigenvalues: np.ndarray
    eigenvectors: np.ndarray


def ease_hyperparameters_path(artifacts_dir: Path) -> Path:
    """Ruta del tuneo de EASE. No es el JSON de two_stage."""

    return Path(artifacts_dir) / EASE_HYPERPARAMETERS_FILE


def load_ease_hyperparameters(path: Path) -> EaseParameters:
    """Lee el JSON de EASE. Falla si el archivo existe pero no es válido."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("el archivo no es un objeto")
        reg_lambda = float(payload["reg_lambda"])
        min_interactions = int(payload["min_interactions"])
        run_name = payload.get("run_name", "")
        if not isinstance(run_name, str):
            raise TypeError("run_name debe ser texto")
        if reg_lambda <= 0 or min_interactions < 1:
            raise ValueError("reg_lambda y min_interactions deben ser positivos")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Hiperparámetros de EASE inválidos en {path}") from exc
    if "weight_mode" in payload:
        LOGGER.info(
            "Se ignora weight_mode=%s en %s: la matriz usa el rating y la consulta, la recencia",
            payload["weight_mode"],
            path,
        )
    return EaseParameters(
        reg_lambda=reg_lambda,
        min_interactions=min_interactions,
        run_name=run_name,
    )


def parameters_from_config(config: EaseConfig) -> EaseParameters:
    """Valores fijos, los de una corrida sin archivo guardado."""

    return EaseParameters(
        reg_lambda=float(config.reg_lambda),
        min_interactions=int(config.min_interactions),
    )


def ease_source_parameters(config: PipelineConfig) -> EaseParameters:
    """Parámetros de la matriz como fuente de two_stage.

    El JSON guardado gana. Si no está, valen los de `EaseConfig`. two_stage
    no vuelve a buscar λ ni el mínimo: solo elige el peso.
    """

    path = ease_hyperparameters_path(config.artifacts_dir)
    if path.is_file():
        return load_ease_hyperparameters(path)
    return parameters_from_config(config.ease)


def _profile_weights(frame: pd.DataFrame, half_life_days: float) -> np.ndarray:
    """Rating por recencia. La edad se mide contra la última lectura del lector."""

    rating = frame[RATING_COL].to_numpy(dtype=np.float64)
    if half_life_days <= 0 or len(frame) == 0:
        return rating
    max_dates = frame.groupby(USER_COL, sort=False)[DATE_COL].transform("max")
    age_days = (max_dates - frame[DATE_COL]).dt.days.clip(lower=0).to_numpy()
    return rating * np.exp2(-age_days / half_life_days)


def interaction_matrix(
    frame: pd.DataFrame,
    *,
    min_interactions: int,
) -> tuple[sparse.csr_matrix, np.ndarray]:
    """Matriz lectores × libros frecuentes. Cada celda es el rating, sin recencia."""

    counts = frame.groupby(ITEM_COL, sort=False).size()
    item_ids = np.array(
        sorted(counts[counts >= min_interactions].index.astype(str)),
        dtype=object,
    )
    if len(item_ids) > MAX_ITEMS:
        raise ValueError(
            f"EASE armaría una matriz densa de {len(item_ids)} libros. "
            f"Subí min_interactions (ahora {min_interactions}); el tope es {MAX_ITEMS}."
        )
    if len(item_ids) == 0:
        empty = sparse.csr_matrix((0, 0), dtype=np.float64)
        return empty, item_ids
    item_index = {item: index for index, item in enumerate(item_ids)}
    columns = np.fromiter(
        (item_index.get(item, -1) for item in frame[ITEM_COL].astype(str)),
        dtype=np.int64,
        count=len(frame),
    )
    mask = columns >= 0
    users = np.array(
        sorted(frame.loc[mask, USER_COL].astype(str).unique()),
        dtype=object,
    )
    user_index = {user: index for index, user in enumerate(users)}
    rows = frame.loc[mask, USER_COL].astype(str).map(user_index).to_numpy()
    weights = frame.loc[mask, RATING_COL].to_numpy(dtype=np.float64)
    matrix = sparse.csr_matrix(
        (weights, (rows, columns[mask])),
        shape=(len(users), len(item_ids)),
        dtype=np.float64,
    )
    return matrix, item_ids


def spectrum_from_matrix(
    matrix: sparse.csr_matrix,
    item_ids: np.ndarray,
) -> EaseSpectrum:
    """Diagonaliza XᵀX. λ se aplica después, así varios trials comparten esto."""

    if matrix.shape[1] == 0:
        return EaseSpectrum(
            item_ids=item_ids,
            eigenvalues=np.zeros(0, dtype=np.float64),
            eigenvectors=np.zeros((0, 0), dtype=np.float64),
        )
    gram = (matrix.T @ matrix).toarray()
    gram = (gram + gram.T) * 0.5
    eigenvalues, eigenvectors = np.linalg.eigh(gram)
    np.maximum(eigenvalues, 0.0, out=eigenvalues)
    return EaseSpectrum(
        item_ids=item_ids,
        eigenvalues=eigenvalues,
        eigenvectors=eigenvectors,
    )


def score_users(matrix: sparse.csr_matrix, spectrum: EaseSpectrum, reg_lambda: float) -> np.ndarray:
    """Puntúa filas de X. s = x − (x P) / diag(P), con P = (XᵀX + λI)⁻¹."""

    n_users, n_items = matrix.shape
    if n_items == 0 or n_users == 0:
        return np.zeros((n_users, n_items), dtype=np.float64)
    if reg_lambda <= 0:
        raise ValueError("reg_lambda debe ser positivo")
    inverse = 1.0 / (spectrum.eigenvalues + reg_lambda)
    diagonal = np.square(spectrum.eigenvectors) @ inverse
    projected = matrix @ spectrum.eigenvectors
    reconstructed = (projected * inverse) @ spectrum.eigenvectors.T
    return matrix.toarray() - reconstructed / diagonal


def _matrix_for_users(
    frame: pd.DataFrame,
    users: list[str],
    item_ids: np.ndarray,
    *,
    half_life_days: float,
) -> sparse.csr_matrix:
    """Una fila por lector, en ese orden. El peso es rating por recencia."""

    item_index = {item: index for index, item in enumerate(item_ids)}
    if not item_index:
        return sparse.csr_matrix((len(users), 0), dtype=np.float64)
    user_index = {user: index for index, user in enumerate(users)}
    columns = object_ids(frame[ITEM_COL]).map(item_index)
    rows = object_ids(frame[USER_COL]).map(user_index)
    mask = columns.notna() & rows.notna()
    weights = _profile_weights(frame, half_life_days)
    return sparse.csr_matrix(
        (
            weights[mask.to_numpy()],
            (rows[mask].to_numpy(dtype=np.int64), columns[mask].to_numpy(dtype=np.int64)),
        ),
        shape=(len(users), len(item_ids)),
        dtype=np.float64,
    )


def _top_unseen(
    item_ids: np.ndarray,
    scores: np.ndarray,
    seen: set[str],
    n: int,
) -> list[tuple[str, float]]:
    """Top-n con desempate por id_libro. Los ya leídos quedan afuera."""

    if n <= 0 or len(item_ids) == 0:
        return []
    ranked_scores = scores.copy()
    for index, item in enumerate(item_ids):
        if item in seen:
            ranked_scores[index] = -np.inf
    order = np.lexsort((item_ids, -ranked_scores))
    chosen: list[tuple[str, float]] = []
    for index in order:
        if not np.isfinite(ranked_scores[index]):
            continue
        chosen.append((str(item_ids[index]), float(ranked_scores[index])))
        if len(chosen) == n:
            break
    return chosen


def ease_ranking(
    history: pd.DataFrame,
    users: list[str],
    spectrum: EaseSpectrum,
    parameters: EaseParameters,
    *,
    half_life_days: float,
    n: int,
) -> pd.DataFrame:
    """Top-n de la matriz, sin popularidad y sin lectores que no aportan peso."""

    columns = [USER_COL, ITEM_COL, "score", "rank"]
    if not users or n <= 0 or len(spectrum.item_ids) == 0:
        return pd.DataFrame(columns=columns)
    unique = list(dict.fromkeys(users))
    matrix = _matrix_for_users(
        history,
        unique,
        spectrum.item_ids,
        half_life_days=half_life_days,
    )
    scored = np.zeros((len(unique), len(spectrum.item_ids)), dtype=np.float64)
    for start in range(0, len(unique), _SCORE_BATCH):
        stop = start + _SCORE_BATCH
        scored[start:stop] = score_users(
            matrix[start:stop],
            spectrum,
            parameters.reg_lambda,
        )
    totals = np.asarray(matrix.sum(axis=1)).ravel()
    if history.empty:
        seen: dict[object, set[str]] = {}
    else:
        seen = history.groupby(USER_COL, sort=False)[ITEM_COL].agg(set).to_dict()
    rows: list[dict[str, object]] = []
    for user, row, total in zip(unique, scored, totals, strict=True):
        if total <= 0:
            continue
        chosen = _top_unseen(
            spectrum.item_ids,
            row,
            set(seen.get(user, set())),
            n,
        )
        for rank, (item, score) in enumerate(chosen, start=1):
            rows.append(
                {
                    USER_COL: user,
                    ITEM_COL: item,
                    "score": score,
                    "rank": rank,
                }
            )
    return pd.DataFrame.from_records(rows, columns=columns)

