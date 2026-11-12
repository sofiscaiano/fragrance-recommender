import json

import numpy as np
import pandas as pd

import config
from data import filtered_matrix

REVIEW_COLUMNS = [
    "member_id",
    "perfume_id",
    "rating",
    "timestamp",
    "longevity",
    "sillage",
    "season_winter",
    "season_spring",
    "season_summer",
    "season_autumn",
    "day",
    "night",
    "gender_vote",
]
ITEM_COLUMNS = [
    "perfume_id",
    "brand",
    "gender",
    "olfactive_family",
    "launch_year",
    "perfumers",
    "accords",
    "notes",
]
SEASONS = ["season_winter", "season_spring", "season_summer", "season_autumn"]


def write_report():
    reviews = _reviews()
    matrix = filtered_matrix()
    keys = matrix[["member_id", "perfume_id"]].drop_duplicates()
    kept = reviews.merge(keys, on=["member_id", "perfume_id"], how="inner")
    items = pd.read_parquet(config.DATA_DIR / "items.parquet", columns=ITEM_COLUMNS)
    items_all = items[items.perfume_id.isin(reviews.perfume_id)]
    items_kept = items[items.perfume_id.isin(matrix.perfume_id)]
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.REPORTS_DIR / "eda.md"
    path.write_text(_report(reviews, kept, items_all, items_kept))
    return path


def _reviews():
    df = pd.read_parquet(config.DATA_DIR / "interactions.parquet", columns=REVIEW_COLUMNS)
    df = df[df.timestamp.notna() & df.rating.notna()]
    return df.drop_duplicates(["member_id", "perfume_id"]).reset_index(drop=True)


def _report(reviews, kept, items_all, items_kept):
    lines = [
        "# EDA",
        "",
        f"Corte `{config.ACTIVE_CUT}`. Universo: reviews con fecha y rating. Matriz: k-core de ese corte.",
        "",
        "## Tamaño",
        "",
        _size(reviews, kept),
        "",
        _cut_sentence(reviews, kept),
        "",
        "## Nulos",
        "",
        "Porcentaje vacío. En accords, notas y perfumista, vacío incluye lista vacía.",
        "En estación, día y noche no hay nulos: un 0 es «no marcado».",
        "",
        _nulls(reviews, kept, items_all, items_kept),
        "",
        "## Distribución",
        "",
        *_distributions(reviews, kept, items_all, items_kept),
    ]
    return "\n".join(lines) + "\n"


def _size(reviews, kept):
    rows = [
        ("reviews", len(reviews), len(kept)),
        ("usuarios", reviews.member_id.nunique(), kept.member_id.nunique()),
        ("perfumes", reviews.perfume_id.nunique(), kept.perfume_id.nunique()),
    ]
    lines = ["| | universo | matriz | se elimina |", "|---|---:|---:|---:|"]
    for name, before, after in rows:
        lines.append(f"| {name} | {before} | {after} | {before - after} ({_pct(before - after, before)}) |")
    density_before = len(reviews) / (reviews.member_id.nunique() * reviews.perfume_id.nunique())
    density_after = len(kept) / (kept.member_id.nunique() * kept.perfume_id.nunique())
    lines.append(f"| densidad | {density_before:.2%} | {density_after:.2%} | |")
    return "\n".join(lines)


def _cut_sentence(reviews, kept):
    dropped_users = ~reviews.member_id.isin(set(kept.member_id))
    dropped_items = ~reviews.perfume_id.isin(set(kept.perfume_id))
    user_degree = reviews[dropped_users].groupby("member_id").size()
    item_degree = reviews[dropped_items].groupby("perfume_id").size()
    return (
        f"Salen usuarios con pocas reviews (p50 {user_degree.median():.0f}) "
        f"y perfumes con pocas reviews (p50 {item_degree.median():.0f})."
    )


def _nulls(reviews, kept, items_all, items_kept):
    lines = ["| feature | universo | matriz |", "|---|---:|---:|"]
    for column in ["rating", "timestamp", "longevity", "sillage", "gender_vote"]:
        lines.append(_null_row(column, reviews[column], kept[column]))
    for column in ["brand", "gender", "olfactive_family", "launch_year"]:
        lines.append(_null_row(column, items_all[column], items_kept[column]))
    lines.append(_null_row("perfumers", items_all.perfumers.map(_empty), items_kept.perfumers.map(_empty)))
    lines.append(_null_row("accords", items_all.accords.map(_empty), items_kept.accords.map(_empty)))
    lines.append(_null_row("notes", items_all.notes.map(_empty), items_kept.notes.map(_empty)))
    return "\n".join(lines)


def _null_row(name, before, after):
    return f"| {name} | {_pct(before.isna().sum(), len(before))} | {_pct(after.isna().sum(), len(after))} |"


