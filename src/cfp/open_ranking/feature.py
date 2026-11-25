"""Open points as a feature build (SC-04a).

The public entry point other products use to get open points at their own cutoff. It runs the same ledger code
as a published edition on a snapshot, with the same frozen parameters, so a feature build and an edition on
the same snapshot have byte-identical ledgers. A feature build is never an edition and is never published as
one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cfp.common.hashing import sha256_hex
from cfp.open_ranking import RULE_VERSION_ID
from cfp.open_ranking.frozen import Frozen
from cfp.open_ranking.ledger import build_ledgers, row_dict
from cfp.open_ranking.release import formula_hash
from cfp.snapshot.build import Snapshot


@dataclass(frozen=True)
class FeatureBuild:
    feature_build_id: str
    points: dict[str, int]  # team -> total centipoints
    rows: dict[str, list[dict[str, Any]]]  # team -> ledger rows, as an edition would publish them
    snapshot_hash: str
    lists_hash: str
    params_sha256: str
    formula_hash: str
    rule_version_id: str


def feature_build(snapshot: Snapshot, frozen: Frozen) -> FeatureBuild:
    if frozen.season != snapshot.season:
        raise ValueError(f"parameters are for season {frozen.season}; the snapshot is {snapshot.season}")
    if frozen.rule_version_id != RULE_VERSION_ID:
        raise ValueError(f"parameters were frozen under {frozen.rule_version_id}; code is {RULE_VERSION_ID}")
    ledgers = build_ledgers(snapshot.games, frozen.params, frozen.t, snapshot.season)
    formula = formula_hash(frozen, snapshot.season)
    pinned = f"{snapshot.snapshot_hash}|{frozen.sha256}|{formula}|{RULE_VERSION_ID}"
    return FeatureBuild(
        f"orf:{sha256_hex(pinned.encode())}",
        {team: ledger.total_cp for team, ledger in ledgers.items()},
        {team: [row_dict(row) for row in ledger.rows] for team, ledger in ledgers.items()},
        snapshot.snapshot_hash,
        snapshot.lists_hash,
        frozen.sha256,
        formula,
        RULE_VERSION_ID,
    )
