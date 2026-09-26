"""Minimal .env loader (no dependency).

Loads KEY=VALUE lines from a .env file into os.environ without overriding
variables that are already set. Search order: explicit path argument, then
BOOKLENDER_ENV, then ./.env, then <repo root>/.env.

The .env file is for local/prototype use and is gitignored — production
deployments should use a real secrets manager.
"""
from __future__ import annotations

import os
from pathlib import Path


def load_env(path: str | Path | None = None) -> Path | None:
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    if os.environ.get("BOOKLENDER_ENV"):
        candidates.append(Path(os.environ["BOOKLENDER_ENV"]))
    candidates.append(Path.cwd() / ".env")
    candidates.append(Path(__file__).resolve().parents[2] / ".env")  # repo root

    for cand in candidates:
        if cand.is_file():
            for line in cand.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
            return cand
    return None
