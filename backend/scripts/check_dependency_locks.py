"""Check that CI and runtime locks include every directly pinned dependency."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==([^\s;\\]+)", re.MULTILINE)


def pinned_versions(path: Path) -> dict[str, str]:
    """Read exact pins, normalizing distribution names as Python installers do."""
    return {
        re.sub(r"[-_.]+", "-", name).lower(): version
        for name, version in PIN.findall(path.read_text(encoding="utf-8"))
    }


def check_locks(root: Path = ROOT) -> list[str]:
    """Return missing or mismatched direct pins in the production and CI locks."""
    failures = []
    for source, lock in (
        ("requirements.txt", "requirements.lock"),
        ("requirements.txt", "requirements-dev.lock"),
        ("requirements-dev.txt", "requirements-dev.lock"),
    ):
        locked = pinned_versions(root / lock)
        for name, version in pinned_versions(root / source).items():
            if locked.get(name) != version:
                failures.append(f"{lock}: expected {name}=={version} from {source}")
    return failures


if __name__ == "__main__":
    errors = check_locks()
    for error in errors:
        print(error)
    if not errors:
        print("Production and CI dependency locks contain all direct pins.")
    raise SystemExit(bool(errors))
