from __future__ import annotations

import pandas as pd

from fragrantica_rec.metrics import (
    ndcg_at_k,
    retrieval_hits,
    retrieval_metrics,
    rows_against_reference,
)


def test_ndcg_penalizes_relevant_items_not_retrieved() -> None:
    truth = pd.DataFrame(
        {
            "member_id": ["u", "u"],
            "perfume_id": ["relevant-10", "relevant-8"],
            "rating": [5, 4],
        }
    )
    perfect = pd.DataFrame(
        {
            "member_id": ["u", "u"],
            "perfume_id": ["relevant-10", "relevant-8"],
            "rank": [1, 2],
        }
    )
    missing = pd.DataFrame(
        {
            "member_id": ["u", "u"],
            "perfume_id": ["relevant-10", "irrelevant"],
            "rank": [1, 2],
        }
    )

    assert ndcg_at_k(perfect, truth, k=2) == 1.0
    assert 0.0 < ndcg_at_k(missing, truth, k=2) < 1.0


def test_retrieval_metrics_report_binary_weighted_and_oracle() -> None:
    truth = pd.DataFrame(
        {
            "member_id": ["u", "u"],
            "perfume_id": ["high", "low"],
            "rating": [5, 1],
        }
    )
    candidates = pd.DataFrame(
        {
            "member_id": ["u"],
            "perfume_id": ["high"],
            "rrf_score": [1.0],
        }
    )
    metrics = retrieval_metrics(candidates, truth)

    hits = retrieval_hits(candidates, truth)
    marked = dict(zip(hits["perfume_id"], hits["in_retrieval"], strict=True))
    assert marked == {"high": 1, "low": 0}

    assert metrics.recall == 0.5
    assert metrics.weighted_recall == 5 / 6
    assert 0 < metrics.oracle_ndcg < 1


def test_ablation_rows_include_the_reference_and_the_drop() -> None:
    rows = rows_against_reference(
        [
            {
                "stage": "retrieval",
                "ablation": "without_als",
                "ndcg_at_10": 0.4,
                "features": None,
                "recall": 0.3,
            }
        ],
        stage="retrieval",
        ndcg_at_10=0.5,
        recall=0.45,
    )

    assert [row["ablation"] for row in rows] == ["full", "without_als"]
    assert rows[0]["delta_ndcg_at_10"] == 0.0
    assert rows[0]["delta_recall"] == 0.0
    assert abs(float(rows[1]["delta_ndcg_at_10"]) - -0.1) < 1e-12
    assert abs(float(rows[1]["delta_recall"]) - -0.15) < 1e-12
