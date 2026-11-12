import warnings

import numpy as np

import config

# NumPy 2 en macOS avisa en matmul aunque el resultado sea finito.
warnings.filterwarnings("ignore", message=".*encountered in matmul", category=RuntimeWarning)
from data import gain


def popularity(train, n_users, n_items):
    age_days = (train.timestamp.max() - train.timestamp) / 86400.0
    weights = gain(train.rating) * np.exp(-age_days / config.POPULARITY_HALF_LIFE_DAYS)
    scores = np.zeros(n_items, dtype=np.float64)
    np.add.at(scores, train.item.to_numpy(), weights)
    return np.tile(scores, (n_users, 1))


def ease(matrix):
    gram = matrix.T @ matrix
    gram.flat[:: gram.shape[0] + 1] += config.EASE_L2
    precision = np.linalg.inv(gram)
    weights = precision / -np.diag(precision)
    np.fill_diagonal(weights, 0.0)
    return matrix @ weights


def item_knn(matrix):
    norms = np.linalg.norm(matrix, axis=0)
    norms[norms == 0] = 1.0
    similarity = (matrix / norms).T @ (matrix / norms)
    np.fill_diagonal(similarity, 0.0)
    k = min(config.ITEM_KNN_K, similarity.shape[0] - 1)
    chosen = np.argpartition(-similarity, k, axis=1)[:, :k]
    mask = np.zeros_like(similarity)
    mask[np.arange(similarity.shape[0])[:, None], chosen] = 1.0
    return matrix @ (similarity * mask)


def als(train, n_users, n_items):
    rng = np.random.default_rng(config.SEED)
    factors = config.ALS_FACTORS
    user_factors = rng.normal(0, 0.1, size=(n_users, factors))
    item_factors = rng.normal(0, 0.1, size=(n_items, factors))
    weights = gain(train.rating) * config.ALS_ALPHA
    by_user = _groups(n_users, train.user.to_numpy(), train.item.to_numpy(), weights)
    by_item = _groups(n_items, train.item.to_numpy(), train.user.to_numpy(), weights)
    for _ in range(config.ALS_ITERATIONS):
        user_factors = _solve(item_factors, by_user, config.ALS_REGULARIZATION)
        item_factors = _solve(user_factors, by_item, config.ALS_REGULARIZATION)
    return user_factors @ item_factors.T


def matrix(train, n_users, n_items):
    values = np.zeros((n_users, n_items), dtype=np.float64)
    values[train.user.to_numpy(), train.item.to_numpy()] = gain(train.rating)
    return values


def _groups(n, keys, values, weights):
    members = [[] for _ in range(n)]
    confidence = [[] for _ in range(n)]
    for key, value, weight in zip(keys, values, weights):
        members[int(key)].append(int(value))
        confidence[int(key)].append(float(weight))
    return [
        (np.asarray(group, dtype=np.int32), np.asarray(extra, dtype=np.float64))
        for group, extra in zip(members, confidence)
    ]


def _solve(factors, groups, regularization):
    width = factors.shape[1]
    gram = factors.T @ factors
    eye = regularization * np.eye(width)
    solved = np.zeros((len(groups), width))
    for row, (index, extra) in enumerate(groups):
        if len(index) == 0:
            continue
        chosen = factors[index]
        confidence = 1.0 + extra
        left = gram + (chosen * (confidence - 1.0)[:, None]).T @ chosen + eye
        right = (chosen * confidence[:, None]).sum(axis=0)
        solved[row] = np.linalg.solve(left, right)
    return solved
