from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from api.pmd_client import (
    PmdMonitorClient,
    pmd_forecast_element,
    pmd_forecast_element_candidates,
    summarize_model_time_response,
)

MODEL_TIME_LIST_PATH = "api/modelTimeList"


def _element_keys(selected: list[str] | None) -> list[str]:
    if selected:
        return selected
    return [element.key for element in pmd_forecast_element_candidates()]


def discover(keys: list[str] | None = None) -> dict:
    client = PmdMonitorClient()
    if not client.configured():
        return {
            "configured": False,
            "checked_at": datetime.now(UTC).isoformat(),
            "elements": [],
            "error": "PMD Monitor credentials are not configured",
        }

    results = []
    for key in _element_keys(keys):
        candidate = pmd_forecast_element(key)
        params = {"data_type": candidate.data_type, "element": candidate.element}
        try:
            payload = client.get_json(MODEL_TIME_LIST_PATH, params=params)
            summary = summarize_model_time_response(payload)
            error = None
        except Exception as exc:  # pragma: no cover - exercised against live PMD only
            summary = {"available": False, "row_count": 0, "model_times": [], "frame_count": None}
            error = str(exc)
        results.append(
            {
                "key": candidate.key,
                "data_type": candidate.data_type,
                "element": candidate.element,
                "label": candidate.label,
                "unit": candidate.unit,
                "accumulation": candidate.accumulation,
                "registry_status": candidate.status,
                "metadata_status": "metadata-confirmed" if summary["available"] else "candidate",
                "model_time_list_path": MODEL_TIME_LIST_PATH,
                "request_params": params,
                "summary": summary,
                "error": error,
            }
        )
    return {"configured": True, "checked_at": datetime.now(UTC).isoformat(), "elements": results}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover PMD prediction modelTimeList metadata for candidate raster elements."
    )
    parser.add_argument(
        "--element-key",
        action="append",
        help="Candidate element key to check. Repeat to check multiple keys. Defaults to all.",
    )
    args = parser.parse_args()
    print(json.dumps(discover(args.element_key), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
