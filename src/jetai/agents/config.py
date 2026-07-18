"""Runtime settings for the agent suite, loaded from the environment / ``.env``."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    """OpenAI credentials and run-directory location."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str
    openai_model: str = "gpt-5"
    runs_dir: Path = Path("runs")


def create_run_dir(runs_dir: Path) -> Path:
    """Create and return a fresh ``runs/<UTC timestamp>/`` directory."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = runs_dir / stamp
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def latest_run_dir(runs_dir: Path) -> Path:
    """Return the most recent run directory, or raise if none exists."""
    candidates = sorted(d for d in runs_dir.glob("*") if d.is_dir())
    if not candidates:
        raise FileNotFoundError(f"No runs found under {runs_dir}; run a stage first.")
    return candidates[-1]
