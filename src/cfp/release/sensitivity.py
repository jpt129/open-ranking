"""The sensitivity report for one Open Ranking edition (VT-08), and the gate's check of it.

The refits themselves are in `cfp.open_ranking.sensitivity`. This module runs each refit's order through the
season's bracket rules, which the Open Ranking package may not reach, and writes the summary.

The bracket scenario is fixed before any refit: a champion decided in the edition's own games is used, and
where a title is not decided the conference's best-placed team in the published order stands in, the same
team in every refit. The place that goes to the best team of the other six conferences is not a title, so it
is worked again from each refit's order.

The report is a separate write-once file. It names the edition by hash; the edition does not name it.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import polars as pl

from cfp.forecast.final_field import FieldError, Setup, field_today
from cfp.open_ranking.ordering import rank_teams
from cfp.open_ranking.sensitivity import (
    LABEL,
    REFITS,
    SensitivityError,
    edition_seed,
    fitted_games,
    middle80,
    run,
    weighted_totals,
)
from cfp.open_ranking.strength import Engine, Params, StrengthError
from cfp.release.edition import canonical
from cfp.rules.engine import Entry, SeasonRules, load_rules

SCHEMA: Final = 1
PRODUCT: Final = "open_ranking_sensitivity"
GATE_SAMPLE: Final = 10
REQUIRED_REFITS = REFITS  # VT-08's number; a file with any other count is neither written nor published
ROW_KEYS: Final = (
    "team_id",
    "open_rank",
    "total_cp",
    "rank_80",
    "rank_diff_80",
    "cut_margin_cp",
    "cut_margin_cp_80",
    "points_diff_cp_80",
    "qualifies",
    "in_field_as_published",
)
AT_LARGE: Final = ("at_large", "top_four")
METHOD: Final = (
    "Results are held fixed. In each refit every fitted game gets one exponential weight of mean one, which "
    "multiplies that game's squared error in the strength fit; the same weight is used in every team's fold. "
    "The ridge penalties and the frozen settings are unchanged. The bubble band, every ledger total, the "
    "order and the bracket are then worked again.",
    "Ranges are the middle 80% of refits: at most a tenth of the refits lie beyond each end.",
    "Margin to the cut line is the team's total minus the total of the last at-large team in the field in "
    "the same refit. It is the headline number: the raw change in points moves with the bubble level.",
    "The cut line is the at-large line only. A team can be in the field below it (a conference champion, the "
    "place for the best team of the other conferences, or a guarantee) and out of it above (a team ruled "
    "ineligible). Head-to-head can also put a team one place above another with a slightly higher total.",
    "Each refit has its own seed, derived from the edition seed and the refit's index. The digests are a "
    "hash of each refit's order and totals, so any refit can be rerun alone and compared.",
)


class SensitivityRefused(ValueError):
    """The report cannot be built, or a written report does not check out."""


@dataclass(frozen=True)
class Built:
    doc: dict[str, Any]
    body: bytes
    sha256: str


def decided_champions(games: pl.DataFrame) -> dict[str, str]:
    """Conference -> winner, for every title game among the edition's own games."""
    out: dict[str, str] = {}
    for g in games.filter(pl.col("title_game")).sort("game_id").iter_rows(named=True):
        league = g["home_conf"]
        if league is None or g["away_conf"] != league:
            raise SensitivityRefused(f"title game {g['game_id']} is not between two teams of one conference")
        if league in out:
            raise SensitivityRefused(f"two title games are on file for {league}")
        out[str(league)] = str(g["winner_id"])
    return out


def field_of(
    rules: SeasonRules,
    order: Sequence[str],
    *,
    members: Mapping[str, str],
    eligible: Mapping[str, bool],
    champions: Mapping[str, str],
) -> list[Entry]:
    """The teams in the field for one order, with every champion already named. Refuses to pick a stand-in."""
    setup = Setup(
        rules.first_season, list(order), members, eligible, {}, {}, dict(champions), {}, frozenset()
    )
    try:
        today = field_today(setup, rules)
    except FieldError as error:
        raise SensitivityRefused(f"the order cannot be run through the bracket rules: {error}") from error
    if today.stand_ins:
        raise SensitivityRefused(
            f"no champion or stand-in was fixed for: {', '.join(sorted(today.stand_ins))}"
        )
    return [entry for entry in today.entries if entry.qualifier]


