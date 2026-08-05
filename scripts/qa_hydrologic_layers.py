"""QA static hydrologic map layers in PostGIS.

Checks the Phase 8A.6 basics that can be verified from persisted layers:
- catchment/sub-basin presence
- flowline presence
- invalid or empty sub-basin polygons
- invalid or empty flowline geometries
- duplicate HYBAS IDs
- missing downstream links inside each selected catchment
- computed catchment area against published references where available
"""

from __future__ import annotations

from dataclasses import dataclass

from core.db.session import make_engine
from data_engineering.reservoirs import REGISTRY
from sqlalchemy import text

EXPECTED_CATCHMENT_KM2: dict[str, float] = {"gobind_sagar": 56_900.0}


@dataclass(frozen=True)
class HydrologicQaRow:
    reservoir_id: str
    catchment_area_km2: float | None
    expected_area_km2: float | None
    area_ratio: float | None
    subbasin_count: int
    headwater_count: int
    invalid_geometry_count: int
    duplicate_hybas_count: int
    missing_downstream_count: int
    external_outlet_count: int
    flowline_count: int
    main_stem_count: int
    max_stream_order: int | None
    invalid_flowline_count: int

    @property
    def status(self) -> str:
        if self.subbasin_count == 0 or self.flowline_count == 0:
            return "fail"
        if self.invalid_geometry_count > 0 or self.invalid_flowline_count > 0:
            return "fail"
        if self.missing_downstream_count > 0 or self.duplicate_hybas_count > 0:
            return "warn"
        if self.area_ratio is not None and not 0.8 <= self.area_ratio <= 1.2:
            return "warn"
        return "ok"


def hydrologic_qa_rows() -> list[HydrologicQaRow]:
    query = text(
        """
        WITH expected(reservoir_id, expected_area_km2) AS (
            VALUES (:gobind_sagar, :gobind_sagar_area)
        ), subbasin_stats AS (
            SELECT
                reservoir_id,
                count(*)::int AS subbasin_count,
                count(*) FILTER (WHERE is_headwater)::int AS headwater_count,
                count(*) FILTER (WHERE NOT ST_IsValid(geom) OR ST_IsEmpty(geom))::int
                    AS invalid_geometry_count
            FROM catchment_subbasin
            GROUP BY reservoir_id
        ), duplicate_stats AS (
            SELECT reservoir_id, count(*)::int AS duplicate_hybas_count
            FROM (
                SELECT reservoir_id, hybas_id
                FROM catchment_subbasin
                GROUP BY reservoir_id, hybas_id
                HAVING count(*) > 1
            ) d
            GROUP BY reservoir_id
        ), external_links AS (
            SELECT s.reservoir_id, count(*)::int AS external_link_count
            FROM catchment_subbasin s
            LEFT JOIN catchment_subbasin d
              ON d.reservoir_id = s.reservoir_id AND d.hybas_id = s.next_down
            WHERE s.next_down <> 0 AND d.hybas_id IS NULL
            GROUP BY s.reservoir_id
        ), flowline_stats AS (
            SELECT
                reservoir_id,
                count(*)::int AS flowline_count,
                count(*) FILTER (WHERE is_main_stem)::int AS main_stem_count,
                max(stream_order)::int AS max_stream_order,
                count(*) FILTER (WHERE NOT ST_IsValid(geom) OR ST_IsEmpty(geom))::int
                    AS invalid_flowline_count
            FROM catchment_flowline
            GROUP BY reservoir_id
        )
        SELECT
            r.reservoir_id,
            CASE WHEN r.catchment_geom IS NULL THEN NULL
                 ELSE ST_Area(r.catchment_geom::geography) / 1000000.0
            END AS catchment_area_km2,
            e.expected_area_km2,
            CASE WHEN e.expected_area_km2 IS NULL OR r.catchment_geom IS NULL THEN NULL
                 ELSE (ST_Area(r.catchment_geom::geography) / 1000000.0) / e.expected_area_km2
            END AS area_ratio,
            COALESCE(ss.subbasin_count, 0) AS subbasin_count,
            COALESCE(ss.headwater_count, 0) AS headwater_count,
            COALESCE(ss.invalid_geometry_count, 0) AS invalid_geometry_count,
            COALESCE(ds.duplicate_hybas_count, 0) AS duplicate_hybas_count,
            GREATEST(COALESCE(el.external_link_count, 0) - 1, 0)::int AS missing_downstream_count,
            LEAST(COALESCE(el.external_link_count, 0), 1)::int AS external_outlet_count,
            COALESCE(fs.flowline_count, 0) AS flowline_count,
            COALESCE(fs.main_stem_count, 0) AS main_stem_count,
            fs.max_stream_order,
            COALESCE(fs.invalid_flowline_count, 0) AS invalid_flowline_count
        FROM reservoir r
        LEFT JOIN expected e ON e.reservoir_id = r.reservoir_id
        LEFT JOIN subbasin_stats ss ON ss.reservoir_id = r.reservoir_id
        LEFT JOIN duplicate_stats ds ON ds.reservoir_id = r.reservoir_id
        LEFT JOIN external_links el ON el.reservoir_id = r.reservoir_id
        LEFT JOIN flowline_stats fs ON fs.reservoir_id = r.reservoir_id
        WHERE r.reservoir_id = ANY(:reservoir_ids)
        ORDER BY r.reservoir_id
        """
    )
    params = {
        "gobind_sagar": "gobind_sagar",
        "gobind_sagar_area": EXPECTED_CATCHMENT_KM2["gobind_sagar"],
        "reservoir_ids": [meta.slug for meta in REGISTRY.values()],
    }
    with make_engine().connect() as conn:
        rows = conn.execute(query, params).mappings().all()
    return [HydrologicQaRow(**dict(row)) for row in rows]


def main() -> None:
    rows = hydrologic_qa_rows()
    for row in rows:
        area = "unknown" if row.catchment_area_km2 is None else f"{row.catchment_area_km2:,.0f} km2"
        ratio = "n/a" if row.area_ratio is None else f"{row.area_ratio:.2f}x"
        print(
            f"[{row.status.upper()}] {row.reservoir_id}: catchment={area}, "
            f"expected_ratio={ratio}, subbasins={row.subbasin_count}, "
            f"headwaters={row.headwater_count}, invalid={row.invalid_geometry_count}, "
            f"flowlines={row.flowline_count}, main_stems={row.main_stem_count}, "
            f"max_order={row.max_stream_order}, invalid_flowlines={row.invalid_flowline_count}, "
            f"duplicates={row.duplicate_hybas_count}, "
            f"external_outlets={row.external_outlet_count}, "
            f"missing_downstream={row.missing_downstream_count}"
        )
    if any(row.status == "fail" for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
