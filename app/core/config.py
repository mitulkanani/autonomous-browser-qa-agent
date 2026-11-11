from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name: str, default: str = "") -> tuple[str, ...]:
    return tuple(part.strip().lower() for part in os.getenv(name, default).split(",") if part.strip())


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Autonomous Browser QA Agent")
    environment: str = os.getenv("ENVIRONMENT", "development")
    database_path: Path = Path(os.getenv("DATABASE_PATH", "./data/qa_runs.sqlite3"))
    artifacts_dir: Path = Path(os.getenv("ARTIFACTS_DIR", "./artifacts"))
    allowed_target_hosts: tuple[str, ...] = _csv_env(
        "ALLOWED_TARGET_HOSTS", "127.0.0.1,localhost"
    )
    allow_private_targets: bool = _bool_env("ALLOW_PRIVATE_TARGETS", False)
    allow_loopback_targets: bool = _bool_env("ALLOW_LOOPBACK_TARGETS", False)
    browser_executable_path: str | None = os.getenv("BROWSER_EXECUTABLE_PATH") or None
    browser_headless: bool = _bool_env("BROWSER_HEADLESS", True)
    navigation_timeout_ms: int = int(os.getenv("NAVIGATION_TIMEOUT_MS", "15000"))
    action_timeout_ms: int = int(os.getenv("ACTION_TIMEOUT_MS", "7000"))
    max_run_seconds: int = int(os.getenv("MAX_RUN_SECONDS", "90"))
    max_concurrent_runs: int = int(os.getenv("MAX_CONCURRENT_RUNS", "2"))
    planner_provider: str = os.getenv("PLANNER_PROVIDER", "mock").strip().lower()
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY") or None
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    qa_api_token: str | None = os.getenv("QA_API_TOKEN") or None


settings = Settings()
