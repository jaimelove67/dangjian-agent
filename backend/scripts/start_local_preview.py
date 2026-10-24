"""Run the isolated local preview in the managed foreground process session.

Private settings are ignored by Git. Never print connection strings or keys.
This command reuses existing data and does not create accounts or reset passwords.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit


def main() -> None:
    backend = Path(__file__).resolve().parents[1]
    config_path = backend / ".env.local-preview.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        database = urlsplit(config["DATABASE_URL"])
        redis = urlsplit(config["REDIS_URL"])
        if not (
            config["ENV"] == "testing"
            and database.scheme == "postgresql+asyncpg"
            and database.hostname in {"127.0.0.1", "localhost"}
            and database.port == 55434
            and database.path == "/dangjian_baseline"
            and redis.scheme == "redis"
            and redis.hostname in {"127.0.0.1", "localhost"}
            and redis.port == 56381
            and redis.path == "/0"
        ):
            raise ValueError("Use only the isolated preview services.")
    except (OSError, ValueError, KeyError, TypeError):
        sys.exit("Missing or invalid private isolated-preview settings; startup cancelled.")

    allowed = {
        "ENV",
        "DATABASE_URL",
        "REDIS_URL",
        "SECRET_KEY",
        "FILE_ENCRYPTION_KEYS",
        "FILE_ENCRYPTION_ACTIVE_KEY",
    }
    env = os.environ.copy()
    env.update(
        {key: value for key, value in config.items() if key in allowed and isinstance(value, str)}
    )
    env.update(
        {
            "PYTHONUTF8": "1",
            "JOB_WORKER_ENABLED": "false",
            "DASHSCOPE_API_KEY": "",
            "QWEN_API_KEY": "",
            "FILE_STORAGE_DIR": str(backend / "tmp" / "smoke-originals"),
            "AUDIT_SPOOL_DIR": str(backend / "tmp" / "smoke-audit"),
        }
    )
    os.chdir(backend)
    raise SystemExit(
        subprocess.call(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "18001",
            ],
            env=env,
        )
    )


if __name__ == "__main__":
    main()
