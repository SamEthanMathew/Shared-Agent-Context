"""Apply data retention. Run on a schedule.

Deliberately a separate process rather than a thread in the web service: a reaper
that lives inside the web process dies with every deploy and runs twice as soon
as there are two instances. As a scheduled job it is exactly-once-ish, its
failures are visible, and it cannot slow a request.

    python scripts/reaper.py            # apply retention
    python scripts/reaper.py --dry-run  # report what would go, delete nothing

Safe to run while the service is serving, and safe to run twice.
"""
from __future__ import annotations

import os
import sys

# Runs as `python scripts/reaper.py`, so the repo root is not on sys.path.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.db import create_sac_engine  # noqa: E402
from app.retention import (  # noqa: E402
    reap,
    revoked_token_retention_days,
    snapshot_retention_days,
)


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    engine = create_sac_engine()

    print(
        f"[reaper] snapshots older than {snapshot_retention_days()}d, "
        f"revoked tokens older than {revoked_token_retention_days()}d, "
        f"expired auth rows, rate counters older than 1d"
    )

    if dry_run:
        from app.retention import preview

        for line in preview(engine).lines():
            print(f"[reaper] would delete {line}")
        print("[reaper] dry run — nothing deleted")
        return 0

    report = reap(engine)
    for line in report.lines():
        print(f"[reaper] deleted {line}")
    print(f"[reaper] done, {report.total} row(s) removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
