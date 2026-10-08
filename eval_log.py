"""eval_runs.csv and the daily test budget, shared by test_local.py and the
scripts that call the model for testing (scripts/preview_outreach.py), so every
paid test run is logged and counted the same way.
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
DAILY_BUDGET_USD = 0.50
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


def budget_ok(estimate: float, force: bool = False) -> bool:
    """Prints the decision. Over the limit is refused unless forced."""
    spent = spent_today()
    if spent + estimate <= DAILY_BUDGET_USD:
        print(f"Budget: ${spent:.2f} spent today, this run about ${estimate:.2f}, "
              f"limit ${DAILY_BUDGET_USD:.2f}.")
        return True
    if force:
        print(f"Budget: over the limit (${spent:.2f} spent today + about ${estimate:.2f}), "
              "running anyway because of --force.")
        return True
    print(f"Refusing to run: ${spent:.2f} spent on tests today, this run would add about "
          f"${estimate:.2f}, over the ${DAILY_BUDGET_USD:.2f} daily limit. Run less, wait until "
          "tomorrow (Singapore time), or pass --force.")
    return False
