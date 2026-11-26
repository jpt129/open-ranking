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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
AT_LARGE: Final = ("at_large", "top_four")
METHOD: Final = (
    "Results are held fixed. In each refit every fitted game gets one exponential weight of mean one, which "
    "multiplies that game's squared error in the strength fit; the same weight is used in every team's fold. "
    "The ridge penalties and the frozen settings are unchanged. The bubble band, every ledger total, the "
    "order and the bracket are then worked again.",
    "Ranges are the middle 80% of refits: at most a tenth of the refits lie beyond each end.",
    "Margin to the cut line is the team's total minus the total of the last at-large team in the field in "
    "the same refit. It is the headline number: the raw change in points moves with the bubble level.",
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


def gate_indices(sha256: str, refits: int, count: int = GATE_SAMPLE) -> list[int]:
    """Which refits the gate reruns: chosen by the edition's hash, so they cannot be known beforehand."""
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
) -> Built:
    """The report document for one edition. Reads nothing and writes nothing."""
    if refits < 1:
        raise SensitivityRefused("at least one refit")
    season = int(edition["season"])
    order, rank, total = _published(edition)
    try:
        rules = load_rules(season)
        ones = dict.fromkeys(fitted_games(games, Engine(games, params)), 1.0)
        again = weighted_totals(games, params, t, season, ones)
        if again != total or [r.team_id for r in rank_teams(again, games, draw)] != order:
            raise SensitivityRefused(
                "the games, settings and draw given do not reproduce the edition's totals and order"
            )
        champions = decided_champions(games)
        setup = Setup(rules.first_season, order, members, eligible, {}, {}, dict(champions), {}, frozenset())
        stand_ins = dict(sorted(field_today(setup, rules).stand_ins.items()))
        fixed = champions | stand_ins
        now = field_of(rules, order, members=members, eligible=eligible, champions=fixed)
        cut_now = cut_line(now, order)
        seed = edition_seed(str(edition["edition_id"]), sha256)
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
        "edition_id": edition["edition_id"],
        "edition_sha256": sha256,
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
) -> str:
    """Rerun a sample of the report's refits and compare. Raises SensitivityRefused on any difference."""
    same = report.get("edition_id") == edition["edition_id"] and report.get("edition_sha256") == sha256
    if report.get("product") != PRODUCT or not same:
        raise SensitivityRefused("the sensitivity file was written for a different edition")
    seed = edition_seed(str(edition["edition_id"]), sha256)
    if report.get("seed") != seed:
        raise SensitivityRefused("the sensitivity file's seed is not the edition's seed")
    digests = report.get("refit_digests")
    refits = report.get("refits")
    if not isinstance(digests, list) or not isinstance(refits, int) or len(digests) != refits or refits < 1:
        raise SensitivityRefused("the sensitivity file does not list one digest per refit")
    sample = gate_indices(sha256, refits, count)
    try:
        found = run(games, params, t, int(edition["season"]), draw, seed=seed, indices=sample)
    except (SensitivityError, StrengthError, ValueError) as error:
        raise SensitivityRefused(f"the refits cannot be rerun: {error}") from error
    for one in found:
        if one.digest() != digests[one.index]:
            raise SensitivityRefused(f"refit {one.index} does not reproduce the published digest")
    return (
        f"{len(sample)} of {refits} refits rerun and matched; the sample is chosen by the edition's hash "
        "(reported; a failure here does not block the edition)"
    )