def cut_line(entries: Sequence[Entry], order: Sequence[str]) -> str:
    """The last at-large team in the field: the lowest-placed team that is in on its ranking alone."""
    place = {team: k for k, team in enumerate(order)}
    at_large = [entry.team_id for entry in entries if entry.route in AT_LARGE]
    if not at_large:
        raise SensitivityRefused("the field has no at-large team, so there is no cut line")
    return max(at_large, key=lambda team: place[team])


def folder_name(edition_id: str, revision: int) -> str:
    """The report's folder: the edition id, then -s2, -s3, ... for a corrected report."""
    if revision < 1:
        raise SensitivityRefused("a revision is 1 or more")
    return edition_id if revision == 1 else f"{edition_id}-s{revision}"


def latest_file(root: Path, edition_id: str) -> Path | None:
    """The newest sensitivity file written for the edition, or None."""
    if not root.is_dir():
        return None
    name = re.compile(rf"^{re.escape(edition_id)}(?:-s(\d+))?$")
    held = [(int(m.group(1) or 1), p) for p in root.iterdir() if (m := name.match(p.name))]
    held = [(k, p) for k, p in held if (p / "sensitivity.json").is_file()]
    return max(held)[1] / "sensitivity.json" if held else None


def gate_indices(sha256: str, refits: int, count: int = GATE_SAMPLE) -> list[int]:
    """Which refits the gate reruns, chosen by the edition's hash rather than always the first ten.

    Whoever builds the file knows the edition's hash, so this catches drift and damage, not a forger.
    """
    if refits <= count:
        return list(range(refits))
    chosen: list[int] = []
    k = 0
    while len(chosen) < count:
        digest = hashlib.sha256(f"vt08-gate|{sha256}|{k}".encode()).digest()
        index = int.from_bytes(digest[:8], "big") % refits
        if index not in chosen:
            chosen.append(index)
        k += 1
    return sorted(chosen)


def _published(edition: Mapping[str, Any]) -> tuple[list[str], dict[str, int], dict[str, int]]:
    teams = sorted(edition["teams"], key=lambda team: team["order"])
    order = [str(team["team_id"]) for team in teams]
    return (
        order,
        {str(team["team_id"]): int(team["open_rank"]) for team in teams},
        {str(team["team_id"]): int(team["total_cp"]) for team in teams},
    )


@dataclass(frozen=True)
class _Scenario:
    rules: SeasonRules
    champions: dict[str, str]  # decided in the edition's own games
    stand_ins: dict[str, str]
    fixed: dict[str, str]  # what every refit uses
    field: list[Entry]  # the published order's field
    cut: str


def _scenario(
    season: int,
    order: Sequence[str],
    games: pl.DataFrame,
    members: Mapping[str, str],
    eligible: Mapping[str, bool],
) -> _Scenario:
    rules = load_rules(season)
    champions = decided_champions(games)
    setup = Setup(
        rules.first_season, list(order), members, eligible, {}, {}, dict(champions), {}, frozenset()
    )
    stand_ins = dict(sorted(field_today(setup, rules).stand_ins.items()))
    fixed = champions | stand_ins
    now = field_of(rules, order, members=members, eligible=eligible, champions=fixed)
    return _Scenario(rules, champions, stand_ins, fixed, now, cut_line(now, order))


