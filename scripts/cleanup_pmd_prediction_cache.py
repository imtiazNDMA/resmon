from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

PREDICTION_CACHE_DIR = Path("data/cache/pmd_predictions")
RETAIN_SUFFIXES = {".png", ".json"}


def cleanup_cache(cache_dir: Path, *, older_than_days: int, dry_run: bool = True) -> list[Path]:
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    removed: list[Path] = []
    if not cache_dir.exists():
        return removed
    for path in cache_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in RETAIN_SUFFIXES:
            continue
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if modified_at >= cutoff:
            continue
        removed.append(path)
        if not dry_run:
            path.unlink()
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean old PMD prediction PNG/JSON cache files.")
    parser.add_argument("--cache-dir", default=str(PREDICTION_CACHE_DIR))
    parser.add_argument("--older-than-days", type=int, default=14)
    parser.add_argument(
        "--delete", action="store_true", help="Actually delete files; default is dry-run."
    )
    args = parser.parse_args()
    removed = cleanup_cache(
        Path(args.cache_dir), older_than_days=args.older_than_days, dry_run=not args.delete
    )
    action = "would delete" if not args.delete else "deleted"
    for path in removed:
        print(f"{action}: {path}")
    print(f"{action} {len(removed)} PMD prediction cache files")


if __name__ == "__main__":
    main()
