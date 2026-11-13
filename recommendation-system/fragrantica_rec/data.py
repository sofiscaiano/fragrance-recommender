"""Carga de las reviews y el catálogo de perfumes.

El marco `books` es el catálogo de perfumes. Conserva ese nombre porque el
prototipo se lo pasa así a cada etapa. Las columnas de adentro son de perfume:
marca, familia olfativa y año de lanzamiento.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import ACTIVE_CUT, CUTS, DATA_DIR

USER_COL = "member_id"
ITEM_COL = "perfume_id"
DATE_COL = "timestamp"
RATING_COL = "rating"
RATING_MAX = 5
# Notas 4 y 5, el tramo alto de la escala 1–5. En el prototipo de libros era 8.
HIGH_RATING = 4

_ITEM_COLUMNS = [
    ITEM_COL,
    "name",
    "brand",
    "gender",
    "launch_year",
    "olfactive_family",
    "perfumers",
    "accords",
    "notes",
    "description",
]


def object_ids(values: pd.Series) -> pd.Series:
    """Ids como ``object``.

    ``isin`` de ``string[pyarrow]`` contra un diccionario grande tarda más de
    100 ms aunque la serie tenga una sola fila.
    """

    if values.dtype == object:
        return values
    return values.astype(object)


@dataclass(frozen=True)
class DataQualityReport:
    """Resumen de anomalías detectadas durante la carga."""

    interaction_count: int
    valid_interaction_count: int
    invalid_date_count: int
    orphan_user_count: int
    orphan_user_interactions: int
    orphan_item_count: int
    orphan_item_interactions: int
    catalog_items_without_interactions: int


@dataclass(frozen=True)
class DatasetBundle:
    """Tablas normalizadas y reporte de calidad."""

    interactions: pd.DataFrame
    invalid_interactions: pd.DataFrame
    books: pd.DataFrame
    readers: pd.DataFrame
    report: DataQualityReport

    @property
    def modeled_interactions(self) -> pd.DataFrame:
        """Interacciones con fecha válida y perfume presente en catálogo."""

        valid_items = set(self.books[ITEM_COL])
        return self.interactions[
            self.interactions[ITEM_COL].isin(valid_items)
        ].reset_index(drop=True)


def kcore(df: pd.DataFrame, min_user: int, min_item: int) -> pd.DataFrame:
    """Itera el piso de reviews por usuario y por perfume hasta que se estabiliza."""

    current = df
    while True:
        user_count = current.groupby(USER_COL).size()
        item_count = current.groupby(ITEM_COL).size()
        users = user_count[user_count >= min_user].index
        items = item_count[item_count >= min_item].index
        nxt = current[current[USER_COL].isin(users) & current[ITEM_COL].isin(items)]
        if len(nxt) == len(current) or len(nxt) == 0:
            return nxt.reset_index(drop=True)
        current = nxt


def filtered_matrix(cut: str | None = None, directory: Path | None = None) -> pd.DataFrame:
    """Reviews con fecha y rating, después del k-core del corte activo.

    Los ids quedan como enteros, igual que el parquet, para el EDA.
    """

    chosen = cut or ACTIVE_CUT
    floors = CUTS[chosen]
    reviews, _invalid = _dated_reviews(directory or DATA_DIR)
    return kcore(reviews, floors["min_user"], floors["min_item"])


def load_dataset(path: str | Path | None = None) -> DatasetBundle:
    """Lee los parquet del corte activo y deja ids en texto.

    Una fila sin fecha no entra al split. El k-core es el de ``ACTIVE_CUT``.
    No hay tabla de lectores: el género y la edad del ranker quedan vacíos.
    """

    root = Path(path) if path is not None else DATA_DIR
    reviews, invalid = _dated_reviews(root)
    floors = CUTS[ACTIVE_CUT]
    matrix = kcore(reviews, floors["min_user"], floors["min_item"])
    items = _read_items(root)
    catalog_ids = set(items[ITEM_COL])
    orphan_mask = ~matrix[ITEM_COL].isin(catalog_ids)
    orphan_items = set(matrix.loc[orphan_mask, ITEM_COL])
    linked = matrix.loc[~orphan_mask].reset_index(drop=True)

    interactions = linked.copy()
    interactions[USER_COL] = interactions[USER_COL].astype(str)
    interactions[ITEM_COL] = interactions[ITEM_COL].astype(str)
    interactions[RATING_COL] = interactions[RATING_COL].astype("int8")
    if not interactions.empty and not interactions[RATING_COL].between(1, RATING_MAX).all():
        raise ValueError(f"Se encontraron ratings fuera del rango 1..{RATING_MAX}")

    kept_items = set(interactions[ITEM_COL])
    books = items[items[ITEM_COL].astype(str).isin(kept_items)].copy()
    books[ITEM_COL] = books[ITEM_COL].astype(str)
    readers = pd.DataFrame(columns=[USER_COL])
    report = DataQualityReport(
        interaction_count=_raw_count(root),
        valid_interaction_count=len(interactions),
        invalid_date_count=len(invalid),
        orphan_user_count=0,
        orphan_user_interactions=0,
        orphan_item_count=len(orphan_items),
        orphan_item_interactions=int(orphan_mask.sum()),
        catalog_items_without_interactions=len(catalog_ids - set(matrix[ITEM_COL])),
    )
    return DatasetBundle(
        interactions=interactions.reset_index(drop=True),
        invalid_interactions=invalid.reset_index(drop=True),
        books=books.reset_index(drop=True),
        readers=readers,
        report=report,
    )


def observed_catalog(
    interactions: pd.DataFrame,
    books: pd.DataFrame,
) -> pd.DataFrame:
    """Restringe el catálogo a perfumes observados en el train indicado."""

    observed = interactions[[ITEM_COL]].drop_duplicates()
    return observed.merge(books, on=ITEM_COL, how="inner", validate="one_to_one")


def _raw_count(root: Path) -> int:
    frame = pd.read_parquet(root / "interactions.parquet", columns=[USER_COL])
    return len(frame)


def _dated_reviews(root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reviews con rating. Las que no tienen fecha quedan aparte."""

    raw = pd.read_parquet(
        root / "interactions.parquet",
        columns=[USER_COL, ITEM_COL, DATE_COL, RATING_COL],
    )
    parsed_dates = _parse_dates(raw[DATE_COL])
    ratings = pd.to_numeric(raw[RATING_COL], errors="coerce")
    invalid_mask = parsed_dates.isna() | ratings.isna()
    invalid = raw.loc[invalid_mask].copy()
    reviews = raw.loc[~invalid_mask].copy()
    reviews[DATE_COL] = parsed_dates.loc[~invalid_mask]
    reviews[RATING_COL] = ratings.loc[~invalid_mask]
    reviews = reviews[reviews[RATING_COL].between(1, RATING_MAX)]
    reviews = reviews.drop_duplicates([USER_COL, ITEM_COL])
    return reviews.reset_index(drop=True), invalid.reset_index(drop=True)