def _distributions(reviews, kept, items_all, items_kept):
    return [
        "**Rating.** " + _share(reviews.rating, kept.rating),
        "",
        "**Longevidad**, entre las que tienen valor. " + _share(reviews.longevity.dropna(), kept.longevity.dropna()),
        "",
        "**Estela**, entre las que tienen valor. " + _share(reviews.sillage.dropna(), kept.sillage.dropna()),
        "",
        "**Estación.** Share de reviews con la estación marcada. "
        + _flags(reviews, kept, SEASONS)
        + f" Sin ninguna: {_pct(_none(reviews, SEASONS), len(reviews))} universo, "
        + f"{_pct(_none(kept, SEASONS), len(kept))} matriz.",
        "",
        "**Día y noche.** "
        + _flags(reviews, kept, ["day", "night"])
        + f" Sin ninguno: {_pct(_none(reviews, ['day', 'night']), len(reviews))} universo, "
        + f"{_pct(_none(kept, ['day', 'night']), len(kept))} matriz.",
        "",
        "**Año de la review.** " + _years(reviews, kept),
        "",
        "**Género del perfume.** " + _share(items_all.gender.fillna("nulo"), items_kept.gender.fillna("nulo")),
        "",
        "**Familia olfativa.** "
        + f"{items_all.olfactive_family.nunique(dropna=True)} en el universo, "
        + f"{items_kept.olfactive_family.nunique(dropna=True)} en la matriz. "
        + "Las más frecuentes en la matriz: "
        + _top(items_kept.olfactive_family.fillna("nulo")),
        "",
        "**Marca.** "
        + f"{items_all.brand.nunique(dropna=True)} en el universo, "
        + f"{items_kept.brand.nunique(dropna=True)} en la matriz. "
        + "Las más frecuentes en la matriz: "
        + _top(items_kept.brand.fillna("nulo")),
        "",
        "**Año de lanzamiento.** " + _numeric(items_all.launch_year, items_kept.launch_year),
        "",
        "**Perfumista.** " + _lists(items_all.perfumers, items_kept.perfumers, "name"),
        "",
        "**Accords.** " + _lists(items_all.accords, items_kept.accords, "name"),
        "",
        "**Notas.** " + _lists(items_all.notes, items_kept.notes, "name"),
    ]


def _share(before, after):
    values = sorted(set(before.dropna().unique()) | set(after.dropna().unique()), key=str)
    parts = []
    for value in values:
        label = int(value) if isinstance(value, (float, np.floating)) and float(value).is_integer() else value
        parts.append(f"{label} {_pct((before == value).sum(), len(before))} / {_pct((after == value).sum(), len(after))}")
    return "Universo / matriz: " + ", ".join(parts) + "."


def _flags(before, after, columns):
    parts = []
    for column in columns:
        name = column.replace("season_", "")
        parts.append(
            f"{name} {_pct((before[column] == 1).sum(), len(before))} / {_pct((after[column] == 1).sum(), len(after))}"
        )
    return "Universo / matriz: " + ", ".join(parts) + "."


def _years(before, after):
    first = pd.to_datetime(before.timestamp, unit="s")
    second = pd.to_datetime(after.timestamp, unit="s")
    return (
        f"{first.dt.year.min()}–{first.dt.year.max()}. "
        f"Desde 2023: {_pct((first.dt.year >= 2023).sum(), len(first))} universo, "
        f"{_pct((second.dt.year >= 2023).sum(), len(second))} matriz."
    )


def _numeric(before, after):
    def brief(series):
        present = series.dropna()
        return f"p50 {present.median():.0f}, {present.min():.0f}–{present.max():.0f}"

    return f"Universo: {brief(before)}. Matriz: {brief(after)}."


def _lists(before, after, key):
    def brief(series):
        parsed = series.map(lambda value: _entries(value, key))
        counts = parsed.map(len)
        names = pd.Series([name for row in parsed for name in row])
        top = ", ".join(f"{name} ({count})" for name, count in names.value_counts().head(5).items())
        return f"p50 {counts.median():.0f} por perfume. Top: {top}"

    return f"Universo: {brief(before)}. Matriz: {brief(after)}."


def _entries(value, key):
    parsed = _parse(value)
    names = []
    for entry in parsed:
        if isinstance(entry, str):
            names.append(entry)
        elif isinstance(entry, dict) and entry.get(key) is not None:
            names.append(str(entry[key]))
    return names


def _parse(value):
    if value is None or value is pd.NA:
        return []
    if isinstance(value, float) and np.isnan(value):
        return []
    if isinstance(value, str):
        return json.loads(value) if value and value != "[]" else []
    return list(value)


def _empty(value):
    return np.nan if not _parse(value) else value


def _none(df, columns):
    return int((df[columns].fillna(0).sum(axis=1) == 0).sum())


def _top(series, n=5):
    counts = series.value_counts().head(n)
    return ", ".join(f"{name} ({count})" for name, count in counts.items()) + "."


def _pct(part, total):
    if not total:
        return "0%"
    return f"{part / total:.1%}"


if __name__ == "__main__":
    print(write_report())
