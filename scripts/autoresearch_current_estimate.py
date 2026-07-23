"""Run an autoresearch-style evaluation for current reservoir level estimation.

Example:
  uv run python scripts/autoresearch_current_estimate.py

Agents should edit only ``research/current_level_candidate.py`` and then rerun this
script. The primary score is ``level_mae_m``; lower is better.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.db.session import make_engine
from ml.autoresearch import EvaluationConfig, evaluate_candidate, load_candidate, read_pairs

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATE = ROOT / "research" / "current_level_candidate.py"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--include-synthetic", action="store_true")
    parser.add_argument("--min-pairs", type=int, default=8)
    parser.add_argument("--train-fraction", type=float, default=0.8)
    args = parser.parse_args()

    module = load_candidate(args.candidate)
    config = EvaluationConfig(
        train_fraction=args.train_fraction,
        min_pairs=args.min_pairs,
        include_synthetic=args.include_synthetic,
    )
    engine = make_engine()
    with engine.connect() as conn:
        pairs = read_pairs(conn, include_synthetic=config.include_synthetic)
    result = evaluate_candidate(module, pairs, config)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
