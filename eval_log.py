"""eval_runs.csv, shared by test_local.py and the scripts that call the model
for testing (scripts/preview_outreach.py), so every paid test run's cost is
logged the same way.
"""
import csv
import hashlib
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVAL_RUNS = ROOT / "eval_runs.csv"
FIELDS = ["timestamp", "commit", "models", "coach_md_sha256", "only", "passed", "total",
          "warnings", "cost_usd", "checks", "persona_costs"]
_SINGAPORE = timezone(timedelta(hours=8))


def now_sgt() -> datetime:
    return datetime.now(_SINGAPORE).replace(tzinfo=None)


def git_commit() -> str:
    """HEAD, with +dirty when tracked files have changes, so a row says exactly
    which code it scored."""
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
                               capture_output=True, text=True).stdout.strip()
        return head + ("+dirty" if dirty else "")
    except Exception:
        return "unknown"


def coach_md_hash() -> str:
    return hashlib.sha256((ROOT / "app" / "agent" / "prompts" / "coach.md").read_bytes()).hexdigest()[:12]


def rows() -> list:
    if not EVAL_RUNS.exists():
        return []
    with open(EVAL_RUNS, newline="") as f:
        return list(csv.DictReader(f))


def _upgrade_header() -> None:
    """Rewrites the file with the current columns if an older run wrote fewer."""
    if not EVAL_RUNS.exists():
        return
    with open(EVAL_RUNS, newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames == FIELDS:
            return
        old = list(reader)
    with open(EVAL_RUNS, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for r in old:
            writer.writerow({k: r.get(k, "") for k in FIELDS})


def append(row: dict) -> None:
    """One row; missing columns are left blank, timestamp and commit filled in."""
    _upgrade_header()
    new_file = not EVAL_RUNS.exists()
    full = {k: "" for k in FIELDS}
    full.update({"timestamp": now_sgt().isoformat(timespec="seconds"), "commit": git_commit(),
                 "coach_md_sha256": coach_md_hash()})
    full.update(row)
    with open(EVAL_RUNS, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(full)


def spent_today() -> float:
    """Model spend on tests today, Singapore date."""
    today = now_sgt().date().isoformat()
    return sum(float(r.get("cost_usd") or 0) for r in rows() if r["timestamp"].startswith(today))


def announce(estimate: float) -> None:
    """Prints today's test spend and this run's estimate. There's no limit; every
    run's cost is logged so spend stays visible."""
    print(f"Test spend today: ${spent_today():.2f}. This run: about ${estimate:.2f}.")
