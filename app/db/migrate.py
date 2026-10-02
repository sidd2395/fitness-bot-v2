from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[2]


def upgrade_head() -> None:
    """Runs every pending migration against DATABASE_URL. No ini file, so
    alembic/env.py skips fileConfig and leaves the app's logging alone."""
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(cfg, "head")
