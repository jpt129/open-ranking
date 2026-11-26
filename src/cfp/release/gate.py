"""The release gate for an Open Ranking edition (RL-01, RL-01a).

The gate reads a written edition folder and checks it against its own files, the frozen parameters and the
draw. It writes nothing. Any failed check blocks publication. Until a second implementation exists, its state
is recorded as "not run" and does not fail the gate.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Any, Final

import polars as pl

from cfp.open_ranking.frozen import load_frozen
from cfp.open_ranking.ledger import FCS_LOSS_CP, FCS_WIN_CP
from cfp.open_ranking.link import SCALE
from cfp.open_ranking.release import PRODUCT, build_edition, formula_hash, load_built
from cfp.snapshot.build import COLUMNS, Snapshot, game_lines

CHECKS: Final = (
    "hash",
    "games file",
    "ledger sums",
    "row arithmetic",
    "results",
    "inputs",
    "frozen parameters",
    "rebuild",
    "ranks",
    "second implementation",
)
SECOND_OK: Final = ("not run", "match")


class GateFailure(Exception):
    """One check failed; the message says why."""


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class Report:
    edition_id: str
    sha256: str
    second_implementation: str
    checks: tuple[Check, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def document(self) -> dict[str, Any]:
        return {
            "edition_id": self.edition_id,
            "sha256": self.sha256,
            "passed": self.passed,
            "second_implementation": self.second_implementation,
            "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in self.checks],
        }


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def games_from_lines(body: bytes) -> pl.DataFrame:
    """The snapshot's games read back from the published file."""
    rows = [json.loads(line) for line in body.splitlines() if line]
    text = {
        name: pl.String for name in ("home_conf", "away_conf", "site", "raw_hash", "home_div", "away_div")
    }
    whole = {name: pl.Int32 for name in ("season", "week", "home_pts", "away_pts", "correction_version")}
    frame = pl.DataFrame(
        rows, schema_overrides={k: v for k, v in (text | whole).items() if rows and k in rows[0]}
    )
    if "start_utc" in frame.columns:
        frame = frame.with_columns(pl.col("start_utc").str.to_datetime(time_zone="UTC"))
    if set(COLUMNS) <= set(frame.columns):
        frame = frame.select([*COLUMNS, *[c for c in frame.columns if c not in COLUMNS]])
    return frame


