"""The field forecast section of a forecast issue (FF-01 to FF-05).

Built from frames already read as of the issue cutoff: the season's remaining games are priced and simulated,
each path's results move teams down Baseline 2's starting order five places a loss, an order is drawn around
that with the fitted rank noise, and the season's rules give the field. Only the baseline is published; it
drops a title-game loser five places like any other loser, and the section says so.

A pairing that is not known becomes scenarios when they are on file (each run on its own, never weighted);
otherwise the section is refused with the reason and the weekly forecast goes out without it.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

import polars as pl

from cfp.common.hashing import sha256_hex
from cfp.forecast.baselines import LOSS_STEP
from cfp.forecast.cutoffs import ET
from cfp.forecast.final_field import BASELINE, FieldError, Setup, field_today, run
from cfp.forecast.noise_params import Noise, NoiseError
from cfp.forecast.pairings import (
    MAX_SCENARIOS,
    OPEN_GROUP_LIMIT,
    PAIRINGS_LEAD,
    Pairing,
    Pairings,
)
from cfp.forecast.rank_noise import published_probability
from cfp.forecast.sim_inputs import fit_history, slate
from cfp.forecast.simulator import Game, simulate
from cfp.rules.engine import RulesError, load_rules
from cfp.scoring.integrity import check_path

Estimate = Callable[[str, str, bool], float | None]


def _seed(label: str) -> int:
    return int(sha256_hex(label.encode())[:12], 16)


def build_field(
    *,
    season: int,
    issue: str,
    cutoff: datetime,
    target: int,
    total: int,
    boundary: datetime,
    final_reveal: datetime,
    rows: Sequence[Mapping[str, Any]],
    names: Mapping[str, str],
    conference_of: Mapping[str, str],
    games: pl.DataFrame,
    lines: pl.DataFrame,
    noise: Noise,
    pairings: Pairings,
    estimate: Estimate | None,
    stem: str,
    paths: int,
    results_through: datetime | None = None,
) -> dict[str, Any]:
    """The `final_field` section. `rows` are Baseline 2's rows; `games` and `lines` cover every season.

    `target` is the release this issue forecasts and `total` the season's number of releases; `boundary` is
    the reveal of the last weekly release, after which a game belongs to title week.
    """
    if target == total:
        kind = "final"
    elif target == total - 1:
        kind = "final_two_back"
    else:
        raise FieldError("the field forecast is issued from the last two releases of the season only")
    try:
        tau = noise.tau("baseline2", issue, kind)
        rules = load_rules(season)
    except (NoiseError, RulesError) as error:
        raise FieldError(str(error)) from error
    fitted = fit_history(games, lines, season=season)
    seasonal = games.filter(pl.col("season") == season)
    ordered = sorted(rows, key=lambda row: int(row["initial"]))
    initial = [str(row["team_id"]) for row in ordered]
    known = {str(row["team_id"]): int(row["losses"]) for row in ordered if row["losses"]}
    eligible = {str(row["team_id"]): bool(row["cfp_eligible"]) for row in ordered}
    if seasonal["start_utc"].null_count():
        raise FieldError("a game of the season has no kickoff time")
    # a game that kicks off after the final list is revealed cannot move it (Army-Navy, the bowls)
    before_reveal = seasonal.filter(pl.col("start_utc") < final_reveal)
    made = slate(
        before_reveal,
        lines.filter(pl.col("first_public_time") <= cutoff),
        cutoff,
        season,
        fitted.curve,
        estimate=estimate,
    )
    start = dict(seasonal.select("game_id", "start_utc").iter_rows())

    def one(
        decided: Mapping[str, Pairing], label: str | None, chosen: Mapping[str, Pairing] | None = None
    ) -> dict[str, Any]:
        champions: dict[str, str] = {}
        title_games: dict[str, str] = {}
        extra: list[Game] = []
        for conference, pair in sorted(decided.items()):
            between = seasonal.filter(
                (
                    ((pl.col("home_id") == pair.team_a) & (pl.col("away_id") == pair.team_b))
                    | ((pl.col("home_id") == pair.team_b) & (pl.col("away_id") == pair.team_a))
                )
                & (pl.col("start_utc").dt.date() >= pair.day - timedelta(days=1))
                & (pl.col("start_utc").dt.date() <= pair.day + timedelta(days=1))
            )
            if between.height > 1:
                raise FieldError(f"the {conference} pairing matches {between.height} games")
            if between.height == 1:
                row = between.row(0, named=True)
                sides = {conference_of.get(row["home_id"]), conference_of.get(row["away_id"])}
                if sides != {conference}:
                    raise FieldError(f"the {conference} pairing names a team from another conference")
                if row["status"] == "final":
                    if (
                        row["home_pts"] is None
                        or row["away_pts"] is None
                        or row["home_pts"] == row["away_pts"]
                    ):
                        raise FieldError(f"the {conference} title game is final with no winner")
                    champions[conference] = (
                        row["home_id"] if row["home_pts"] > row["away_pts"] else row["away_id"]
                    )
                else:
                    title_games[row["game_id"]] = conference
                continue
            if {conference_of.get(pair.team_a), conference_of.get(pair.team_b)} != {conference}:
                raise FieldError(f"the {conference} pairing names a team from another conference")
            p = estimate(pair.team_a, pair.team_b, True) if estimate is not None else None
            if p is None:
                raise FieldError(
                    f"the {conference} title game is not on the schedule and has no strength estimate"
                )
            game_id = f"title-{season}-{conference}"
            extra.append(Game(game_id, pair.team_a, pair.team_b, p))
            title_games[game_id] = conference
        slate_games = [*made.games, *extra]
        title_week = frozenset(
            g.game_id
            for g in slate_games
            if g.game_id in title_games or start.get(g.game_id, boundary) >= boundary
        )
        setup = Setup(
            season,
            initial,
            conference_of,
            eligible,
            known if kind == "final_two_back" else {},
            known if kind == "final" else {},
            champions,
            title_games,
            title_week,
        )
        # One seed for every scenario. The draws line up game for game only when the scenarios have the
        # same number of teams and games, as title-week pairings do; otherwise they are independent runs.
        tag = stem
        simulated = simulate(slate_games, paths, a=fitted.dependence.a, seed=_seed(f"field-games|{tag}"))
        upcoming: dict[str, tuple[datetime, str]] = {}
        for (
            g
        ) in slate_games:  # each team's next game: its earliest; a title game not yet scheduled comes last
            when = (start.get(g.game_id) or datetime.max.replace(tzinfo=cutoff.tzinfo), g.game_id)
            for team in (g.home_id, g.away_id):
                if team not in upcoming or when < upcoming[team]:
                    upcoming[team] = when
        result = run(
            setup,
            simulated,
            rules,
            BASELINE.with_tau(tau),
            seed=_seed(f"field-order|{tag}"),
            next_game={team: game_id for team, (_, game_id) in upcoming.items()},
            check=lambda entries: check_path(
                entries,
                field=rules.field_size,
                byes=len(rules.byes),
                hosts=sum(len(seeds) for _, seeds in rules.hosts),
            ),
        )
        today = field_today(setup, rules)
        shown = [t for t in initial if result.field.get(t) or t in result.conditionals]
        teams = []
        for team in shown:
            cond = result.conditionals.get(team)
            count = result.field.get(team, 0)
            teams.append(
                {
                    "team_id": team,
                    "name": names[team],
                    "initial": initial.index(team) + 1,
                    "field_paths": count,
                    "p_field": published_probability(count, paths),
                    "bye_paths": result.bye.get(team, 0),
                    "host_paths": {str(rnd): by.get(team, 0) for rnd, by in sorted(result.host.items())},
                    "seed_paths": {str(k): v for k, v in sorted(result.seeds.get(team, {}).items())},
                    "route_paths": dict(sorted(result.routes.get(team, {}).items())),
                    "next_game": (
                        {
                            "game_id": cond.game_id,
                            "win_paths": cond.win_paths,
                            "lose_paths": cond.lose_paths,
                            "field_if_win": cond.field_if_win,
                            "field_if_lose": cond.field_if_lose,
                        }
                        if cond is not None
                        else None
                    ),
                }
            )
        extras = {g.game_id: "strength" for g in extra}
        return {
            "scenario": label,
            "scenario_pairings": {c: sorted([p.team_a, p.team_b]) for c, p in sorted((chosen or {}).items())},
            "seeds": {"games": simulated.seed, "order": result.order_seed},
            "games": [
                {
                    "game_id": g.game_id,
                    "home_id": g.home_id,
                    "away_id": g.away_id,
                    "p_home": g.p_home,
                    "source": made.sources.get(g.game_id) or extras[g.game_id],
                    "books": made.books.get(g.game_id, 0),
                    "title_for": title_games.get(g.game_id),
                    "title_week": g.game_id in title_week,
                    "in_progress": g.game_id in made.in_progress,
                }
                for g in sorted(slate_games, key=lambda g: g.game_id)
            ],
            "champions_decided": dict(sorted(champions.items())),
            "teams": teams,
            "today": {
                "assumption": "each undecided league's best-placed team stands in for its champion",
                "stand_ins": dict(sorted(today.stand_ins.items())),
                "field": [
                    {"seed": e.seed, "team_id": e.team_id, "name": names[e.team_id], "route": e.route}
                    for e in sorted((e for e in today.entries if e.qualifier), key=lambda e: e.seed or 0)
                ],
            },
        }

    choices = [
        [(conference, pair) for pair in options] for conference, options in sorted(pairings.scenarios.items())
    ]
    combos = list(itertools.product(*choices)) if choices else [()]
    if len(combos) > MAX_SCENARIOS:
        raise FieldError(f"{len(combos)} pairing scenarios are too many to publish; limit {MAX_SCENARIOS}")
    runs = []
    for combo in combos:
        decided = dict(pairings.decided) | {conference: pair for conference, pair in combo}
        label = "; ".join(f"{conference}: {pair.scenario}" for conference, pair in combo) or None
        runs.append(one(decided, label, dict(combo)))
    # An open league's teams play no title game on any path, so neither finalist takes the loss. If such a
    # league's teams take the place for the best of the other conferences often, it is treated as named.
    for conference in pairings.open:
        mine = {team for team, league in conference_of.items() if league == conference}
        # an open league has no champion on any path, so its teams' only automatic place is the shared one
        share = max(
            sum(t["route_paths"].get("automatic", 0) for t in found["teams"] if t["team_id"] in mine) / paths
            for found in runs
        )
        if share > OPEN_GROUP_LIMIT:
            raise FieldError(
                f"the {conference} pairing is open and its teams take the other conferences' place in "
                f"{share:.1%} of paths (limit {OPEN_GROUP_LIMIT:.0%}); it needs a pairing or scenarios"
            )
    conditional = len(runs) > 1 or bool(runs[0]["scenario"])
    # How often each of the other conferences takes the shared place, in each run on its own.
    if rules.group_of == "team":
        for found in runs:
            counts = dict.fromkeys(sorted(rules.group), 0)
            for row in found["teams"]:
                league = conference_of.get(row["team_id"])
                if league in counts:  # none of these is named, so their only automatic place is this one
                    counts[league] += row["route_paths"].get("automatic", 0)
            found["other_conferences_place"] = {
                league: published_probability(count, paths) for league, count in counts.items()
            }

    def clock(moment: datetime) -> str:
        local = moment.astimezone(ET)
        return f"{local:%H:%M} ET {local:%A}"

    as_known = clock(cutoff - PAIRINGS_LEAD)
    through = clock(results_through) if results_through is not None else "the cutoff"
    if issue != "sun0200":  # only the Sunday issue has a ruled entry time
        as_known = "the start of the issuing run, up to two hours before the cutoff"
    disclosure = f"Title pairings as known at {as_known}; results through {through}."
    if conditional:
        after = as_known if issue == "sun0200" else "that"
        disclosure += f" A result ingested after {after} may have ruled a listed scenario out."
    secondary = sorted(c for c, p in pairings.decided.items() if p.basis == "cfbd_schedule")
    if secondary:
        disclosure += (
            " Taken from the schedule in the store at the cutoff, not from a conference: "
            + ", ".join(secondary)
            + "."
        )
    notes = [
        disclosure,
        f"Baseline only: every loss, including a title-game loss, costs {LOSS_STEP} places. "
        "The fitted title-week drop the plan specified (shrunk toward the weekly value) scored worse than "
        "the baseline on 2017-2025 and was not promoted. An unshrunk version scored better, but it was "
        "looked at only afterwards and rests on three team-seasons, so it is not published.",
        "On 2017-2025 the baseline's small field probabilities were too small: forecasts near 0.09 came "
        "in near 0.19 (5 of 27).",
        "The order among teams outside the committee's 25 is never observed, so the noise applied to the "
        "six-conference place is not validated.",
        "The six-conference place carries the widest uncertainty: its teams are mostly outside the "
        "committee's 25, where the starting order rests on AP votes and open points.",
        "Open points are computed at the cutoff for the starting order and are not recomputed on each path.",
        "A count of no paths or every path is published half a path short of 0 or 1.",
        "The bracket checked on every path: each team once, each seed once, the era's byes and home games.",
    ]
    if made.in_progress:
        notes.append(
            "A game in progress at the cutoff is treated as unplayed and priced from its last quote "
            "before kickoff."
        )
    if pairings.open:
        notes.append(
            "No pairing is known for: "
            + ", ".join(pairings.open)
            + ". Their teams take no title-game result."
        )
    notes.extend(f"Cross-check: {warning}." for warning in pairings.warnings)
    if conditional:
        notes.append(
            "A pairing was not final at the cutoff: each scenario is run separately. None is weighted, "
            "merged or averaged, and there is no headline scenario. The scenario that matches the actual "
            "pairings is the one scored, as conditional on pairings, apart from unconditional issues."
        )
    return {
        "model": "baseline",
        "kind": kind,
        "tau": tau,
        "paths": paths,
        "dependence_a": fitted.dependence.a,
        "spread_scale": fitted.curve.scale,
        "history_seasons": list(fitted.seasons),
        "rules_source": rules.source,
        "pairings_sha256": pairings.sha256,
        "pairings": [
            {
                "conference": p.conference,
                "team_a": p.team_a,
                "team_b": p.team_b,
                "basis": p.basis,
                "source_url": p.source_url,
                "first_public_utc": p.first_public.isoformat() if p.first_public else None,
            }
            for _, p in sorted(pairings.decided.items())
        ],
        "open_pairings": list(pairings.open),
        "ignored_pairing_rows": list(pairings.ignored),
        "pairing_warnings": list(pairings.warnings),
        "scenario_basis": {
            c: {"statement": options[0].listed_by, "source_urls": options[0].source_url.split()}
            for c, options in sorted(pairings.scenarios.items())
        },
        "pairings_disclosure": disclosure,
        "conditional_on_pairings": conditional,
        "market_contest": "excluded: the field forecast is conditional on pairings"
        if conditional
        else "eligible",
        "invalid_quotes": made.invalid_quotes,
        "scenarios": runs if conditional else None,
        "forecast": None if conditional else runs[0],
        "notes": notes,
    }
