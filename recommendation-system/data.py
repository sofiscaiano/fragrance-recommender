import hashlib
import json

import numpy as np
import pandas as pd

import config

COLUMNS = ["member_id", "perfume_id", "rating", "timestamp"]


def gain(rating):
    return np.power(2.0, np.asarray(rating, dtype=np.float64)) - 1.0


def load_reviews():
    df = pd.read_parquet(config.DATA_DIR / "interactions.parquet", columns=COLUMNS)
    df = df[df.timestamp.notna() & df.rating.notna()]
    df = df.drop_duplicates(["member_id", "perfume_id"])
    return df.reset_index(drop=True)


def kcore(df, min_user, min_item):
    current = df
    while True:
        user_count = current.groupby("member_id").size()
        item_count = current.groupby("perfume_id").size()
        users = user_count[user_count >= min_user].index
        items = item_count[item_count >= min_item].index
        nxt = current[current.member_id.isin(users) & current.perfume_id.isin(items)]
        if len(nxt) == len(current) or len(nxt) == 0:
            return nxt.reset_index(drop=True)
        current = nxt


def filtered_matrix(cut=None):
    cut = cut or config.ACTIVE_CUT
    floors = config.CUTS[cut]
    return kcore(load_reviews(), floors["min_user"], floors["min_item"])


def assign_split(df):
    ordered = df.sort_values(["member_id", "timestamp", "perfume_id"])
    rank = ordered.groupby("member_id").cumcount(ascending=False)
    k = config.HOLDOUT_K
    split = np.where(rank < k, "test", np.where(rank < 2 * k, "val", "train"))
    ordered = ordered.copy()
    ordered["split"] = split
    return ordered.reset_index(drop=True)


def _indexes(matrix):
    users = np.sort(matrix.member_id.unique())
    items = np.sort(matrix.perfume_id.unique())
    user_index = {int(user): i for i, user in enumerate(users)}
    item_index = {int(item): i for i, item in enumerate(items)}
    return users, items, user_index, item_index


def _encode(df, user_index, item_index):
    out = df.copy()
    out["user"] = out.member_id.map(user_index).astype(np.int32)
    out["item"] = out.perfume_id.map(item_index).astype(np.int32)
    return out


def prepare():
    matrix = assign_split(filtered_matrix())
    counts = matrix.groupby("member_id").size()
    if int(counts.min()) < 2 * config.HOLDOUT_K:
        raise SystemExit("el corte deja usuarios sin 10 reviews de validación y 10 de test")

    config.SPLITS_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("train", "val", "test"):
        part = matrix[matrix.split == name].drop(columns="split")
        part.to_parquet(config.SPLITS_DIR / f"{name}.parquet", index=False)

    test_path = config.SPLITS_DIR / "test.parquet"
    digest = hashlib.sha256(test_path.read_bytes()).hexdigest()
    manifest = {
        "cut": config.ACTIVE_CUT,
        "train_rows": int((matrix.split == "train").sum()),
        "val_rows": int((matrix.split == "val").sum()),
        "test_rows": int((matrix.split == "test").sum()),
        "test_sha256": digest,
        "note": "el test no se evalúa",
    }
    (config.SPLITS_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))

    users, items, user_index, item_index = _indexes(matrix)
    train = _encode(matrix[matrix.split == "train"], user_index, item_index)
    val = _encode(matrix[matrix.split == "val"], user_index, item_index)
    return {
        "train": train,
        "val": val,
        "users": users,
        "items": items,
        "n_users": len(users),
        "n_items": len(items),
    }
