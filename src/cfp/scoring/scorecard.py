"""The scorecard for one committee release: every edition issued for that reveal, scored (VT-11, VT-13).

Nothing here changes an edition. A scorecard is written once; a correction is a new numbered scorecard.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import polars as pl

from cfp.forecast.observations import fbs_field
from cfp.forecast.pairings import conference_id as conference_key
from cfp.forecast.rank_noise import published_probability
from cfp.ingest.cfp_releases import load_schedule
from cfp.open_ranking.strength import INDEPENDENT
from cfp.release.edition import canonical
from cfp.release.history import past_champions
from cfp.release.issue import PRODUCT
from cfp.rules.engine import Entry, RulesError, load_rules, select_field
from cfp.scoring.field import FieldRow, field_scores
from cfp.scoring.integrity import IntegrityError, check_section
from cfp.scoring.weekly import RANKED, cumulative_from_counts, score_weekly, top25_scores
from cfp.snapshot.data import load_title_games
from cfp.store.lake import Lake
from cfp.store.types import Mode

SCHEMA: Final = 1
LABELS: Final = {"baseline1": "AP as issued", "baseline2": "prior CFP update"}
NOTES: Final = (
    "Lower is better. A perfect forecast scores 0.",
    "The fitted model was not issued this season, so the comparison is between the two baselines.",
    "The calibrated column is scored on P(top 25) alone, beside the raw column on the same teams. It is "
    "not part of the weekly rank score, which needs every cutoff from 1 to 25.",
    "A replay edition is scored for reference and is never counted as a prospective forecast.",
    "One release is one observation. No model is promoted or dropped on one scorecard.",
    "Field and bye probabilities are scored once, on the Selection Day scorecard, for every edition of the "
    "season that carried a field forecast.",
)


class ScoreRefused(ValueError):
    """The release cannot be scored from what is in the store."""


@dataclass(frozen=True)
class Scorecard:
    scorecard_id: str
    doc: dict[str, Any]
    body: bytes
    sha256: str


def _certain(order: Sequence[str]) -> dict[str, list[float]]:
    return {
        team: [1.0 if k >= place else 0.0 for k in range(1, RANKED + 1)]
        for place, team in enumerate(order[:RANKED], start=1)
    }


def _field(doc: Mapping[str, Any]) -> dict[str, Any] | None:
    section = doc.get("final_field")
    if not section:
        return None
    out: dict[str, Any] = {"kind": section.get("kind"), "outcome": None}
    out["outcome_note"] = "Field and bye probabilities are scored after Selection Day."
    try:
        rules = load_rules(doc["season"])
        hosts = sum(len(seeds) for _, seeds in rules.hosts)
        runs = check_section(section, field=rules.field_size, byes=len(rules.byes), hosts=hosts)
        out["integrity"] = {"passed": True, "runs": runs}
    except (IntegrityError, RulesError, KeyError) as error:
        out["integrity"] = {"passed": False, "error": str(error)}
    return out


def score_edition(
    doc: Mapping[str, Any], actual: Sequence[str], *, prior: Sequence[str] | None
) -> dict[str, Any]:
    """Both baselines in one edition against the committee's list."""
    noise = doc.get("rank_noise")
    first = doc["forecasts"]["baseline1"]
    rows = doc["forecasts"]["baseline2"]["rows"]
    orders = {"baseline1": list(first["order"]), "baseline2": [r["team_id"] for r in rows]}
    if set(orders["baseline1"]) != set(orders["baseline2"]):
        raise ScoreRefused("the two baselines in the edition do not cover the same teams")
    if noise:
        paths = noise["paths"]
        forecasts = {
            "baseline1": {t: cumulative_from_counts(c, paths) for t, c in first["rank_counts"].items()},
            "baseline2": {r["team_id"]: cumulative_from_counts(r["rank_counts"], paths) for r in rows},
        }
        how = "sampled ranks"
    else:
        forecasts = {name: _certain(order) for name, order in orders.items()}
        how = "point order, scored as certain"
    models: dict[str, Any] = {}
    for name, order in orders.items():
        try:
            card = score_weekly(name, order, forecasts[name], actual, order, prior=prior)
        except ValueError as error:
            raise ScoreRefused(str(error)) from error
        models[name] = card | {"label": LABELS[name], "forecast": how}
    column = None
    calibrated = {
        r["team_id"]: r["calibrated"]["p_top25"] for r in rows if "p_top25" in (r.get("calibrated") or {})
    }
    if calibrated:
        try:
            column = top25_scores({r["team_id"]: r["p_top25"] for r in rows}, calibrated, actual=actual)
        except ValueError as error:
            raise ScoreRefused(f"P(top 25) column: {error}") from error
    return {"models": models, "top25_column": column, "field": _field(doc)}


