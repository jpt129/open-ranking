"""Golden edition: today's code rebuilds the last rehearsal edition byte for byte (OR-08, RL-01a).

The fixture is the games file and manifest of `or-2026-20261122t0700z-replay-e1`, built in rehearsal on
26 Nov 2026 from 819 real games. Any change to the strength fit, the band, the link, the ledger or the
ordering that moves one centipoint changes the hash and fails here.
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime
from pathlib import Path

import polars as pl

from cfp.common.draw import load_draw
from cfp.common.hashing import sha256_hex
from cfp.open_ranking.frozen import load_frozen
from cfp.open_ranking.release import build_edition
from cfp.release.gate import games_from_lines
from cfp.snapshot.build import Snapshot

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "fixtures" / "golden_open_ranking"


def golden() -> tuple[dict[str, object], bytes]:
    meta = json.loads((GOLDEN / "meta.json").read_text())
    return meta, gzip.decompress((GOLDEN / "games.jsonl.gz").read_bytes())


def rebuild(meta: dict[str, object], games: bytes) -> bytes:
    omitted: dict[str, int] = meta["omissions"]  # type: ignore[assignment]
    reasons = [reason for reason, count in sorted(omitted.items()) for _ in range(count)]
    omissions = pl.DataFrame(
        {"game_id": [f"omitted-{k}" for k in range(len(reasons))], "reason": reasons},
        schema={"game_id": pl.String, "reason": pl.String},
    )
    cutoff = datetime.fromisoformat(str(meta["cutoff_utc"]))
    snapshot = Snapshot(
        int(str(meta["season"])),
        cutoff,
        str(meta["mode"]),  # type: ignore[arg-type]
        games_from_lines(games),
        omissions,
        str(meta["snapshot_hash"]),
        str(meta["lists_hash"]),
    )
    frozen = load_frozen(ROOT / "frozen", snapshot.season)
    assert frozen.sha256 == meta["params_sha256"]
    draw = load_draw(ROOT / "data" / f"preseason_draw_{snapshot.season}.csv", snapshot.season)
    code_hash = "".join(meta["code_hash"])  # type: ignore[arg-type]  # stored in two halves
    return build_edition(snapshot, frozen, draw, code_hash=code_hash).body


def test_unweighted_fit_reproduces_the_rehearsal_edition_byte_for_byte() -> None:
    meta, games = golden()
    assert sha256_hex(games) == meta["games_sha256"]
    body = rebuild(meta, games)
    doc = json.loads(body)
    assert len(doc["teams"]) == 138  # one fold per FBS team in 2026
    assert [[t["team_id"], t["open_rank"], t["total_cp"]] for t in doc["teams"][:25]] == meta["top25"]
    assert sha256_hex(body) == meta["sha256"]