def build_sensitivity(
    edition: Mapping[str, Any],
    sha256: str,
    games: pl.DataFrame,
    params: Params,
    t: float,
    draw: Mapping[str, int],
    *,
    members: Mapping[str, str],
    eligible: Mapping[str, bool],
    code_hash: str,
    refits: int = REFITS,
    workers: int = 1,
    revision: int = 1,
) -> Built:
    """The report document for one edition. Reads nothing and writes nothing."""
    if refits < 1:
        raise SensitivityRefused("at least one refit")
    edition_id = str(edition["edition_id"])
    folder_name(edition_id, revision)
    season = int(edition["season"])
    order, rank, total = _published(edition)
    # only the edition's teams: the file records exactly the bracket inputs that were used
    members = {team: str(members[team]) for team in order if members.get(team)}
    eligible = {team: bool(eligible.get(team, True)) for team in order}
    try:
        ones = dict.fromkeys(fitted_games(games, Engine(games, params)), 1.0)
        again = weighted_totals(games, params, t, season, ones)
        if again != total or [r.team_id for r in rank_teams(again, games, draw)] != order:
            raise SensitivityRefused(
                "the games, settings and draw given do not reproduce the edition's totals and order"
            )
        scene = _scenario(season, order, games, members, eligible)
        rules, champions, stand_ins, fixed = scene.rules, scene.champions, scene.stand_ins, scene.fixed
        now, cut_now = scene.field, scene.cut
        seed = edition_seed(edition_id, sha256)
        found = run(games, params, t, season, draw, seed=seed, indices=range(refits), workers=workers)
        qualifies = dict.fromkeys(order, 0)
        margins: dict[str, list[int]] = {team: [] for team in order}
        for one in found:
            if set(one.totals) != set(order):
                raise SensitivityRefused(f"refit {one.index} does not rank the edition's teams")
            entries = field_of(rules, one.order, members=members, eligible=eligible, champions=fixed)
            cut = one.totals[cut_line(entries, one.order)]
            for entry in entries:
                qualifies[entry.team_id] += 1
            for team in order:
                margins[team].append(one.totals[team] - cut)
    except (SensitivityError, StrengthError, FieldError, ValueError) as error:
        if isinstance(error, SensitivityRefused):
            raise
        raise SensitivityRefused(str(error)) from error
    rows = []
    for team in order:
        moves = middle80([one.ranks[team] - rank[team] for one in found])
        rows.append(
            {
                "team_id": team,
                "open_rank": rank[team],
                "total_cp": total[team],
                "rank_80": [rank[team] + moves[0], rank[team] + moves[1]],
                "rank_diff_80": moves,
                "cut_margin_cp": total[team] - total[cut_now],
                "cut_margin_cp_80": middle80(margins[team]),
                "points_diff_cp_80": middle80([one.totals[team] - total[team] for one in found]),
                "qualifies": qualifies[team],
                "in_field_as_published": team in {entry.team_id for entry in now},
            }
        )
    if stand_ins:
        note = (
            "Provisional: where a title is not decided, the conference's best-placed team in the published "
            "order stands in for its champion, the same team in every refit. That is an assumption, not a "
            "forecast."
        )
    else:
        note = "Final: every refit uses the conference champions decided on the field."
    note += (
        " The place for the best team from the other conferences is not a title; it goes to the "
        "best-placed such team in each refit's own order."
    )
    document = {
        "schema": SCHEMA,
        "product": PRODUCT,
        "edition_id": edition_id,
        "edition_sha256": sha256,
        "revision": revision,
        "supersedes": folder_name(edition_id, revision - 1) if revision > 1 else None,
        "season": season,
        "label": LABEL,
        "method": list(METHOD),
        "seed": seed,
        "refits": refits,
        "code_hash": code_hash,
        "scenario": {
            "provisional": bool(stand_ins),
            "champions": dict(sorted(champions.items())),
            "stand_ins": stand_ins,
            "note": note,
        },
        "cut_line": {
            "definition": "the last at-large team in the field, in the same refit",
            "published": cut_now,
        },
        "field_as_published": [entry.team_id for entry in sorted(now, key=lambda e: e.seed or 0)],
        "bracket_inputs": {
            "conference_of": dict(sorted(members.items())),
            "ineligible": sorted(team for team, flag in eligible.items() if not flag),
            "source": "the store's membership and eligibility tables as of the edition's data time",
        },
        "teams": rows,
        "refit_digests": [one.digest() for one in found],
    }
    body = canonical(document)
    return Built(document, body, hashlib.sha256(body).hexdigest())


