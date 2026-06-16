"""Shared pipeline substrate imported by all three pipelines (RS, DE, ML).

Holds the swappable :class:`DataAccessBackend` seam (GEE today, openEO/Planetary
Computer tomorrow — §4.4) plus retry/backoff and run-context helpers, so no single
pipeline package owns these and there are no circular dependencies.
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
