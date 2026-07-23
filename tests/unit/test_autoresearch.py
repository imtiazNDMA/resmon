from __future__ import annotations

from pathlib import Path

import pandas as pd
from ml.autoresearch import EvaluationConfig, evaluate_candidate, load_candidate


def test_current_level_candidate_contract_runs():
    rows = []
    for rid, offset in [("a", 0.0), ("b", 10.0)]:
        for i in range(10):
            area = 100.0 + offset + i
            rows.append(
                {
                    "reservoir_id": rid,
                    "gt_date": pd.Timestamp("2020-01-01") + pd.Timedelta(days=i),
                    "acquisition_date": pd.Timestamp("2020-01-01") + pd.Timedelta(days=i),
                    "area_km2": area,
                    "level_m": 400.0 + area * 0.5,
                    "live_storage_bcm": area * 0.02,
                    "pct_filled": area * 0.2,
                    "live_capacity_bcm": 10.0,
                    "area_confidence": 0.9,
                    "extraction_method": "otsu_vh",
                    "scene_ids": ["S1_TEST"],
                }
            )
    module = load_candidate(Path("research/current_level_candidate.py"))
    result = evaluate_candidate(module, pd.DataFrame(rows), EvaluationConfig(min_pairs=8))
    assert result["score"] < 1e-9
    assert result["overall"]["fill_mae_pct"] < 1e-9
