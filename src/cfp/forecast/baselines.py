"""Baselines (SC-03).

Baseline 1 carries forward the latest AP order. Baseline 2 starts from the prior committee top 25, then the
other teams by AP votes, then open points, then the published draw; each loss since that release adds five to
a team's starting position; teams are sorted by adjusted position, then by starting order.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import polars as pl

LOSS_STEP = 5
FINAL_LAG = timedelta(hours=4, minutes=30)  # kickoff to final; the same lag dates results in the store


@dataclass(frozen=True)
class Placed:
    team_id: str
    position: int  # final place, 1 first
    initial: int  # starting position
    losses: int  # since the anchor
    adjusted: int  # initial + 5 per loss


def ap_order(ap: pl.DataFrame) -> list[tuple[int, str, int]]:
    """(week, team, points) for the latest AP poll in `ap`: ranked teams in rank order, then others by votes.

    Teams with equal votes outside the ranked 25 are returned in team-id order; callers break those ties.
    """
    if ap.height == 0:
        raise ValueError("no AP poll is available")
    latest = ap.filter(pl.col("week") == ap["week"].max())
    ranked = latest.filter(pl.col("rank").is_not_null()).sort(["rank", "team_id"])
    others = latest.filter(pl.col("rank").is_null()).sort(["points", "team_id"], descending=[True, False])
    rows = [*ranked.iter_rows(named=True), *others.iter_rows(named=True)]
    return [(int(row["week"]), row["team_id"], int(row["points"] or 0)) for row in rows]


def _standing(ap: pl.DataFrame) -> tuple[dict[str, int], dict[str, int]]:
    """(AP rank by team, AP points by team) for the latest poll. Teams sharing a rank share the number."""
    if ap.height == 0:
        raise ValueError("no AP poll is available")
    latest = ap.filter(pl.col("week") == ap["week"].max())
    ranks = {r["team_id"]: int(r["rank"]) for r in latest.iter_rows(named=True) if r["rank"] is not None}
    points = {r["team_id"]: int(r["points"] or 0) for r in latest.iter_rows(named=True)}
    return ranks, points


def baseline1(teams: Sequence[str], ap: pl.DataFrame, draw: Mapping[str, int]) -> list[str]:
    """The latest AP order over the whole field: ranked teams, then others by votes, then the draw."""
    return initial_order(teams, None, ap, None, draw)


def initial_order(
    teams: Sequence[str],
    prior_cfp: Sequence[str] | None,
    ap: pl.DataFrame,
    open_points: Mapping[str, int] | None,
    draw: Mapping[str, int],
) -> list[str]:
    """Baseline 2's starting order over `teams`.

    The prior committee top 25 in order (none on the opening week, when AP is the anchor), then every other
    team by AP standing: ranked teams in rank order, then by votes. Equal ranks or votes fall to open points
    when given (a team without open points sorts after those with), then to the draw. Votes for a team outside
    the field (AP voters sometimes name an FCS team) are ignored.
    """
    field = set(teams)
    head = list(prior_cfp or [])
    ranks, votes = _standing(ap)
    for team in head:
        if team not in field:
            raise ValueError(f"{team} is in the committee's 25 but is not in the field")
    missing = sorted(field - set(draw))
    if missing:
        raise ValueError(f"the draw does not cover {missing[0]}")
    placed = set(head)
    points = open_points or {}
    unranked = max(ranks.values(), default=0) + 1

    def key(team: str) -> tuple[int, int, int, int, int]:
        return (
            ranks.get(team, unranked),
            -votes.get(team, 0),
            0 if team in points else 1,
            -points.get(team, 0),
            draw[team],
        )

    return head + sorted((team for team in field if team not in placed), key=key)


def losses_since(
    games: pl.DataFrame,
    teams: Sequence[str],
    since: datetime | None = None,
    since_week: int | None = None,
) -> dict[str, int]:
    """Losses by `teams` in final games the anchor could not have counted.

    With a committee release as the anchor, those are games not yet final at its reveal: kickoff later than
    the reveal minus FINAL_LAG (4.5 hours, the same lag used to date results). With an AP poll as the anchor
    they are games in weeks from `since_week`. Games between two teams outside `teams` are ignored.
    """
    field = set(teams)
    finals = games.filter(
        (pl.col("status") == "final") & (pl.col("home_id").is_in(teams) | pl.col("away_id").is_in(teams))
    )
    if since is not None:
        if finals["start_utc"].null_count():
            raise ValueError("a final game has no kickoff time")
        finals = finals.filter(pl.col("start_utc") > since - FINAL_LAG)
    if since_week is not None:
        if finals["week"].null_count():
            raise ValueError("a final game has no week")
        finals = finals.filter(pl.col("week") >= since_week)
    out: dict[str, int] = {}
    for row in finals.iter_rows(named=True):
        home, away = row["home_pts"], row["away_pts"]
        if home is None or away is None:
            raise ValueError(f"{row['game_id']}: final with no score")
        if home == away:
            raise ValueError(f"{row['game_id']}: a {home}-{away} tie is not a result")
        loser = row["away_id"] if home > away else row["home_id"]
        if loser in field:
            out[loser] = out.get(loser, 0) + 1
    return out


def baseline2(initial: Sequence[str], losses: Mapping[str, int]) -> list[Placed]:
    """Add five places per loss, then sort by adjusted position and starting order."""
    scored = [
        (place + LOSS_STEP * losses.get(team, 0), place, team) for place, team in enumerate(initial, start=1)
    ]
    return [
        Placed(team, position, place, losses.get(team, 0), adjusted)
        for position, (adjusted, place, team) in enumerate(sorted(scored), start=1)
    ]
