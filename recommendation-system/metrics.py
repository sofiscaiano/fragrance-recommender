import numpy as np

import config
from data import gain


def evaluate(scores, val, train, k=None):
    k = config.NDCG_K if k is None else k
    masked = np.array(scores, dtype=np.float64, copy=True)
    masked[train.user.to_numpy(), train.item.to_numpy()] = -np.inf

    n_users, n_items = masked.shape
    relevance = np.zeros((n_users, n_items), dtype=np.float64)
    relevance[val.user.to_numpy(), val.item.to_numpy()] = gain(val.rating.to_numpy())

    top = _top_k(masked, k)
    rows = np.arange(n_users)[:, None]
    gained = relevance[rows, top]
    discounts = 1.0 / np.log2(np.arange(2, k + 2))
    dcg = (gained * discounts).sum(axis=1)

    order = np.argsort(-relevance, axis=1)[:, :k]
    ideal = relevance[rows, order]
    idcg = (ideal * discounts).sum(axis=1)
    keep = idcg > 0
    ndcg = float((dcg[keep] / idcg[keep]).mean())

    n_relevant = (relevance > 0).sum(axis=1)
    hits = (gained > 0).sum(axis=1)
    recall = float((hits[keep] / n_relevant[keep]).mean())
    coverage = float(len(np.unique(top[keep])) / n_items)
    return {"ndcg@10": ndcg, "recall@10": recall, "coverage@10": coverage}


def _top_k(scores, k):
    chosen = np.argpartition(-scores, k, axis=1)[:, :k]
    rows = np.arange(scores.shape[0])[:, None]
    order = np.argsort(-scores[rows, chosen], axis=1)
    return chosen[rows, order]


def _self_check():
    scores = np.array([[3.0, 2.0, 0.0], [0.0, 5.0, 4.0]])
    val = _frame([(0, 0, 5.0), (0, 1, 1.0), (1, 1, 5.0), (1, 2, 4.0)])
    train = _frame([(0, 2, 1.0)])
    metrics = evaluate(scores, val, train, k=2)
    perfect = (gain(5) + gain(4) / np.log2(3)) / (gain(5) + gain(4) / np.log2(3))
    first = (gain(5) + gain(1) / np.log2(3)) / (gain(5) + gain(1) / np.log2(3))
    assert abs(metrics["ndcg@10"] - (first + perfect) / 2) < 1e-9
    assert abs(metrics["recall@10"] - 1.0) < 1e-9


def _frame(rows):
    import pandas as pd

    return pd.DataFrame(rows, columns=["user", "item", "rating"])
