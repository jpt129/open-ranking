"""Secrets come from the environment. A local .env file is loaded into it and never printed."""

from __future__ import annotations

import os
from pathlib import Path


class MissingSecret(LookupError):
    """A required key is not set."""


def load_env(path: Path | str = ".env") -> None:
    """Load KEY=VALUE lines into os.environ without overriding values already set."""
    file = Path(path)
    if not file.is_file():
        return
    for line in file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.removeprefix("export ").partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()  # an unquoted value ends at an inline comment
        os.environ.setdefault(name.strip(), value)


def secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise MissingSecret(f"{name} is not set; put it in .env (see .env.example)")
    return value
