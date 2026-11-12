import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT.parent / "scraper" / "data" / "final"
SPLITS_DIR = ROOT / "splits"
REPORTS_DIR = ROOT / "reports"
CHOSEN_PATH = ROOT / "chosen.json"
MLFLOW_DB = ROOT / "mlflow.db"
MLFLOW_ARTIFACTS = ROOT / "mlartifacts"
MLFLOW_URI = f"sqlite:///{MLFLOW_DB}"
MLFLOW_EXPERIMENT = "fragrantica"

SEED = 7
HOLDOUT_K = 10
NDCG_K = 10

CUTS = {
    "28_60": {"min_user": 28, "min_item": 60},
    "22_80": {"min_user": 22, "min_item": 80},
    "30_60": {"min_user": 30, "min_item": 60},
}
ACTIVE_CUT = "28_60"

POPULARITY_HALF_LIFE_DAYS = 730
POPULARITY_HALF_LIFE_GRID = [30, 90, 180, 365, 730]
EASE_L2 = 5000.0
EASE_L2_GRID = [1.0, 10.0, 50.0, 100.0, 500.0, 1000.0, 5000.0]
ITEM_KNN_K = 200
ITEM_KNN_K_GRID = [10, 20, 50, 100, 200]
ALS_FACTORS = 16
ALS_FACTORS_GRID = [16, 32, 64]
ALS_REGULARIZATION = 1.0
ALS_REGULARIZATION_GRID = [0.01, 0.1, 1.0]
ALS_ITERATIONS = 15
ALS_ALPHA = 1.0
ALS_ALPHA_GRID = [1.0, 10.0, 40.0]

TWO_TOWER_DIM = 32
TWO_TOWER_DIM_GRID = [32, 64, 128]
TWO_TOWER_NEGATIVES = 64
TWO_TOWER_NEGATIVES_GRID = [32, 64, 128]
TWO_TOWER_EPOCHS = 15
TWO_TOWER_MAX_EPOCHS = 50
TWO_TOWER_PATIENCE = 4
TWO_TOWER_LR = 3e-3
TWO_TOWER_LR_GRID = [1e-4, 3e-4, 1e-3, 3e-3]
TWO_TOWER_BATCH_SIZE = 2048
TWO_TOWER_HISTORY = 20
TWO_TOWER_HISTORY_GRID = [10, 20, 30, 50]
TWO_TOWER_BEST_EPOCH = None

TUNED = (
    "POPULARITY_HALF_LIFE_DAYS",
    "EASE_L2",
    "ITEM_KNN_K",
    "ALS_FACTORS",
    "ALS_REGULARIZATION",
    "ALS_ALPHA",
    "TWO_TOWER_LR",
    "TWO_TOWER_DIM",
    "TWO_TOWER_NEGATIVES",
    "TWO_TOWER_HISTORY",
)

BASELINE = "popularity"

MODELS = [
    "popularity",
    "ease",
    "item_knn",
    "als",
    "two_tower",
    #"two_tower_id",
]


def use_chosen():
    values = _read_chosen().get(ACTIVE_CUT, {})
    applied = {}
    for key in TUNED:
        if values.get(key) is None:
            continue
        globals()[key] = values[key]
        applied[key] = values[key]
    return applied


def save_chosen(values):
    saved = _read_chosen()
    current = saved.get(ACTIVE_CUT, {})
    for key in TUNED:
        if values.get(key) is None:
            continue
        current[key] = values[key]
    saved[ACTIVE_CUT] = current
    CHOSEN_PATH.write_text(json.dumps(saved, indent=2) + "\n")


def _read_chosen():
    if not CHOSEN_PATH.exists():
        return {}
    return json.loads(CHOSEN_PATH.read_text())