def verify(
    report: Mapping[str, Any],
    edition: Mapping[str, Any],
    sha256: str,
    games: pl.DataFrame,
    params: Params,
    t: float,
    draw: Mapping[str, int],
    *,
    count: int = GATE_SAMPLE,
    required: int | None = None,
) -> str:
    """Check a written report against its edition. Raises SensitivityRefused on any difference.

    Checked in full: the label, the refit count, every team's published rank and total, and the published
    field, cut line and margins, which are worked again from the bracket inputs the file records. Checked
    by sample: the refits themselves. The ranges and qualify counts are not recomputed.
    """
    required = REQUIRED_REFITS if required is None else required
    if not isinstance(report, Mapping):
        raise SensitivityRefused("the sensitivity file is not a document")
    same = report.get("edition_id") == edition["edition_id"] and report.get("edition_sha256") == sha256
    if report.get("product") != PRODUCT or not same:
        raise SensitivityRefused("the sensitivity file was written for a different edition")
    if report.get("schema") != SCHEMA:
        raise SensitivityRefused(f"the sensitivity file's schema is {report.get('schema')!r}, not {SCHEMA}")
    if report.get("label") != LABEL:
        raise SensitivityRefused("the sensitivity file's label is not the published wording")
    seed = edition_seed(str(edition["edition_id"]), sha256)
    if report.get("seed") != seed:
        raise SensitivityRefused("the sensitivity file's seed is not the edition's seed")
    digests = report.get("refit_digests")
    refits = report.get("refits")
    if not isinstance(digests, list) or not isinstance(refits, int) or len(digests) != refits or refits < 1:
        raise SensitivityRefused("the sensitivity file does not list one digest per refit")
    if refits != required:
        raise SensitivityRefused(f"the sensitivity file has {refits} refits; {required} are required")
    order, rank, total = _published(edition)
    try:
        rows = list(report["teams"])
        for row in rows:
            for key in ROW_KEYS:
                value = row[key]
                parts = value if isinstance(value, list) else [value]
                if key != "team_id" and not all(isinstance(part, int) for part in parts):
                    raise SensitivityRefused(f"{row['team_id']}: {key} is not whole numbers")
            if any(len(row[key]) != 2 for key in ROW_KEYS if key.endswith("_80")):
                raise SensitivityRefused(f"{row['team_id']}: a range does not have two ends")
            if not 0 <= row["qualifies"] <= refits:
                raise SensitivityRefused(f"{row['team_id']}: in the field in {row['qualifies']} refits")
        if [row["team_id"] for row in rows] != order:
            raise SensitivityRefused("the sensitivity file does not list the edition's teams in its order")
        inputs = report["bracket_inputs"]
        members = {str(team): str(league) for team, league in inputs["conference_of"].items()}
        barred = set(inputs["ineligible"])
        scene = _scenario(
            int(edition["season"]), order, games, members, {team: team not in barred for team in order}
        )
        said = report["scenario"]
        if (said["champions"], said["stand_ins"]) != (dict(sorted(scene.champions.items())), scene.stand_ins):
            raise SensitivityRefused("the champions and stand-ins are not the published order's")
        if said["provisional"] != bool(scene.stand_ins) or not isinstance(said["note"], str):
            raise SensitivityRefused("the scenario is not stated as it was run")
        if report["cut_line"]["published"] != scene.cut:
            raise SensitivityRefused("the cut line is not the published field's last at-large team")
        field = [entry.team_id for entry in sorted(scene.field, key=lambda e: e.seed or 0)]
        if report["field_as_published"] != field:
            raise SensitivityRefused("the field is not the published order's field")
        for row in rows:
            team = row["team_id"]
            want = (rank[team], total[team], total[team] - total[scene.cut], team in field)
            have = (row["open_rank"], row["total_cp"], row["cut_margin_cp"], row["in_field_as_published"])
            if have != want:
                raise SensitivityRefused(f"{team}: its published rank, total or margin is not the edition's")
        if sum(row["qualifies"] for row in rows) != refits * len(field):
            raise SensitivityRefused("the qualify counts do not add up to one full field per refit")
    except SensitivityRefused:
        raise
    except (KeyError, TypeError, AttributeError, ValueError, FieldError) as error:
        raise SensitivityRefused(
            f"the sensitivity file is not in the expected form: {type(error).__name__}: {error}"
        ) from error
    sample = gate_indices(sha256, refits, count)
    try:
        found = run(games, params, t, int(edition["season"]), draw, seed=seed, indices=sample)
    except (SensitivityError, StrengthError, ValueError) as error:
        raise SensitivityRefused(f"the refits cannot be rerun: {error}") from error
    for one in found:
        if one.digest() != digests[one.index]:
            raise SensitivityRefused(f"refit {one.index} does not reproduce the published digest")
    return (
        f"{len(sample)} of {refits} refits rerun and matched (sample chosen by the edition's hash); the "
        "published ranks, totals, field and cut line were worked again. Reported: a failure here does not "
        "block the edition"
    )


def verify_file(path: Path) -> dict[str, Any]:
    """The written report, after checking its bytes against the receipt beside it."""
    body = path.read_bytes()
    receipt = json.loads((path.parent / "receipt.json").read_bytes())
    if receipt.get("sha256") != hashlib.sha256(body).hexdigest():
        raise SensitivityRefused("the sensitivity file's hash is not the hash in its receipt")
    report = json.loads(body)
    if not isinstance(report, dict):
        raise SensitivityRefused("the sensitivity file is not a document")
    return report
