import math

import config
from data import prepare
from eda import write_report
from metrics import evaluate
from run import _fit, _format, _log, _print_test_seal


def main():
    report = write_report()
    bundle = prepare()
    _print_test_seal()
    chosen = {
        "popularity": _sweep(bundle, report, "popularity", "POPULARITY_HALF_LIFE_DAYS", config.POPULARITY_HALF_LIFE_GRID),
        "ease": _sweep(bundle, report, "ease", "EASE_L2", config.EASE_L2_GRID),
        "item_knn": _sweep(bundle, report, "item_knn", "ITEM_KNN_K", config.ITEM_KNN_K_GRID),
        "als": _sweep_als(bundle, report),
        "two_tower": _sweep_tower(bundle, report),
    }
    print("mejores por NDCG@10 de validación")
    for name, (value, metrics) in chosen.items():
        print(f"{name} {value} {_format(metrics)}")
    config.save_chosen(_flat(chosen))
    print(f"guardados en {config.CHOSEN_PATH.name} corte {config.ACTIVE_CUT}")


def _sweep(bundle, report, name, attr, values):
    best_value = None
    best_metrics = None
    for value in values:
        setattr(config, attr, value)
        metrics = _trial(bundle, report, name, f"{name}/{attr}={value}")
        best_value, best_metrics = _keep(best_value, best_metrics, value, metrics)
    setattr(config, attr, best_value)
    print(f"mejor {name}: {attr}={best_value} {_format(best_metrics)}")
    return best_value, best_metrics


def _sweep_als(bundle, report):
    best = None
    best_metrics = None
    for factors in config.ALS_FACTORS_GRID:
        for regularization in config.ALS_REGULARIZATION_GRID:
            for alpha in config.ALS_ALPHA_GRID:
                config.ALS_FACTORS = factors
                config.ALS_REGULARIZATION = regularization
                config.ALS_ALPHA = alpha
                label = f"als/f{factors}_r{regularization}_a{alpha}"
                metrics = _trial(bundle, report, "als", label)
                point = {"factors": factors, "regularization": regularization, "alpha": alpha}
                if metrics is None:
                    continue
                if best_metrics is None or metrics["ndcg@10"] > best_metrics["ndcg@10"]:
                    best, best_metrics = point, metrics
    config.ALS_FACTORS = best["factors"]
    config.ALS_REGULARIZATION = best["regularization"]
    config.ALS_ALPHA = best["alpha"]
    print(f"mejor als: {best} {_format(best_metrics)}")
    return best, best_metrics


def _sweep_tower(bundle, report):
    stages = [
        ("TWO_TOWER_LR", config.TWO_TOWER_LR_GRID),
        ("TWO_TOWER_DIM", config.TWO_TOWER_DIM_GRID),
        ("TWO_TOWER_NEGATIVES", config.TWO_TOWER_NEGATIVES_GRID),
        ("TWO_TOWER_HISTORY", config.TWO_TOWER_HISTORY_GRID),
    ]
    chosen = {}
    best_metrics = None
    for attr, values in stages:
        best_value = None
        stage_metrics = None
        for value in values:
            setattr(config, attr, value)
            metrics = _trial(bundle, report, "two_tower", f"two_tower/{attr}={value}")
            best_value, stage_metrics = _keep(best_value, stage_metrics, value, metrics)
        setattr(config, attr, best_value)
        chosen[attr] = best_value
        best_metrics = stage_metrics
        print(f"mejor two_tower {attr}={best_value} {_format(best_metrics)}")
    id_metrics = _trial(bundle, report, "two_tower_id", "two_tower_id/best")
    print(f"two_tower_id en el punto elegido {_format(id_metrics)}")
    return chosen, best_metrics


def _trial(bundle, report, name, label):
    scores = _fit(name, bundle)
    metrics = evaluate(scores, bundle["val"], bundle["train"])
    if not math.isfinite(metrics["ndcg@10"]):
        print(label, "ndcg no finito")
        return None
    print(label, _format(metrics))
    _log(name, metrics, report, bundle, run_name=label, tags={"search": "grid"})
    return metrics


def _flat(chosen):
    popularity, _ = chosen["popularity"]
    ease, _ = chosen["ease"]
    item_knn, _ = chosen["item_knn"]
    als, _ = chosen["als"]
    tower, _ = chosen["two_tower"]
    values = {
        "POPULARITY_HALF_LIFE_DAYS": popularity,
        "EASE_L2": ease,
        "ITEM_KNN_K": item_knn,
    }
    if als is not None:
        values["ALS_FACTORS"] = als["factors"]
        values["ALS_REGULARIZATION"] = als["regularization"]
        values["ALS_ALPHA"] = als["alpha"]
    values.update(tower)
    return values


def _keep(best_value, best_metrics, value, metrics):
    if metrics is None:
        return best_value, best_metrics
    if best_metrics is None or metrics["ndcg@10"] > best_metrics["ndcg@10"]:
        return value, metrics
    return best_value, best_metrics


if __name__ == "__main__":
    main()
