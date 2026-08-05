from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from api.pmd_client import pmd_forecast_element


def _band_stats(values: np.ma.MaskedArray) -> dict[str, float | int | None]:
    compressed = values.compressed()
    if compressed.size == 0:
        return {"valid_pixels": 0, "min": None, "p50": None, "p95": None, "max": None}
    return {
        "valid_pixels": int(compressed.size),
        "min": float(np.min(compressed)),
        "p50": float(np.percentile(compressed, 50)),
        "p95": float(np.percentile(compressed, 95)),
        "max": float(np.max(compressed)),
    }


def inspect_raster(path: str | Path, *, element_key: str | None = None) -> dict[str, Any]:
    raster_path = Path(path)
    evidence: dict[str, Any] = {
        "path": str(raster_path),
        "element": None,
        "raster": None,
    }
    if element_key is not None:
        candidate = pmd_forecast_element(element_key)
        evidence["element"] = {
            "key": candidate.key,
            "data_type": candidate.data_type,
            "element": candidate.element,
            "label": candidate.label,
            "unit": candidate.unit,
            "accumulation": candidate.accumulation,
            "registry_status": candidate.status,
        }

    with rasterio.open(raster_path) as dataset:
        band_stats = []
        for band_index in range(1, dataset.count + 1):
            band_stats.append(
                {
                    "band": band_index,
                    **_band_stats(dataset.read(band_index, masked=True)),
                }
            )
        evidence["raster"] = {
            "driver": dataset.driver,
            "width": dataset.width,
            "height": dataset.height,
            "crs": dataset.crs.to_string() if dataset.crs else None,
            "bounds": list(dataset.bounds),
            "band_count": dataset.count,
            "dtypes": list(dataset.dtypes),
            "nodata": dataset.nodata,
            "band_stats": band_stats,
        }
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect a downloaded PMD prediction raster and emit contract evidence."
    )
    parser.add_argument(
        "path",
        help="Path to a downloaded GeoTIFF or raster file readable by GDAL.",
    )
    parser.add_argument(
        "--element-key",
        help="Optional candidate registry key, e.g. pmd_pred_hourtpe.",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            inspect_raster(args.path, element_key=args.element_key), indent=2, sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