def run_gate(
    folder: Path,
    *,
    frozen_root: Path | str,
    draw: Mapping[str, int],
    recorded: Mapping[str, str],
) -> Report:
    """Every check on the edition in `folder`. `recorded` maps edition ids to the store's hashes."""
    body = (folder / "edition.json").read_bytes()
    doc = json.loads(body)
    if doc.get("product") != PRODUCT:
        raise ValueError(f"{folder.name} is not an Open Ranking edition")
    manifest = doc["manifest"]
    games_body = (folder / "games.jsonl").read_bytes() if (folder / "games.jsonl").is_file() else b""
    games = {g["game_id"]: g for g in (json.loads(line) for line in games_body.splitlines() if line)}
    data_as_of = datetime.fromisoformat(doc["data_as_of_utc"])
    cutoff_at = datetime.fromisoformat(doc["cutoff_utc"])
    recorded_sha256 = recorded.get(doc["edition_id"])

    def hash_() -> str:
        receipt = json.loads((folder / "receipt.json").read_bytes())
        mine = _sha(body)
        if doc["edition_id"] != folder.name or receipt.get("edition_id") != folder.name:
            raise GateFailure("the folder, the receipt and the document do not name the same edition")
        if receipt.get("sha256") != mine:
            raise GateFailure("the file's hash is not the hash in its receipt")
        if recorded_sha256 is None:
            raise GateFailure("the edition is not recorded in the store")
        if recorded_sha256 != mine:
            raise GateFailure("the file's hash is not the hash recorded at issue")
        return f"sha256 {mine} matches the receipt and the store"

    def games_file() -> str:
        if _sha(games_body) != manifest["games_sha256"]:
            raise GateFailure("games.jsonl is not the file the manifest names")
        if len(games) != manifest["games"]:
            raise GateFailure(f"{len(games)} games in the file, {manifest['games']} in the manifest")
        if _sha(f"season={doc['season']}\n".encode() + games_body) != manifest["snapshot_hash"]:
            raise GateFailure("the games do not hash to the snapshot hash")
        return f"{len(games)} games hash to the snapshot"

    def ledger_sums() -> str:
        for team in doc["teams"]:
            points = [row["points_cp"] for row in team["rows"]]
            if any(isinstance(p, bool) or not isinstance(p, int) for p in [*points, team["total_cp"]]):
                raise GateFailure(f"{team['team_id']}: points are not whole centipoints")
            if sum(points) != team["total_cp"]:
                raise GateFailure(
                    f"{team['team_id']}: rows sum to {sum(points)}, total is {team['total_cp']}"
                )
            wins = sum(1 for row in team["rows"] if row["result"] == "W")
            if (team["wins"], team["losses"]) != (wins, len(points) - wins):
                raise GateFailure(f"{team['team_id']}: the record does not match its rows")
        return f"{len(doc['teams'])} teams: every total is the sum of its rows"

    def row_arithmetic() -> str:
        count = 0
        for team in doc["teams"]:
            for row in team["rows"]:
                where = f"{team['team_id']} {row['game_id']}"
                won = row["result"] == "W"
                if row["result"] not in ("W", "L"):
                    raise GateFailure(f"{where}: result {row['result']!r}")
                if row["policy_exception"] in ("fcs_win", "fcs_loss"):
                    want = FCS_WIN_CP if won else FCS_LOSS_CP
                    if (row["policy_exception"] == "fcs_win") != won:
                        raise GateFailure(f"{where}: the FCS label does not match the result")
                else:
                    q = row["q"]
                    if isinstance(q, bool) or not isinstance(q, int) or not 0 <= q <= SCALE:
                        raise GateFailure(f"{where}: q is {q!r}")
                    want = SCALE - q if won else -q
                if row["points_cp"] != want:
                    raise GateFailure(f"{where}: points are {row['points_cp']}, the rule gives {want}")
                count += 1
        return f"{count} rows: win {SCALE} - q, loss -q, FCS win {FCS_WIN_CP}, FCS loss {FCS_LOSS_CP}"

    def results() -> str:
        seen: dict[str, int] = {}
        for team in doc["teams"]:
            for row in team["rows"]:
                where = f"{team['team_id']} {row['game_id']}"
                game = games.get(row["game_id"])
                if game is None:
                    raise GateFailure(f"{where}: the game is not in the games file")
                sides = {game["home_id"], game["away_id"]}
                if team["team_id"] not in sides or row["opponent_id"] not in sides - {team["team_id"]}:
                    raise GateFailure(f"{where}: the teams are not the game's teams")
                if (game["winner_id"] == team["team_id"]) != (row["result"] == "W"):
                    raise GateFailure(f"{where}: the result is not the game's result")
                seen[row["game_id"]] = seen.get(row["game_id"], 0) + 1
        for game_id, game in games.items():
            if not game.get("forfeit"):
                ahead = game["home_id"] if game["home_pts"] > game["away_pts"] else game["away_id"]
                if game["home_pts"] == game["away_pts"] or ahead != game["winner_id"]:
                    raise GateFailure(f"{game_id}: the winner does not match the score")
            fbs = sum(1 for side in ("home_div", "away_div") if game[side] == "fbs")
            if seen.get(game_id, 0) != fbs:
                raise GateFailure(f"{game_id}: in {seen.get(game_id, 0)} ledgers, expected {fbs}")
        return (
            f"{len(games)} games: every ledger row matches its game, and every game is in its teams' ledgers"
        )

    def inputs() -> str:
        for game_id, game in games.items():
            if not datetime.fromisoformat(game["start_utc"]) < cutoff_at:
                raise GateFailure(f"{game_id} kicks off at {game['start_utc']}, not before the cutoff")
            if not game.get("raw_hash"):
                raise GateFailure(f"{game_id} has no raw-source hash")
        if data_as_of != cutoff_at:  # a correction re-reads the superseded edition's games, and no others
            old = folder.parent / str(doc["supersedes"]) / "games.jsonl"
            if not doc["supersedes"] or not old.is_file():
                raise GateFailure("a correction's superseded edition is missing")
            before = {json.loads(line)["game_id"] for line in old.read_bytes().splitlines() if line}
            if before != set(games):
                raise GateFailure("a correction must hold exactly the games of the edition it supersedes")
        want = {
            f"snapshot:{manifest['snapshot_hash']}",
            f"lists:{manifest['lists_hash']}",
            f"params:{manifest['params_sha256']}",
            f"draw:{manifest['draw_hash']}",
        }
        if not want <= set(doc["inputs"]):
            raise GateFailure("the input list does not name the snapshot, lists, parameters and draw")
        return f"every game kicked off before {doc['cutoff_utc']} and carries its raw-source hash"

    def frozen_parameters() -> str:
        frozen = load_frozen(frozen_root, doc["season"])
        if frozen.sha256 != manifest["params_sha256"]:
            raise GateFailure("the frozen parameters file is not the one the edition was built with")
        if formula_hash(frozen, doc["season"]) != manifest["formula_hash"]:
            raise GateFailure("the formula's code or constants have changed since the edition was built")
        return f"parameters {frozen.sha256[:12]} ({frozen.status}) and the formula hash match"

    def rebuild() -> str:
        frame = games_from_lines(games_body)
        if game_lines(frame) != games_body:
            raise GateFailure("the games file does not read back to the same bytes")
        reasons = [reason for reason, count in sorted(manifest["omissions"].items()) for _ in range(count)]
        omissions = pl.DataFrame(
            {"game_id": [f"omitted-{k}" for k in range(len(reasons))], "reason": reasons},
            schema={"game_id": pl.String, "reason": pl.String},
        )
        snapshot = Snapshot(
            doc["season"],
            data_as_of,
            doc["mode"],
            frame,
            omissions,
            manifest["snapshot_hash"],
            manifest["lists_hash"],
        )
        previous = None
        if doc["previous_edition"]:
            named = doc["previous_edition"]
            path = folder.parent / named["edition_id"] / "edition.json"
            if not path.is_file() or _sha(path.read_bytes()) != named["sha256"]:
                raise GateFailure(f"the previous edition {named['edition_id']} is missing or changed")
            if recorded.get(named["edition_id"]) != named["sha256"]:
                raise GateFailure(
                    f"the previous edition {named['edition_id']} is not the one the store recorded"
                )
            previous = load_built(path.read_bytes())
        cutoff = datetime.fromisoformat(doc["cutoff_utc"])
        again = build_edition(
            snapshot,
            load_frozen(frozen_root, doc["season"]),
            draw,
            code_hash=manifest["code_hash"],
            revision=doc["revision"],
            previous=previous,
            cutoff=cutoff if cutoff != data_as_of else None,
        )
        if again.body != body:
            raise GateFailure("building again from the same games, parameters and draw gives different bytes")
        return "the same games, parameters and draw give the same bytes"

    def ranks() -> str:
        teams = doc["teams"]
        if [team["order"] for team in teams] != list(range(1, len(teams) + 1)):
            raise GateFailure("the order is not 1 to n, once each, in sequence")
        if len({team["team_id"] for team in teams}) != len(teams):
            raise GateFailure("a team is listed twice")
        by_total = sorted(teams, key=lambda team: -team["total_cp"])
        for above, below in pairwise(by_total):
            same = above["total_cp"] == below["total_cp"]
            if (above["raw_rank"] == below["raw_rank"]) != same or above["raw_rank"] > below["raw_rank"]:
                raise GateFailure(
                    f"raw ranks of {above['team_id']} and {below['team_id']} do not follow totals"
                )
        for above, below in pairwise(teams):
            if above["open_rank"] > below["open_rank"]:
                raise GateFailure(f"{above['team_id']} is listed above {below['team_id']} with a worse rank")
        return f"{len(teams)} teams in one order; raw ranks follow totals"

    def second_implementation() -> str:
        state = manifest.get("second_implementation")
        if state not in SECOND_OK:
            raise GateFailure(f"second implementation: {state}")
        if state == "not run":
            return "not run (recorded; the gate does not fail on it in the pilot)"
        return "match"

    steps: dict[str, Callable[[], str]] = {
        "hash": hash_,
        "games file": games_file,
        "ledger sums": ledger_sums,
        "row arithmetic": row_arithmetic,
        "results": results,
        "inputs": inputs,
        "frozen parameters": frozen_parameters,
        "rebuild": rebuild,
        "ranks": ranks,
        "second implementation": second_implementation,
    }
    checks = []
    for name in CHECKS:
        try:
            checks.append(Check(name, True, steps[name]()))
        except GateFailure as error:
            checks.append(Check(name, False, str(error)))
        except Exception as error:  # a check that cannot run has not passed
            checks.append(Check(name, False, f"{type(error).__name__}: {error}"))
    return Report(doc["edition_id"], _sha(body), str(manifest.get("second_implementation")), tuple(checks))
