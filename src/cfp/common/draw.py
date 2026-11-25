"""The tiebreak draw (SC-03): a fixed order of the season's FBS teams, published before it is used.

A team's place is the rank of SHA-256("<phrase>|<team_id>"), so the draw depends on nothing but the recorded
phrase and can be reproduced in any language. The phrase is the recorded seed.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

from cfp.common.hashing import sha256_hex

PHRASE = "open-ranking tiebreak draw {season}"


def draw_positions(team_ids: Iterable[str], phrase: str) -> dict[str, int]:
    """Each team's place in the draw, 1 first."""
    ordered = sorted(set(team_ids), key=lambda team: (sha256_hex(f"{phrase}|{team}".encode()), team))
    return {team: position for position, team in enumerate(ordered, start=1)}


def load_draw(path: Path | str, season: int) -> dict[str, int]:
    """The published draw for a season. Columns: season, position, team_id, name."""
    out: dict[str, int] = {}
    with Path(path).open(newline="") as handle:
        for row in csv.DictReader(handle):
            if int(row["season"]) != season:
                raise ValueError(f"{path}: row for season {row['season']} in the {season} draw")
            if row["team_id"] in out:
                raise ValueError(f"{path}: {row['team_id']} is drawn twice")
            out[row["team_id"]] = int(row["position"])
    if sorted(out.values()) != list(range(1, len(out) + 1)):
        raise ValueError(f"{path}: positions are not 1..{len(out)}")
    return out
