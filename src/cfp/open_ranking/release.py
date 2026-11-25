"""Open Ranking edition document (OR-08, RL-01a, RL-02).

One canonical JSON document per edition: a manifest that pins the input snapshot, the hand-kept lists, the
frozen parameters, the formula and the draw, then every team's ledger in final order. Everything computed is
an integer; the only floats are the frozen parameter values, copied from their file. The same snapshot,
parameters, draw and code give the same bytes.

This module builds the document. Writing it to the editions folder is the `cfp` command's job.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from cfp.common.hashing import sha256_hex
from cfp.open_ranking import RULE_VERSION_ID
from cfp.open_ranking.band import band_ranks, field_size
from cfp.open_ranking.frozen import Frozen
from cfp.open_ranking.ledger import FCS_LOSS_CP, FCS_WIN_CP, build_ledgers
from cfp.open_ranking.link import BOUNDARY, SCALE
from cfp.open_ranking.ordering import WINDOW_CP, rank_teams
from cfp.snapshot.build import Snapshot

PRODUCT: Final = "open_ranking"
FORMULA_SOURCES: Final = ("strength.py", "band.py", "link.py", "ledger.py", "ordering.py")


class ReleaseError(RuntimeError):
    """An edition cannot be built from these inputs."""


@dataclass(frozen=True)
class Built:
    edition_id: str
    doc: dict[str, Any]
    body: bytes
    sha256: str
    inputs: list[str]


def _canonical(doc: Any) -> bytes:
    """Sorted keys, no spaces, ASCII, one trailing newline (the same bytes cfp.release.edition writes)."""
    text = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return text.encode() + b"\n"


def formula_hash(frozen: Frozen, season: int) -> str:
    """SHA-256 over the rule version, the frozen parameters, the fixed constants and the formula's source."""
    here = Path(__file__).parent
    pinned = {
        "rule_version_id": RULE_VERSION_ID,
        "params_sha256": frozen.sha256,
        "field_size": field_size(season),
        "band_ranks": list(band_ranks(season)),
        "window_cp": WINDOW_CP,
        "fcs_win_cp": FCS_WIN_CP,
        "fcs_loss_cp": FCS_LOSS_CP,
        "scale": SCALE,
        "boundary": repr(BOUNDARY),
        "source": {name: sha256_hex((here / name).read_bytes()) for name in FORMULA_SOURCES},
    }
    return sha256_hex(_canonical(pinned))


def _draw_hash(draw: Mapping[str, int]) -> str:
    return sha256_hex("\n".join(f"{team}|{place}" for team, place in sorted(draw.items())).encode())


def _previous_ledgers(previous: Built) -> dict[tuple[str, str], int]:
    return {(t["team_id"], r["game_id"]): r["points_cp"] for t in previous.doc["teams"] for r in t["rows"]}


