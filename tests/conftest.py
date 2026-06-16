"""Root test configuration."""

from __future__ import annotations

import os

# sklearn/joblib's loky probes physical core count via a subprocess that fails noisily on
# some Windows setups; pin it so tests stay quiet and deterministic.
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "2")

# Tests run against the credential-free fixture data-access backend (no GEE).
os.environ.setdefault("DATA_ACCESS_BACKEND", "fixture")
