"""ABT builder units (FR-ABT-2 recency semantics).

The mixed-resolution case is the pandas-3 regression that broke the DE pipeline:
SQL DATE columns parse to ``datetime64[s]`` while ``pd.date_range`` spines are
``datetime64[us]``, and ``merge_asof`` (unlike equality merges) refuses to coerce.
"""

from __future__ import annotations

import pandas as pd
from data_engineering.build_abt import _STALE, _backward_recency


def _spine(start: str, end: str) -> pd.DataFrame:
    return pd.DataFrame({"date": pd.date_range(start, end, freq="D")})


def test_backward_recency_mixed_datetime_resolutions():
    spine = _spine("2020-01-01", "2020-01-10")
    # what pd.read_sql(parse_dates=...) returns for a DATE column under pandas 3
    events = pd.Series(["2020-01-01", "2020-01-05"]).astype("datetime64[s]")

    days = _backward_recency(spine, events)

    assert days.tolist() == [0, 1, 2, 3, 0, 1, 2, 3, 4, 5]


def test_backward_recency_stale_before_first_event():
    spine = _spine("2020-01-01", "2020-01-04")
    events = pd.Series(["2020-01-03"]).astype("datetime64[s]")

    days = _backward_recency(spine, events)

    assert days.tolist() == [_STALE, _STALE, 0, 1]


def test_backward_recency_no_events_is_all_stale():
    spine = _spine("2020-01-01", "2020-01-03")

    days = _backward_recency(spine, pd.Series([], dtype="datetime64[s]"))

    assert days.tolist() == [_STALE, _STALE, _STALE]