def not_prospective(
    doc: Mapping[str, Any], row: Mapping[str, Any], reveal: datetime, superseded: bool = False
) -> list[str]:
    """Why an edition does not count as a prospective forecast for this reveal; empty if it does.

    `row` is the store's record of the edition. Its ingest time is stamped by the store when the row is
    written, so an edition recorded after the reveal never counts, whatever its receipt says.
    """
    why = []
    if not doc.get("prospective_eligible"):
        why.append("the edition was not marked eligible when it was issued")
    if row["vintage"] != "live":
        why.append(f"its vintage is {row['vintage']}, not live")
    if not datetime.fromisoformat(doc["cutoff_utc"]) < reveal:
        why.append("its cutoff is not before the reveal")
    if not row["first_public_time"] < reveal:
        why.append("it was issued after the reveal")
    if not row["ingest_time"] < reveal:
        why.append("it was recorded in the store after the reveal")
    if superseded:
        why.append("a later revision supersedes it")
    return why


def release_rows(frame: pl.DataFrame, release_id: str) -> tuple[int, int, datetime, list[str]]:
    rows = frame.filter(pl.col("release_id") == release_id).sort("rank")
    if not rows.height:
        raise ScoreRefused(f"{release_id} is not in the store: ingest the release first")
    if rows["rank"].to_list() != list(range(1, RANKED + 1)):
        raise ScoreRefused(f"{release_id} does not hold ranks 1 to {RANKED} once each")
    head = rows.row(0, named=True)
    return head["season"], head["release_no"], head["reveal_utc"], rows["team_id"].to_list()


def actual_field(
    season: int,
    actual: Sequence[str],
    champions: Mapping[str, str],
    *,
    eligible: Mapping[str, bool],
    conference_of: Mapping[str, str],
) -> dict[str, Entry]:
    """The field on Selection Day: the season's rules applied to the committee's final list and champions.

    It is not read from an official field list. Where the rules need something the final list does not
    hold (a champion not on file, a six-conference team outside the 25), it refuses and never guesses.
    """
    rules = load_rules(season)
    wanted = list(rules.named)
    if not wanted and rules.champion_count:  # eras that take the best champions: every title must be on file
        wanted = sorted({c for c in conference_of.values() if c and c != INDEPENDENT})
    missing = [c for c in wanted if c not in champions]
    if missing:
        raise ScoreRefused(f"no champion is on file for {', '.join(missing)}")
    grouped = rules.group_of == "team" and bool(rules.group)
    if grouped and not any(conference_of.get(team) in rules.group for team in actual):
        raise ScoreRefused(
            "the committee did not rank a team from the six conferences, so that place cannot be "
            "worked out from its list: the official field is needed"
        )
    try:
        entries = select_field(
            rules,
            list(actual),
            dict(champions),
            eligible=eligible,
            conference_of=conference_of if grouped else None,
        )
    except RulesError as error:
        raise ScoreRefused(f"the final list cannot be run through the rules: {error}") from error
    return {e.team_id: e for e in entries if e.qualifier}


def _automatic(route: str | None) -> bool:
    return bool(route) and str(route).startswith("auto")