def _parse_dates(values: pd.Series) -> pd.Series:
    """Unix en segundos. Los NaN no se convierten: pandas desborda en esa serie."""

    if pd.api.types.is_datetime64_any_dtype(values):
        return values
    numeric = pd.to_numeric(values, errors="coerce")
    present = numeric.dropna()
    parsed = pd.to_datetime(present.astype("int64"), unit="s", errors="coerce")
    return parsed.reindex(values.index)


def _read_items(root: Path) -> pd.DataFrame:
    raw = pd.read_parquet(root / "items.parquet", columns=_ITEM_COLUMNS)
    books = raw.drop_duplicates(ITEM_COL).copy()
    for column in ("name", "brand", "gender", "olfactive_family", "description"):
        books[column] = books[column].fillna("").astype(str).str.strip()
    books["perfumers"] = books["perfumers"].map(_names)
    books["accords"] = books["accords"].map(_names)
    books["notes"] = books["notes"].map(_names)
    year = pd.to_numeric(books["launch_year"], errors="coerce")
    books["launch_year"] = year.where(year.between(1000, 2100))
    return books.reset_index(drop=True)


def _names(value: object) -> str:
    """Junta los nombres de una lista JSON de perfumistas, accords o notas."""

    if value is None or value is pd.NA:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    parsed: object = value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        if text[0] not in "[{":
            return text
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return text
    if isinstance(parsed, list):
        parts = []
        for entry in parsed:
            if isinstance(entry, str):
                parts.append(entry)
            elif isinstance(entry, dict):
                parts.append(str(entry.get("name") or ""))
        return " ".join(part for part in parts if part)
    return str(parsed)
