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
from typing import Any, Final

import polars as pl

from cfp.common.hashing import sha256_hex
from cfp.forecast.baselines import LOSS_STEP
from cfp.forecast.final_field import BASELINE, FieldError, Setup, field_today, run
from cfp.forecast.noise_params import Noise, NoiseError
from cfp.forecast.pairings import Pairing, Pairings
from cfp.forecast.rank_noise import published_probability
from cfp.forecast.sim_inputs import fit_history, slate
from cfp.forecast.simulator import Game, simulate
from cfp.rules.engine import RulesError, load_rules

MAX_SCENARIOS: Final = 8
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

    def one(decided: Mapping[str, Pairing], label: str | None) -> dict[str, Any]:
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
        runs.append(one(decided, label))
    notes = [
        f"Baseline only: every loss, including a title-game loss, costs {LOSS_STEP} places. "
        "A fitted title-week drop was tested on 2017-2025 and did not pass the promotion rule.",
        "The six-conference place carries the widest uncertainty: its teams are mostly outside the "
        "committee's 25, where the starting order rests on AP votes and open points.",
        "Open points are computed at the cutoff for the starting order and are not recomputed on each path.",
        "A count of no paths or every path is published half a path short of 0 or 1.",
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
    if len(runs) > 1 or runs[0]["scenario"]:
        notes.append(
            "A pairing was not official at the cutoff: each scenario is run separately and none is weighted."
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
        "invalid_quotes": made.invalid_quotes,
        "scenarios": runs if (len(runs) > 1 or runs[0]["scenario"]) else None,
        "forecast": runs[0] if len(runs) == 1 and not runs[0]["scenario"] else None,
        "notes": notes,
    }