def score_field_section(
    doc: Mapping[str, Any],
    entries: Mapping[str, Any],
    played: Mapping[str, frozenset[str]] | None = None,
) -> dict[str, Any]:
    """Brier and log loss for one edition's field and bye probabilities against the actual field (VT-12).

    Every team the edition listed is scored; a team with no paths was published half a path from zero and is
    scored at that. The bubble is the one the edition fixed at issue.

    An edition issued as scenarios is scored on the one scenario whose pairings were the ones played
    (`played`: conference -> the two teams), as conditional on pairings. The others are listed, not scored.
    Nothing is merged or averaged, and such an edition is out of the market contest.
    """
    section = doc["final_field"]
    paths = int(section["paths"])
    population = [str(row["team_id"]) for row in doc["forecasts"]["baseline2"]["rows"]]
    unknown = sorted(set(entries) - set(population))
    if unknown:
        raise ScoreRefused(f"the field holds teams the edition never listed: {', '.join(unknown)}")
    pairwise = (doc.get("rank_noise") or {}).get("pairwise") or {}
    cohort = [str(team) for team in pairwise.get("teams") or []]
    rules = load_rules(doc["season"])
    era = f"{rules.field_size}-team, {rules.seeding} seeding"
    lead = f"r{int(doc['target_release_no']):02d}-{doc['issue']}"
    runs = [section["forecast"]] if section.get("forecast") else list(section.get("scenarios") or [])
    if not runs:
        raise ScoreRefused("the field section holds no forecast and no scenarios")
    conditional = not section.get("forecast")
    not_scored: list[str] = []
    if conditional:
        if any(not isinstance(run.get("scenario_pairings"), dict) for run in runs):
            raise ScoreRefused("the edition's scenarios do not record their pairings, so none can be matched")
        wanted = sorted({league for run in runs for league in run["scenario_pairings"]})
        missing = [league for league in wanted if played is None or league not in played]
        if missing or played is None:
            raise ScoreRefused(
                f"the actual pairings are not on file for: {', '.join(missing) or 'any league'}"
            )
        matches = [
            run
            for run in runs
            if all(frozenset(pair) == played[league] for league, pair in run["scenario_pairings"].items())
        ]
        not_scored = [str(run.get("scenario")) for run in runs if run not in matches]
        runs = matches
    scored = []
    for run in runs:
        said = {str(team["team_id"]): team for team in run["teams"]}
        rows = []
        for team in population:
            mine = said.get(team, {})
            field = int(mine.get("field_paths", 0))
            auto = sum(n for route, n in (mine.get("route_paths") or {}).items() if _automatic(route))
            entry = entries.get(team)
            route = None if entry is None else ("automatic" if _automatic(entry.route) else "at_large")
            rows.append(
                FieldRow(
                    int(doc["season"]),
                    lead,
                    era,
                    team,
                    published_probability(field, paths),
                    published_probability(int(mine.get("bye_paths", 0)), paths),
                    entry is not None,
                    bool(entry and entry.bye),
                    published_probability(auto, paths),
                    published_probability(field - auto, paths),
                    route,
                    team in cohort,
                )
            )
        scored.append({"scenario": run.get("scenario"), "scores": field_scores(rows)})
    out: dict[str, Any] = {
        "lead": lead,
        "era": era,
        "teams": len(population),
        "bubble": cohort,
        "runs": scored,
        "basis": "conditional on pairings" if conditional else "unconditional",
        "market_contest": "excluded: conditional on pairings" if conditional else "eligible",
    }
    if conditional:
        out["not_scored"] = not_scored
        out["note"] = (
            "Scored: the one scenario whose pairings were played, conditional on pairings and apart from "
            "unconditional issues. Scenarios are never combined, merged or averaged."
            if scored
            else "not scored: pairing not listed. No listed scenario matches the pairings that were played; "
            "this is logged as a miss."
        )
        if not scored:
            out["miss"] = True
    return out


def actual_pairings(lake: Lake, data: Path, season: int, now: datetime) -> dict[str, frozenset[str]]:
    """Conference -> the two teams of its title game, from the title file once every pairing is on it."""
    ids = dict(lake.as_of("teams", now, "replay").frame.select("name", "team_id").iter_rows())
    out: dict[str, frozenset[str]] = {}
    for title in load_title_games(data / "title_games.csv"):
        if title.season == season and title.team_a in ids and title.team_b in ids:
            out[conference_key(title.conference)] = frozenset({ids[title.team_a], ids[title.team_b]})
    return out