def build_edition(
    snapshot: Snapshot,
    frozen: Frozen,
    draw: Mapping[str, int],
    *,
    code_hash: str,
    revision: int = 1,
    previous: Built | None = None,
) -> Built:
    """The edition for one snapshot. `previous` is the last edition, for each row's revision since then."""
    if revision < 1:
        raise ReleaseError("revision starts at 1")
    if frozen.season != snapshot.season:
        raise ReleaseError(f"parameters are for season {frozen.season}; the snapshot is {snapshot.season}")
    if frozen.rule_version_id != RULE_VERSION_ID:
        raise ReleaseError(
            f"parameters were frozen under rule version {frozen.rule_version_id}; code is {RULE_VERSION_ID}"
        )
    live = snapshot.mode == "live"
    if live and (code_hash == "unknown" or code_hash.endswith("-dirty")):
        raise ReleaseError("a live edition needs committed code")
    cutoff = snapshot.cutoff
    offset = cutoff.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ReleaseError("the snapshot cutoff must be in UTC")
    stem = f"or-{snapshot.season}-{cutoff.strftime('%Y%m%dt%H%Mz')}" + ("" if live else "-replay")
    edition_id = f"{stem}-e{revision}"
    if previous is not None:
        earlier = (
            previous.doc["season"] == snapshot.season and previous.doc["cutoff_utc"] < cutoff.isoformat()
        )
        if not earlier or previous.doc["product"] != PRODUCT:
            raise ReleaseError(f"{previous.edition_id} is not earlier in the same season")

    ledgers = build_ledgers(snapshot.games, frozen.params, frozen.t, snapshot.season)
    old = _previous_ledgers(previous) if previous is not None else {}
    ranked = rank_teams({team: ledger.total_cp for team, ledger in ledgers.items()}, snapshot.games, draw)
    teams: list[dict[str, Any]] = []
    boundary_rows = 0
    for place in ranked:
        ledger = ledgers[place.team_id]
        rows: list[dict[str, Any]] = []
        for row in ledger.rows:
            key = (ledger.team_id, row.game_id)
            change = row.points_cp - old[key] if previous is not None and key in old else None
            boundary_rows += row.boundary
            rows.append(
                {
                    "game_id": row.game_id,
                    "week": row.week,
                    "opponent_id": row.opponent_id,
                    "site": row.site,
                    "result": row.result,
                    "title_game": row.title_game,
                    "q": row.q,
                    "boundary": row.boundary,
                    "points_cp": row.points_cp,
                    "policy_exception": row.policy_exception,
                    "revision_cp": change,
                }
            )
        if ledger.total_cp != sum(item["points_cp"] for item in rows):
            raise ReleaseError(f"{ledger.team_id}: the total is not the sum of its rows")
        wins = sum(1 for item in rows if item["result"] == "W")
        teams.append(
            {
                "team_id": place.team_id,
                "total_cp": place.total_cp,
                "raw_rank": place.raw_rank,
                "group": place.group,
                "head_to_head": place.head_to_head,
                "open_rank": place.open_rank,
                "order": place.order,
                "wins": wins,
                "losses": len(rows) - wins,
                "band": list(ledger.band),
                "rule_version_id": ledger.rule_version_id,
                "rows": rows,
            }
        )
    omissions = {
        str(reason): int(count)
        for reason, count in snapshot.omissions.group_by("reason").len().sort("reason").iter_rows()
    }
    draw_hash = _draw_hash(draw)
    manifest = {
        "snapshot_hash": snapshot.snapshot_hash,
        "lists_hash": snapshot.lists_hash,
        "params_sha256": frozen.sha256,
        "params": {
            "lambda_c": frozen.params.lambda_c,
            "lambda_u": frozen.params.lambda_u,
            "t": frozen.t,
            "cap": frozen.params.cap,
            "independent_penalty": frozen.params.independent_penalty,
            "status": frozen.status,
        },
        "formula_hash": formula_hash(frozen, snapshot.season),
        "draw_hash": draw_hash,
        "code_hash": code_hash,
        "rule_version_id": RULE_VERSION_ID,
        "band_ranks": list(band_ranks(snapshot.season)),
        "games": snapshot.games.height,
        "omissions": omissions,
        "boundary_rows": boundary_rows,
        "second_implementation": "not run",
    }
    doc = {
        "product": PRODUCT,
        "edition_id": edition_id,
        "season": snapshot.season,
        "cutoff_utc": cutoff.isoformat(),
        "mode": snapshot.mode,
        "revision": revision,
        "supersedes": f"{stem}-e{revision - 1}" if revision > 1 else None,
        "previous_edition": (
            {"edition_id": previous.edition_id, "sha256": previous.sha256} if previous is not None else None
        ),
        "manifest": manifest,
        "teams": teams,
    }
    body = _canonical(doc)
    inputs = [
        f"snapshot:{snapshot.snapshot_hash}",
        f"lists:{snapshot.lists_hash}",
        f"params:{frozen.sha256}",
        f"draw:{draw_hash}",
    ]
    return Built(edition_id, doc, body, sha256_hex(body), inputs)


def load_built(edition_json: bytes) -> Built:
    """A published edition read back from its bytes, to serve as `previous`."""
    doc = json.loads(edition_json)
    if doc.get("product") != PRODUCT:
        raise ReleaseError("not an Open Ranking edition")
    return Built(doc["edition_id"], doc, edition_json, sha256_hex(edition_json), [])
