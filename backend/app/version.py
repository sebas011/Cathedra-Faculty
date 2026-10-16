"""Release version helpers shared by Cathedra's local service."""

import os
from pathlib import Path


def build_identity() -> str:
    return os.environ.get("CATHEDRA_BUILD_ID", "development")


def release_version() -> str:
    configured = os.environ.get("CATHEDRA_RELEASE_VERSION", "").strip()
    if configured:
        return configured

    version_file = Path(__file__).resolve().parents[2] / "VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip() or "development"
    except OSError:
        return "development"
