"""Schema/constraint guarantees (plan 02 §10): append-only audit, one-active rating
curve, CHECK constraints, idempotent upsert, and geometry SRID.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError


def test_geometry_srid_is_4326(conn, add_reservoir):
    add_reservoir("srid_res")
    srid = conn.execute(
        text("SELECT ST_SRID(aoi_geom) FROM reservoir WHERE reservoir_id = 'srid_res'")
    ).scalar_one()
    assert srid == 4326


def test_reservoir_updated_at_changes_on_raw_sql_update(conn, add_reservoir):
    rid = add_reservoir("updated_res")
    before = conn.execute(
        text("SELECT updated_at FROM reservoir WHERE reservoir_id = :rid"), {"rid": rid}
    ).scalar_one()
    conn.execute(text("SELECT pg_sleep(0.01)"))
    conn.execute(text("UPDATE reservoir SET name = 'updated' WHERE reservoir_id = :rid"), {"rid": rid})
    after = conn.execute(
        text("SELECT updated_at FROM reservoir WHERE reservoir_id = :rid"), {"rid": rid}
    ).scalar_one()
    assert after > before


def test_idempotent_observation_upsert(conn, add_reservoir):
    rid = add_reservoir("ups_res")
    stmt = text(
        """
        INSERT INTO observation
          (reservoir_id, acquisition_date, surface_area, area_confidence, water_mask_ref,
           extraction_method, extraction_version, scene_ids, orbit_relative, pass_direction,
           aoi_version, layover_shadow_fraction, processing_params)
        VALUES (:rid, '2025-08-28', 50.0, 0.9, 'ref://m', 'otsu', 'v1', ARRAY['s1'], 12, 'ASC',
                'v1', 0.1, '{}'::jsonb)
        ON CONFLICT (reservoir_id, acquisition_date)
        DO UPDATE SET surface_area = EXCLUDED.surface_area
        """
    )
    conn.execute(stmt, {"rid": rid})
    conn.execute(stmt, {"rid": rid})  # second upsert is a no-op update, not a duplicate
    n = conn.execute(
        text("SELECT count(*) FROM observation WHERE reservoir_id = :rid"), {"rid": rid}
    ).scalar_one()
    assert n == 1


def test_ground_truth_negative_pct_rejected(conn, add_reservoir):
    rid = add_reservoir("gt_res")
    with pytest.raises((IntegrityError, DBAPIError)):
        conn.execute(
            text(
                """
                INSERT INTO ground_truth (reservoir_id, date, pct_filled, frl_m, live_capacity_bcm)
                VALUES (:rid, '2025-08-28', -5, 500, 6.0)
                """
            ),
            {"rid": rid},
        )


def test_one_active_rating_curve_per_reservoir(conn, add_reservoir):
    rid = add_reservoir("rc_res")
    base = text(
        """
        INSERT INTO rating_curve
          (reservoir_id, version, fit_type, area_to_storage_params, area_to_level_params,
           frl_anchor, observed_range, fit_metrics, valid_from, is_active)
        VALUES (:rid, :ver, 'blended', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                '{}'::jsonb, '2025-01-01', true)
        """
    )
    conn.execute(base, {"rid": rid, "ver": "v1"})
    with pytest.raises((IntegrityError, DBAPIError)):
        conn.execute(base, {"rid": rid, "ver": "v2"})  # second active → partial-unique violation


def test_prediction_is_append_only(conn, add_reservoir):
    rid = add_reservoir("ap_res")
    mv_id = conn.execute(
        text(
            """
            INSERT INTO model_version (model_name, version, model_stage)
            VALUES ('forecaster', 'v1', 'production') RETURNING id
            """
        )
    ).scalar_one()
    conn.execute(
        text(
            """
            INSERT INTO prediction
              (reservoir_id, run_timestamp, horizon_date, predicted_pct_filled,
               model_version_id, input_abt_version)
            VALUES (:rid, '2026-06-16T00:00:00Z', '2026-06-20', 80.0, :mv, 'abt_v1')
            """
        ),
        {"rid": rid, "mv": mv_id},
    )
    with pytest.raises(DBAPIError):  # trigger forbids UPDATE
        conn.execute(
            text("UPDATE prediction SET predicted_pct_filled = 90 WHERE reservoir_id = :rid"),
            {"rid": rid},
        )


def test_release_risk_invalid_level_rejected(conn, add_reservoir):
    rid = add_reservoir("rr_res")
    mv_id = conn.execute(
        text(
            """
            INSERT INTO model_version (model_name, version, model_stage)
            VALUES ('release', 'v1', 'production') RETURNING id
            """
        )
    ).scalar_one()
    with pytest.raises((IntegrityError, DBAPIError)):
        conn.execute(
            text(
                """
                INSERT INTO release_risk
                  (reservoir_id, run_timestamp, release_probability, risk_level,
                   contributing_factors, model_version_id, input_abt_version)
                VALUES (:rid, '2026-06-16T00:00:00Z', 0.5, 'Critical', '{}'::jsonb, :mv, 'abt_v1')
                """
            ),
            {"rid": rid, "mv": mv_id},
        )
