import json
import os

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

import mlflow

import config
from baselines import als, ease, item_knn, matrix, popularity
from data import prepare
from eda import write_report
from metrics import evaluate
from model import two_tower

BASELINES = ("popularity", "ease", "item_knn", "als")


def main():
    applied = config.use_chosen()
    if applied:
        print(f"hiperparámetros de {config.CHOSEN_PATH.name} corte {config.ACTIVE_CUT}")
    report = write_report()
    bundle = prepare()
    print(
        f"train {len(bundle['train'])} val {len(bundle['val'])} "
        f"usuarios {bundle['n_users']} perfumes {bundle['n_items']}"
    )
    _print_test_seal()
    results = [_run(name, bundle, report) for name in config.MODELS]
    reference = _reference(results, bundle, report)
    _report(results, reference)
    _decision(results)


def _fit(name, bundle):
    train = bundle["train"]
    n_users, n_items = bundle["n_users"], bundle["n_items"]
    if name == "popularity":
        return popularity(train, n_users, n_items)
    values = matrix(train, n_users, n_items)
    if name == "ease":
        return ease(values)
    if name == "item_knn":
        return item_knn(values)
    if name == "als":
        return als(train, n_users, n_items)
    if name == "two_tower":
        return two_tower(train, n_users, n_items, bundle["items"], use_content=True, val=bundle["val"])
    if name == "two_tower_id":
        return two_tower(train, n_users, n_items, bundle["items"], use_content=False, val=bundle["val"])
    raise SystemExit(f"modelo desconocido: {name}")


def _run(name, bundle, report):
    print(name)
    scores = _fit(name, bundle)
    metrics = evaluate(scores, bundle["val"], bundle["train"])
    if any("test" in key for key in metrics):
        raise SystemExit("una métrica de test no se puede loguear")
    print(name, _format(metrics))
    _log(name, metrics, report, bundle)
    return name, metrics


def _reference(results, bundle, report):
    found = dict(results)
    if config.BASELINE in found:
        return config.BASELINE, found[config.BASELINE]
    return _run(config.BASELINE, bundle, report)


def _report(results, reference):
    name, baseline = reference
    print(f"baseline {name} {_format(baseline)}")
    for model, metrics in results:
        if model == name:
            continue
        delta = " ".join(f"{key} {metrics[key] - baseline[key]:+.4f}" for key in metrics)
        print(f"{model} vs {name} {delta}")


def _log(name, metrics, report, bundle, run_name=None, tags=None):
    mlflow.set_tracking_uri(config.MLFLOW_URI)
    config.MLFLOW_ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if mlflow.get_experiment_by_name(config.MLFLOW_EXPERIMENT) is None:
        mlflow.create_experiment(
            config.MLFLOW_EXPERIMENT,
            artifact_location=config.MLFLOW_ARTIFACTS.resolve().as_uri(),
        )
    mlflow.set_experiment(config.MLFLOW_EXPERIMENT)
    with mlflow.start_run(run_name=run_name or name):
        if tags:
            mlflow.set_tags(tags)
        mlflow.log_params(_params(name, bundle))
        mlflow.log_metrics({key.replace("@", "_at_"): value for key, value in metrics.items()})
        mlflow.log_artifact(str(report))


def _params(name, bundle):
    floors = config.CUTS[config.ACTIVE_CUT]
    params = {
        "model": name,
        "cut": config.ACTIVE_CUT,
        "min_user": floors["min_user"],
        "min_item": floors["min_item"],
        "seed": config.SEED,
        "holdout_k": config.HOLDOUT_K,
        "ndcg_k": config.NDCG_K,
        "n_users": bundle["n_users"],
        "n_items": bundle["n_items"],
        "n_train": len(bundle["train"]),
        "n_val": len(bundle["val"]),
        "baseline": config.BASELINE,
    }
    if name == "popularity":
        params["half_life_days"] = config.POPULARITY_HALF_LIFE_DAYS
    elif name == "ease":
        params["l2"] = config.EASE_L2
    elif name == "item_knn":
        params["neighbors"] = config.ITEM_KNN_K
    elif name == "als":
        params["factors"] = config.ALS_FACTORS
        params["regularization"] = config.ALS_REGULARIZATION
        params["iterations"] = config.ALS_ITERATIONS
        params["alpha"] = config.ALS_ALPHA
    elif name.startswith("two_tower"):
        params["dim"] = config.TWO_TOWER_DIM
        params["negatives"] = config.TWO_TOWER_NEGATIVES
        params["epochs"] = config.TWO_TOWER_BEST_EPOCH or config.TWO_TOWER_EPOCHS
        params["lr"] = config.TWO_TOWER_LR
        params["batch_size"] = config.TWO_TOWER_BATCH_SIZE
        params["history"] = config.TWO_TOWER_HISTORY
        params["use_content"] = name == "two_tower"
    return params


def _decision(results):
    found = dict(results)
    baseline = {name: metrics for name, metrics in results if name in BASELINES}
    if not baseline or "two_tower" not in found:
        return
    best_recall = max(baseline, key=lambda name: baseline[name]["recall@10"])
    best_ndcg = max(baseline, key=lambda name: baseline[name]["ndcg@10"])
    tower = found["two_tower"]
    recall_wins = tower["recall@10"] > baseline[best_recall]["recall@10"]
    ndcg_short = tower["ndcg@10"] <= baseline[best_ndcg]["ndcg@10"]
    print(f"mejor baseline recall: {best_recall} {_format(baseline[best_recall])}")
    print(f"mejor baseline ndcg: {best_ndcg} {_format(baseline[best_ndcg])}")
    if recall_wins and ndcg_short:
        print("two_tower gana recall y no gana ndcg: el orden entre notas queda para un ranker")
        return
    print("sin ranker aparte: two_tower no dejó recall ganado y ndcg corto a la vez")


def _format(metrics):
    return " ".join(f"{key} {value:.4f}" for key, value in metrics.items())


def _print_test_seal():
    manifest = json.loads((config.SPLITS_DIR / "manifest.json").read_text())
    print(f"test reservado: {manifest['test_rows']} filas, sha {manifest['test_sha256'][:12]}")


if __name__ == "__main__":
    main()
