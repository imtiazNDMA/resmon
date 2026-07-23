"""Unit tests for bulletin cleaning + ABT recency (no DB)."""

from __future__ import annotations

import pandas as pd
from data_engineering.build_abt import _STALE, _backward_recency
from data_engineering.cleaning import canonical_name, clean_bulletins, parse_ist_date


def test_canonical_name_aliases():
    assert canonical_name("Bhakra Dam") == "GOBIND SAGAR"
    assert canonical_name("pong") == "PONG DAM"
    assert canonical_name("Ranjit Sagar") == "THEIN DAM"
    assert canonical_name("Unknown Dam") is None


def test_parse_ist_date_iso_vs_dayfirst():
    assert parse_ist_date("2025-05-08") == pd.Timestamp("2025-05-08")
    assert parse_ist_date("08/05/2025") == pd.Timestamp("2025-05-08")  # dayfirst


def test_clean_bulletins_maps_and_quarantines():
    raw = pd.DataFrame(
        {
            "RESERVOIR NAME": ["GOBIND SAGAR", "Unknown Dam"],
            "DATE": ["2025-08-28", "2025-08-28"],
            "CURRENT RESERVOIR LEVEL (M)": [500.0, 100.0],
            "CURRENT LIVE STORAGE (BCM)": [5.0, 1.0],
            "pct_filled": [85.0, 50.0],
            "STORAGE AS % OF LIVE CAPACITY AT FRL - NORMAL STORAGE": [80.0, 40.0],
            "BENEFITS - IRR-CCA": [676.0, 0.0],
            "BENEFITS - HYDEL IN MW": [1379.0, 0.0],
            "SOURCE_PDF": ["b.pdf", "b.pdf"],
        }
    )
    out = clean_bulletins(raw)
    gobind = out[out["reservoir_id"] == "gobind_sagar"].iloc[0]
    assert gobind["row_quality"] == "ok"
    assert gobind["frl_m"] == 512.00
    # Unknown name → no slug → quarantine.
    assert (out["row_quality"] == "quarantine").any()


def test_clean_bulletins_accepts_historical_spreadsheet_headers():
    raw = pd.DataFrame(
        {
            "RESERVOIR NAME - NAN": ["GOBIND SAGAR"],
            "DATE": ["2025-05-29"],
            "CURRENT RESERVOIR LEVEL (M) - NAN": [476.22],
            "CURRENT LIVE STORAGE (BCM) - NAN": [1.387],
            "pct_filled": [22.27],
            "STORAGE AS % OF LIVE CAPACITY AT FRL - NORMAL STORAGE": [27.48],
            "BENEFITS - IRR-CCA": [676.0],
            "BENEFITS - HYDEL IN MW": [1379.0],
            "SOURCE_PDF": ["bulletin.pdf"],
        }
    )
    out = clean_bulletins(raw)
    assert out.iloc[0]["reservoir_id"] == "gobind_sagar"
    assert out.iloc[0]["live_storage_bcm"] == 1.387


def test_backward_recency_no_future_leak():
    spine = pd.DataFrame({"date": pd.date_range("2025-01-01", "2025-01-10", freq="D")})
    events = pd.Series(pd.to_datetime(["2025-01-03", "2025-01-07"]))
    days = _backward_recency(spine, events)
    # Before the first event → sentinel (no future event leaks backward).
    assert days.iloc[0] == _STALE  # 2025-01-01, no prior event
    assert days.iloc[2] == 0  # 2025-01-03 is an event day
    assert days.iloc[3] == 1  # 2025-01-04, 1 day after the 01-03 event
    assert (days >= 0).all()
