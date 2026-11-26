"""Edition bundles (RL-02, RL-03): canonical bytes, input IDs, and a write-once folder.

An edition is one canonical JSON document. Its SHA-256 is what gets published before the reveal. Nothing in
the document depends on the wall clock, so the same inputs and code give the same bytes; the time of issue
lives in the receipt beside it.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import polars as pl

from cfp.common.hashing import sha256_hex

EDITION_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,80}$")


class EditionExists(FileExistsError):
    """Editions are write-once; a correction is a new edition."""


def canonical(doc: Any) -> bytes:
    """Sorted keys, no spaces, ASCII, one trailing newline."""
    text = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return text.encode() + b"\n"


def input_id(name: str, rows: pl.DataFrame, key: Sequence[str]) -> str:
    """An immutable ID for the rows an edition read: a hash of each row's key, version and raw payload."""
    lines = sorted(
        "|".join(str(value) for value in row)
        for row in rows.select([*key, "correction_version", "raw_hash"]).iter_rows()
    )
    return f"{name}:{len(lines)}:{sha256_hex(chr(10).join(lines).encode())}"


def write_edition(
    root: Path | str,
    edition_id: str,
    body: bytes,
    receipt: Mapping[str, Any],
    extra: Mapping[str, bytes] | None = None,
    name: str = "edition.json",
) -> Path:
    """Create <root>/<edition_id>/ with the body (as `name`), receipt.json and extras; refuse if it exists."""
    if not EDITION_ID.fullmatch(edition_id):
        raise ValueError(f"not an edition id: {edition_id!r}")
    files = {name: body, "receipt.json": canonical(dict(receipt)), **(extra or {})}
    if name == "receipt.json" or name in (extra or {}):
        raise ValueError(f"{name!r} is taken by another file in the folder")
    for file_name in files:
        if not re.fullmatch(r"[a-z0-9_.-]+", file_name) or file_name.startswith("."):
            raise ValueError(f"not a file name: {file_name!r}")
    folder = Path(root) / edition_id
    Path(root).mkdir(parents=True, exist_ok=True)
    if folder.exists():
        raise EditionExists(f"edition {edition_id} already exists; issue a new revision")
    staging = Path(root) / f".staging-{edition_id}-{uuid.uuid4().hex}"
    staging.mkdir()
    for file_name, payload in files.items():
        path = staging / file_name
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        path.chmod(0o444)
    try:
        staging.rename(folder)  # one step: the edition appears complete or not at all
    except OSError as error:
        for path in staging.iterdir():
            path.unlink()
        staging.rmdir()
        raise EditionExists(f"edition {edition_id} already exists; issue a new revision") from error
    folder.chmod(0o555)
    return folder
