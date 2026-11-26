"""Final-field forecast (FF-03, FF-04, FF-05).

Each path takes one set of simulated results, moves teams down the starting order for their losses, draws a
committee order around the result with the fitted rank noise, and applies the season's rules to get the
field, seeds, byes and hosts.

The starting order is the last committee list followed by every other team (the baseline's own order). A loss
adds a number of places: the baseline adds five for any loss, exactly as the spec defines it; a labelled model
may add different amounts for a regular week and for title week. Two models run on the same paths share the
simulated games and the same noise draws, so they differ only in the drops and the temperature.

Open points are not recomputed on each path here: neither order model reads them after the starting order is
set. `open_points_on_path` does that recomputation and is kept under test.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace

import numpy as np
import polars as pl

from cfp.forecast.simulator import Paths
from cfp.open_ranking.ledger import build_ledgers
from cfp.open_ranking.strength import INDEPENDENT, Params
from cfp.rules.engine import Entry, RulesError, SeasonRules, select_field

RANKED = 25


class FieldError(ValueError):
    """The field cannot be forecast from these inputs."""


@dataclass(frozen=True)
class Model:
    name: str
    drop_regular: float  # places added per loss in a regular week
    drop_title: float  # places added per loss in title week
    tau: float  # rank-noise temperature for the final list

    def with_tau(self, tau: float) -> Model:
        return replace(self, tau=tau)


BASELINE = Model("baseline", 5.0, 5.0, float("nan"))  # the spec's five places; its temperature is fitted


@dataclass(frozen=True)
class Setup:
    season: int
    initial: Sequence[str]  # the starting order over the whole field, best first
    conference_of: Mapping[str, str]
    eligible: Mapping[str, bool]
    regular_losses: Mapping[str, int]  # real losses since the starting order, before title week
    title_losses: Mapping[str, int]  # real losses in title week
    champions: Mapping[str, str]  # conference -> champion already decided
    title_games: Mapping[str, str]  # simulated game id -> conference whose title it decides
    title_week: frozenset[str]  # simulated game ids that fall in title week


@dataclass(frozen=True)
class Conditional:
    game_id: str
    win_paths: int
    lose_paths: int
    field_if_win: int
    field_if_lose: int


@dataclass(frozen=True)
class Result:
    model: Model
    paths: int
    paths_seed: int
    order_seed: int
    field: dict[str, int]
    bye: dict[str, int]
    host: dict[int, dict[str, int]]  # round -> team -> paths hosting it
    seeds: dict[str, dict[int, int]]
    routes: dict[str, dict[str, int]]
    conditionals: dict[str, Conditional]
    champion_paths: dict[str, dict[str, int]]  # conference -> team -> paths as champion


def _check(setup: Setup, paths: Paths, rules: SeasonRules) -> None:
    place = set(setup.initial)
    if len(place) != len(setup.initial):
        raise FieldError("a team appears twice in the starting order")
    unknown = sorted(set(paths.game_ids) & set(setup.title_games))
    for conference in rules.named:
        simulated = [g for g in unknown if setup.title_games[g] == conference]
        if conference in setup.champions and simulated:
            raise FieldError(f"the {conference} title is both decided and still to play")
        if conference not in setup.champions and not simulated:
            raise FieldError(f"no champion or title game for {conference}: its pairing is not known")
    for game_id in setup.title_games:
        if game_id not in paths.game_ids:
            raise FieldError(f"title game {game_id} was not simulated")


def _sides(paths: Paths, games: Mapping[str, tuple[str, str]]) -> tuple[list[str], list[str]]:
    return [games[g][0] for g in paths.game_ids], [games[g][1] for g in paths.game_ids]


def run(
    setup: Setup,
    paths: Paths,
    rules: SeasonRules,
    model: Model,
    *,
    seed: int,
    sides: Mapping[str, tuple[str, str]] | None = None,
    next_game: Mapping[str, str] | None = None,
    check: Callable[[Sequence[Entry]], None] | None = None,
) -> Result:
    """Field, bye, host and seed counts over the simulated paths under one order model.

    `sides` gives (home, away) for each simulated game; it defaults to the title games' pairings read from
    the game ids' teams in `paths` when the caller passes Game objects through `teams_of`. `next_game` names
    each team's next game for the conditionals; by default it is the team's only simulated game. `check`,
    if given, is handed every path's whole bracket and raises ValueError on one that is not well formed.
    """
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("a recorded seed is needed: a whole number, zero or more")
    if not model.tau > 0:
        raise FieldError(f"the {model.name} model has no fitted temperature")
    _check(setup, paths, rules)
    teams = list(setup.initial)
    index = {team: k for k, team in enumerate(teams)}
    size, n = len(teams), paths.home_won.shape[0]
    pairs = dict(sides or paths.sides)
    home_ids, away_ids = _sides(paths, pairs)

    base = np.arange(1, size + 1, dtype=np.float64)
    for team, count in setup.regular_losses.items():
        if team in index:
            base[index[team]] += model.drop_regular * count
    for team, count in setup.title_losses.items():
        if team in index:
            base[index[team]] += model.drop_title * count
    adjusted = np.tile(base, (n, 1))
    for column, game_id in enumerate(paths.game_ids):
        drop = model.drop_title if game_id in setup.title_week else model.drop_regular
        won = paths.home_won[:, column]
        for team, lost in ((home_ids[column], ~won), (away_ids[column], won)):
            if team in index:
                adjusted[lost, index[team]] += drop
    # place after the drops: by adjusted position, then starting order (a stable sort keeps that order)
    by_place = np.argsort(adjusted, axis=1, kind="stable")
    place = np.empty_like(by_place)
    rows = np.arange(n)[:, None]
    place[rows, by_place] = np.arange(size)[None, :]
    rng = np.random.default_rng(seed)
    keys = -place / model.tau + rng.gumbel(size=(n, size))
    sampled = np.argsort(-keys, axis=1, kind="stable")

    field: dict[str, int] = {}
    bye: dict[str, int] = {}
    host: dict[int, dict[str, int]] = {rnd: {} for rnd, _ in rules.hosts}
    seeds: dict[str, dict[int, int]] = {}
    routes: dict[str, dict[str, int]] = {}
    champion_paths: dict[str, dict[str, int]] = {}
    in_field = np.zeros((n, size), dtype=bool)
    title_columns = [
        (column, setup.title_games[g]) for column, g in enumerate(paths.game_ids) if g in setup.title_games
    ]
    needs_league = rules.group_of == "team" and bool(rules.group)
    for p in range(n):
        champions = dict(setup.champions)
        for column, conference in title_columns:
            champions[conference] = home_ids[column] if paths.home_won[p, column] else away_ids[column]
        for conference, team in champions.items():
            tally = champion_paths.setdefault(conference, {})
            tally[team] = tally.get(team, 0) + 1
        order = [teams[k] for k in sampled[p]]
        try:
            entries = select_field(
                rules,
                order[:RANKED],
                champions,
                eligible=setup.eligible,
                conference_of=setup.conference_of if needs_league else None,
                extra_order=order[RANKED:],
            )
        except RulesError as error:
            raise FieldError(f"path {p}: {error}") from error
        if check is not None:
            try:
                check(entries)
            except ValueError as error:
                raise FieldError(f"path {p}: {error}") from error
        entries = [entry for entry in entries if entry.qualifier]
        for entry in entries:
            team = entry.team_id
            if team not in index:
                raise FieldError(f"{team} qualified but is not in the starting order")
            in_field[p, index[team]] = True
            field[team] = field.get(team, 0) + 1
            if entry.bye:
                bye[team] = bye.get(team, 0) + 1
            if entry.host_round is not None:
                host[entry.host_round][team] = host[entry.host_round].get(team, 0) + 1
            if entry.seed is not None:
                by_seed = seeds.setdefault(team, {})
                by_seed[entry.seed] = by_seed.get(entry.seed, 0) + 1
            by_route = routes.setdefault(team, {})
            label = entry.route or "unknown"
            label = "automatic" if label.startswith("auto:") else label
            by_route[label] = by_route.get(label, 0) + 1

    conditionals: dict[str, Conditional] = {}
    playing: dict[str, list[int]] = {}
    for column in range(len(paths.game_ids)):
        for team in (home_ids[column], away_ids[column]):
            playing.setdefault(team, []).append(column)
    for team, columns in sorted(playing.items()):
        if team not in index:
            continue
        if next_game is not None and team in next_game:
            if next_game[team] not in paths.game_ids:
                raise FieldError(f"{team}'s next game {next_game[team]} was not simulated")
            chosen = paths.game_ids.index(next_game[team])
            if chosen not in columns:
                raise FieldError(f"{team} does not play in {next_game[team]}")
        elif len(columns) == 1:
            chosen = columns[0]
        else:
            continue  # more than one game left and no order given: no single next game
        won = paths.home_won[:, chosen] if home_ids[chosen] == team else ~paths.home_won[:, chosen]
        inside = in_field[:, index[team]]
        conditionals[team] = Conditional(
            paths.game_ids[chosen],
            int(won.sum()),
            int((~won).sum()),
            int((inside & won).sum()),
            int((inside & ~won).sum()),
        )
    return Result(model, n, paths.seed, seed, field, bye, host, seeds, routes, conditionals, champion_paths)


@dataclass(frozen=True)
class Today:
    entries: list[Entry]
    stand_ins: dict[str, str]  # conference -> the team standing in for a champion not yet decided


def field_today(setup: Setup, rules: SeasonRules) -> Today:
    """The field if the season ended now: the starting order with losses on the books, no noise, no games.

    A title not yet decided has no champion, so each such conference's best-placed team stands in for one.
    That is an assumption, shown as such; it is not a forecast.
    """
    lost = {
        team: setup.regular_losses.get(team, 0) + setup.title_losses.get(team, 0) for team in setup.initial
    }
    order = [
        team
        for _, _, team in sorted(
            (place + BASELINE.drop_regular * lost[team], place, team)
            for place, team in enumerate(setup.initial, start=1)
        )
    ]
    champions = dict(setup.champions)
    stand_ins: dict[str, str] = {}
    leagues = sorted({c for c in setup.conference_of.values() if c and c != INDEPENDENT})
    wanted = list(rules.named) or (leagues if rules.champion_count else [])
    for conference in wanted:
        if conference in champions:
            continue
        best = next((team for team in order if setup.conference_of.get(team) == conference), None)
        if best is not None:
            champions[conference] = best
            stand_ins[conference] = best
    needs_league = rules.group_of == "team" and bool(rules.group)
    try:
        entries = select_field(
            rules,
            order[:RANKED],
            champions,
            eligible=setup.eligible,
            conference_of=setup.conference_of if needs_league else None,
            extra_order=order[RANKED:],
        )
    except RulesError as error:
        raise FieldError(str(error)) from error
    return Today(entries, stand_ins)


def open_points_on_path(
    games: pl.DataFrame, simulated: pl.DataFrame, params: Params, t: float, season: int
) -> dict[str, int]:
    """Open points with one path's simulated games added to the snapshot's games (FF-03).

    `simulated` has the snapshot's columns. Not used by the pilot's order models; kept so the step exists
    and is tested when a model needs it.
    """
    both = pl.concat([games, simulated.select(games.columns)], how="vertical_relaxed")
    return {team: ledger.total_cp for team, ledger in build_ledgers(both, params, t, season).items()}
