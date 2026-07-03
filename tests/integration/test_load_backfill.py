"""Loader: backfill CSVs -> real observation rows (spec: data prerequisite)."""

from __future__ import annotations

from sqlalchemy import text

from scripts.load_backfill import load_backfill

CSV = (
    "scene_id,acquisition_date,orbit_relative,pass_direction,status,area_km2,"
    "threshold_db,otsu_eta,valley_ratio,separability,detail\n"
    "S1A_TEST_0001,2020-01-05,27,ASC,ok,120.5,-21.4,0.86,0.21,0.92,\n"
    "S1A_TEST_0002,2020-01-17,27,ASC,abstain,,-20.1,0.55,0.81,0.10,histogram not bimodal\n"
    "S1A_TEST_0003,2020-01-29,27,ASC,ok,118.2,-21.9,0.84,0.25,0.91,\n"
)


def test_load_backfill_upserts_ok_rows_only(session, add_reservoir, tmp_path):
    add_reservoir("gobind_sagar")
    csv_dir = tmp_path / "backfill"
    csv_dir.mkdir()
    (csv_dir / "area_series_gobind_sagar.csv").write_text(CSV, encoding="utf-8")

    result = load_backfill(session, csv_dir)
    assert result == {"loaded": 2, "skipped_non_ok": 1}

    rows = session.execute(
        text(
            "SELECT acquisition_date, surface_area, extraction_method, scene_ids "
            "FROM observation WHERE reservoir_id = 'gobind_sagar' ORDER BY acquisition_date"
        )
    ).fetchall()
    assert len(rows) == 2
    assert float(rows[0].surface_area) == 120.5
    assert rows[0].extraction_method == "otsu_vh"
    assert rows[0].scene_ids == ["S1A_TEST_0001"]

    # idempotent: re-load converges, no duplicates
    result2 = load_backfill(session, csv_dir)
    assert result2["loaded"] == 2
    n = session.execute(
        text("SELECT count(*) FROM observation WHERE reservoir_id='gobind_sagar'")
    ).scalar()
    assert n == 2
