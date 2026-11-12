import json

import numpy as np
import pandas as pd
import torch
from torch import nn

import config
from data import gain
from metrics import evaluate


def two_tower(train, n_users, n_items, item_ids, use_content, val=None):
    torch.manual_seed(config.SEED)
    content = _content(item_ids) if use_content else None
    model = _Tower(n_items, content)
    optimizer = torch.optim.Adam(model.parameters(), lr=config.TWO_TOWER_LR)
    _, positives, ratings, history = _examples(train)
    weights = torch.tensor(gain(ratings), dtype=torch.float32)
    history = torch.tensor(history, dtype=torch.long)
    positives = torch.tensor(positives, dtype=torch.long)
    generator = torch.Generator().manual_seed(config.SEED)
    epochs = config.TWO_TOWER_MAX_EPOCHS if val is not None else config.TWO_TOWER_EPOCHS
    best_state = None
    best_ndcg = -1.0
    best_epoch = 0
    stale = 0

    for epoch in range(epochs):
        model.train()
        order = torch.randperm(len(positives), generator=generator)
        total = 0.0
        seen = 0
        for start in range(0, len(order), config.TWO_TOWER_BATCH_SIZE):
            batch = order[start : start + config.TWO_TOWER_BATCH_SIZE]
            loss = _loss(model, history[batch], positives[batch], weights[batch], n_items)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total += loss.detach().item() * len(batch)
            seen += len(batch)
        message = f"two_tower content={use_content} epoch {epoch + 1} loss {total / seen:.4f}"
        if val is None:
            print(message)
            continue
        scores = _score(model, train, n_users)
        ndcg = evaluate(scores, val, train)["ndcg@10"]
        print(f"{message} ndcg@10 {ndcg:.4f}")
        if ndcg > best_ndcg:
            best_ndcg = ndcg
            best_epoch = epoch + 1
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= config.TWO_TOWER_PATIENCE:
                break

    config.TWO_TOWER_BEST_EPOCH = best_epoch or epochs
    if best_state is not None:
        model.load_state_dict(best_state)
    return _score(model, train, n_users)


def _score(model, train, n_users):
    model.eval()
    with torch.no_grad():
        users = model.user_vectors(torch.tensor(_eval_history(train, n_users)))
        return (users @ model.item_vectors().T).numpy()


def _loss(model, history, positives, weights, n_items):
    vectors = model.item_vectors()
    users = model.user_vectors(history)
    positive = vectors[positives]
    negatives = torch.randint(0, n_items, (len(positives), config.TWO_TOWER_NEGATIVES))
    clash = negatives == positives[:, None]
    negatives = torch.where(clash, torch.randint(0, n_items, negatives.shape), negatives)
    negative = vectors[negatives]
    positive_logit = (users * positive).sum(dim=1, keepdim=True)
    negative_logit = (users.unsqueeze(1) * negative).sum(dim=2)
    logits = torch.cat([positive_logit, negative_logit], dim=1)
    loss = nn.functional.cross_entropy(logits, torch.zeros(len(positives), dtype=torch.long), reduction="none")
    return (loss * weights).sum() / weights.sum()


class _Tower(nn.Module):
    def __init__(self, n_items, content):
        super().__init__()
        dim = config.TWO_TOWER_DIM
        self.item = nn.Embedding(n_items, dim)
        self.user = nn.Linear(dim, dim)
        if content is None:
            self.proj = None
            return
        self.proj = nn.Linear(content.shape[1], dim, bias=False)
        self.register_buffer("content", torch.tensor(content, dtype=torch.float32))

    def item_vectors(self):
        vectors = self.item.weight
        if self.proj is not None:
            vectors = vectors + self.proj(self.content)
        return vectors

    def user_vectors(self, history):
        gathered = self.item_vectors()[history.clamp(min=0)]
        mask = (history >= 0).unsqueeze(-1)
        mean = (gathered * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
        return self.user(mean)


def _examples(train):
    width = config.TWO_TOWER_HISTORY
    users, positives, ratings, histories = [], [], [], []
    for user, group in train.groupby("user", sort=False):
        group = group.sort_values("timestamp")
        items = group.item.to_numpy()
        notes = group.rating.to_numpy()
        for index in range(1, len(items)):
            past = items[max(0, index - width) : index]
            padded = np.full(width, -1, dtype=np.int64)
            padded[-len(past) :] = past
            users.append(int(user))
            positives.append(int(items[index]))
            ratings.append(float(notes[index]))
            histories.append(padded)
    return (
        np.asarray(users),
        np.asarray(positives),
        np.asarray(ratings),
        np.stack(histories),
    )


def _eval_history(train, n_users):
    width = config.TWO_TOWER_HISTORY
    history = np.full((n_users, width), -1, dtype=np.int64)
    for user, group in train.groupby("user", sort=False):
        items = group.sort_values("timestamp").item.to_numpy()[-width:]
        history[int(user), -len(items) :] = items
    return history


def _content(item_ids):
    raw = pd.read_parquet(
        config.DATA_DIR / "items.parquet",
        columns=["perfume_id", "brand", "gender", "olfactive_family", "launch_year", "accords", "notes"],
    )
    table = raw.set_index("perfume_id").reindex(item_ids).reset_index()
    categories = pd.get_dummies(
        table[["brand", "gender", "olfactive_family"]].fillna("unknown"),
        dtype=np.float32,
    )
    year = table.launch_year.fillna(table.launch_year.median()).fillna(0).to_numpy(dtype=np.float32)
    year = (year - year.mean()) / (year.std() or 1.0)
    features = [
        categories.to_numpy(dtype=np.float32),
        year[:, None].astype(np.float32),
        _bag(table.accords, "name", "intensity", 40),
        _bag(table.notes, "note_id", None, 64),
    ]
    return np.concatenate(features, axis=1)


def _bag(series, key, weight, limit):
    parsed = [_parse(value) for value in series]
    totals = {}
    for row in parsed:
        for entry in row:
            name = entry.get(key)
            if name is None:
                continue
            totals[name] = totals.get(name, 0.0) + float(entry.get(weight) or 1.0)
    kept = [name for name, _ in sorted(totals.items(), key=lambda item: -item[1])[:limit]]
    index = {name: i for i, name in enumerate(kept)}
    bag = np.zeros((len(parsed), len(kept)), dtype=np.float32)
    for row_index, row in enumerate(parsed):
        for entry in row:
            column = index.get(entry.get(key))
            if column is None:
                continue
            bag[row_index, column] = float(entry.get(weight) or 1.0) if weight else 1.0
    if bag.size == 0:
        return np.zeros((len(parsed), 1), dtype=np.float32)
    scale = bag.max() or 1.0
    return bag / scale


def _parse(value):
    if value is None or value is pd.NA:
        return []
    if isinstance(value, float) and np.isnan(value):
        return []
    if isinstance(value, str):
        return json.loads(value) if value else []
    return list(value)