def _read_edition(root: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    path = root / row["edition_id"] / "edition.json"
    if not path.is_file():
        raise ScoreRefused(f"{row['edition_id']} is recorded but its file is missing")
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != row["sha256"]:
        raise ScoreRefused(f"{row['edition_id']}: the file's hash is not the hash recorded at issue")
    return json.loads(body)  # type: ignore[no-any-return]


FIELD_SOURCE: Final = (
    "the season's rules applied to the committee's final list and the title-game winners on file; "
    "not read from an official field list"
)


def _integrity(doc: Mapping[str, Any]) -> dict[str, Any]:
    try:
        rules = load_rules(doc["season"])
        hosts = sum(len(seeds) for _, seeds in rules.hosts)
        runs = check_section(doc["final_field"], field=rules.field_size, byes=len(rules.byes), hosts=hosts)
        return {"passed": True, "runs": runs}
    except (IntegrityError, RulesError, KeyError, TypeError) as error:
        return {"passed": False, "error": str(error)}


def _field_card(
    name: str,
    doc: Mapping[str, Any],
    row: Mapping[str, Any],
    releases: pl.DataFrame,
    entries: Mapping[str, Entry],
    superseded: bool,
    played: Mapping[str, frozenset[str]] | None = None,
) -> dict[str, Any]:
    """One edition's field forecast, scored. Its prospective status is judged against the store's release."""
    card: dict[str, Any] = {"edition_id": name, "sha256": row["sha256"]}
    try:
        season, number = int(doc["season"]), int(doc["target_release_no"])
        target = releases.filter((pl.col("season") == season) & (pl.col("release_no") == number))
        if season != row["season"] or not target.height:
            why = ["the release it was issued for is not in the store for its season"]
        else:
            reveal = target["reveal_utc"][0]
            why = not_prospective(doc, row, reveal, superseded=superseded)
            if datetime.fromisoformat(doc["reveal_utc"]) != reveal:
                why.append("its own reveal time differs from the store's release")
        card |= {
            "kind": doc["final_field"].get("kind"),
            "prospective": not why,
            "not_prospective_because": why,
        }
        card["integrity"] = _integrity(doc)
        card |= score_field_section(doc, entries, played)
    except (ScoreRefused, ValueError, KeyError, TypeError) as error:
        card.setdefault("prospective", False)
        card |= {"runs": None, "error": f"{type(error).__name__}: {error}"}
    return card


def _field_outcome(
    lake: Lake,
    data: Path,
    season: int,
    reveal: datetime,
    actual: Sequence[str],
    *,
    now: datetime,
    mode: Mode,
    root: Path,
    releases: pl.DataFrame,
) -> dict[str, Any]:
    """Every field forecast issued this season, scored on Selection Day. A reason, if it cannot be.

    Nothing here stops the scorecard: an edition that cannot be read is listed, and a field that cannot be
    worked out is reported unscored with the reason.
    """
    held = lake.as_of("editions", now, mode, season=season).frame.filter(pl.col("product") == PRODUCT)
    docs: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    unreadable: dict[str, str] = {}
    for row in held.sort("edition_id").iter_rows(named=True):
        try:
            docs[row["edition_id"]] = (_read_edition(root, row), row)
        except (ScoreRefused, ValueError) as error:
            unreadable[row["edition_id"]] = str(error)
    carrying = {name: pair for name, pair in docs.items() if pair[0].get("final_field")}
    if not carrying:
        reason = "no edition this season carries a field forecast"
        return {"scored": False, "reason": reason, "unreadable": unreadable}
    try:
        found, _, problems = past_champions(lake, data, [season], now)
        if problems:
            raise ScoreRefused("champions are not all on file: " + "; ".join(problems))
        champions = dict(found[season])
        day = reveal.date()
        membership = lake.as_of("membership", now, mode).frame
        flags = fbs_field(membership, lake.as_of("eligibility", now, mode).frame, season, day)
        eligible = {str(team): bool(flag) for team, flag in flags.iter_rows()}
        current = membership.filter(
            (pl.col("valid_from") <= day) & (pl.col("valid_to").is_null() | (pl.col("valid_to") >= day))
        )
        members = {
            str(team): str(league)
            for team, league in current.select("team_id", "conference_id").drop_nulls().iter_rows()
            if team in eligible  # FBS teams only
        }
        entries = actual_field(season, actual, champions, eligible=eligible, conference_of=members)
        try:  # needed only by an edition issued as scenarios, which is refused on its own without it
            played: dict[str, frozenset[str]] | None = actual_pairings(lake, data, season, now)
        except Exception:
            played = None
    except (ScoreRefused, OSError, RuntimeError, ValueError, TypeError, KeyError) as error:
        reason = str(error) if isinstance(error, ScoreRefused) else f"{type(error).__name__}: {error}"
        return {"scored": False, "reason": reason, "unreadable": unreadable}
    replaced = {doc["supersedes"] for doc, _ in docs.values() if doc.get("supersedes")}
    editions = [
        _field_card(name, doc, row, releases, entries, name in replaced, played)
        for name, (doc, row) in carrying.items()
    ]
    ordered = sorted(entries.values(), key=lambda e: e.seed or 0)
    return {
        "scored": True,
        "source": FIELD_SOURCE,
        "champions": dict(sorted(champions.items())),
        "field": [{"team_id": e.team_id, "seed": e.seed, "bye": e.bye, "route": e.route} for e in ordered],
        "byes": [e.team_id for e in ordered if e.bye],
        "editions": editions,
        "misses": [card["edition_id"] for card in editions if card.get("miss")],
        "unreadable": unreadable,
    }


def build_scorecard(
    lake: Lake,
    release_id: str,
    *,
    now: datetime,
    mode: Mode = "live",
    revision: int = 1,
    code_hash: str,
    editions_root: Path | None = None,
    data: Path | None = None,
) -> Scorecard:
    """Score every recorded edition issued for `release_id`. Reads only; writes nothing."""
    if revision < 1:
        raise ScoreRefused("a revision is 1 or more")
    releases = lake.as_of("committee_releases", now, mode).frame
    season, number, reveal, actual = release_rows(releases, release_id)
    if now < reveal:
        raise ScoreRefused(f"{release_id} is revealed at {reveal.isoformat()}: nothing is scored before then")
    prior: list[str] | None = None
    prior_id: str | None = None
    if number > 1:
        earlier = releases.filter((pl.col("season") == season) & (pl.col("release_no") == number - 1))
        if not earlier.height:
            raise ScoreRefused(f"release {number - 1} of {season} is not in the store: ingest it first")
        prior_id = earlier["release_id"][0]
        _, _, _, prior = release_rows(releases, prior_id)
    names = dict(lake.as_of("teams", now, mode).frame.select("team_id", "name").iter_rows())
    stem = f"scw-{season}-r{number:02d}-"
    held = lake.as_of("editions", now, mode, season=season).frame
    held = held.filter((pl.col("product") == PRODUCT) & pl.col("edition_id").str.starts_with(stem))
    if not held.height:
        raise ScoreRefused(f"no edition was recorded for {release_id}: there is nothing to score")
    root = editions_root or lake.root / "editions"
    docs: dict[str, dict[str, Any]] = {}
    for row in held.sort("edition_id").iter_rows(named=True):
        path = root / row["edition_id"] / "edition.json"
        if not path.is_file():
            raise ScoreRefused(f"{row['edition_id']} is recorded but its file is missing")
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != row["sha256"]:
            raise ScoreRefused(f"{row['edition_id']}: the file's hash is not the hash recorded at issue")
        docs[row["edition_id"]] = json.loads(body) | {"_row": row}
    replaced = {d["supersedes"]: name for name, d in docs.items() if d.get("supersedes")}
    editions = []
    for name, doc in docs.items():
        row = doc["_row"]
        if doc.get("target_release_no") != number or datetime.fromisoformat(doc["reveal_utc"]) != reveal:
            raise ScoreRefused(
                f"{name} was not issued for {release_id}: its own reveal or release number differs"
            )
        why = not_prospective(doc, row, reveal, superseded=name in replaced)
        editions.append(
            {
                "edition_id": name,
                "sha256": row["sha256"],
                "hash_matches_issue": True,
                "issue": doc["issue"],
                "cutoff_utc": doc["cutoff_utc"],
                "issued_utc": row["first_public_time"].isoformat(),
                "vintage": row["vintage"],
                "code_hash": doc.get("code_hash"),
                "prospective": not why,
                "not_prospective_because": why,
                "superseded_by": replaced.get(name),
                "headline_forecast": doc.get("headline_forecast"),
            }
            | score_edition(doc, actual, prior=prior)
        )
    field_outcome = None
    if data is not None:
        try:
            scheduled = sum(1 for day in load_schedule(data / "cfp_reveals.csv") if day.year == season)
        except (OSError, RuntimeError, ValueError) as error:
            raise ScoreRefused(f"the reveal schedule cannot be read: {error}") from error
        if number == scheduled:  # Selection Day: the only release that settles the field
            field_outcome = _field_outcome(
                lake, data, season, reveal, actual, now=now, mode=mode, root=root, releases=releases
            )
    if field_outcome and field_outcome["scored"]:
        done = {
            card["edition_id"]: card["runs"] for card in field_outcome["editions"] if card["runs"] is not None
        }
        for card in editions:
            if card["edition_id"] in done and card["field"]:
                card["field"]["outcome"] = (
                    "scored: see field_outcome"
                    if done[card["edition_id"]]
                    else "not scored: pairing not listed (a miss); see field_outcome"
                )
    scorecard_id = f"score-{season}-r{number:02d}-e{revision}"
    document = {
        "schema": SCHEMA,
        "scorecard_id": scorecard_id,
        "product": "scorecard_weekly",
        "supersedes": f"score-{season}-r{number:02d}-e{revision - 1}" if revision > 1 else None,
        "season": season,
        "release_id": release_id,
        "release_no": number,
        "reveal_utc": reveal.isoformat(),
        "prior_release_id": prior_id,
        "mode": mode,
        "actual": actual,
        "actual_sha256": hashlib.sha256(canonical(actual)).hexdigest(),
        "names": {team: names.get(team, team) for team in actual},
        "fitted_model": "not issued",
        "prospective_editions": sum(1 for e in editions if e["prospective"]),
        "editions": editions,
        "field_outcome": field_outcome,
        "code_hash": code_hash,
        "notes": list(NOTES),
    }
    body = canonical(document)
    return Scorecard(scorecard_id, document, body, hashlib.sha256(body).hexdigest())
