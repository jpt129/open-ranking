"""Frozen parameters (OR-04): the link scale and ridge penalties fixed before a season is graded.

The frozen folder holds params_<season>.json, written once, with its SHA-256 beside it. A reader checks the
hash.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cfp.common.hashing import sha256_hex
from cfp.open_ranking.strength import Params


class FrozenError(RuntimeError):
    """Frozen parameters are missing, already written, or do not match their hash."""


@dataclass(frozen=True)
class Frozen:
    season: int
    params: Params
    t: float
    status: str
    rule_version_id: str
    sha256: str
    document: dict[str, Any]


def _paths(root: Path | str, season: int) -> tuple[Path, Path]:
    folder = Path(root)
    return folder / f"params_{season}.json", folder / f"params_{season}.sha256"


def write_frozen(root: Path | str, season: int, document: Mapping[str, Any]) -> tuple[Path, str]:
    """Write the season's parameters once. Returns the file and its SHA-256."""
    path, side = _paths(root, season)
    if int(document["season"]) != season:
        raise FrozenError(f"the document is for {document['season']}, not {season}")
    text = json.dumps(dict(document), sort_keys=True, indent=1, ensure_ascii=True, allow_nan=False)
    body = (text + "\n").encode()
    digest = sha256_hex(body)
    already = f"{season} is already frozen at {path}; frozen parameters are never rewritten"
    if path.exists():
        raise FrozenError(already)
    path.parent.mkdir(parents=True, exist_ok=True)
    if side.exists():  # left by a write that stopped before the parameters were written
        side.chmod(0o644)
    side.write_text(f"{digest}  {path.name}\n")  # the hash first: a parameters file never exists without it
    try:
        with path.open("xb") as handle:
            handle.write(body)
    except FileExistsError as error:
        raise FrozenError(already) from error
    path.chmod(0o444)
    side.chmod(0o444)
    return path, digest


def load_frozen(root: Path | str, season: int) -> Frozen:
    path, side = _paths(root, season)
    if not path.is_file() or not side.is_file():
        raise FrozenError(f"{season} is not frozen: {path} is missing")
    body = path.read_bytes()
    digest = sha256_hex(body)
    if side.read_text().split()[0] != digest:
        raise FrozenError(f"{path} does not match its recorded hash")
    doc = json.loads(body)
    if doc.get("season") != season:
        raise FrozenError(f"{path} is for season {doc.get('season')}, not {season}")
    params = Params(
        float(doc["lambda_c"]), float(doc["lambda_u"]), int(doc["cap"]), doc["independent_penalty"]
    )
    return Frozen(season, params, float(doc["t"]), doc["status"], doc["rule_version_id"], digest, doc)
