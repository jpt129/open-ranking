"""Committee observations (SC-01): one release and the complete list of that season's FBS teams.

The target is 25 ordered teams; every other FBS team is known only to be below 25 and stays in the
denominator. Bid eligibility is a separate flag and never removes a team.
"""

from __future__ import annotations

from datetime import date, datetime

import polars as pl

from cfp.common.timeutil import require_utc

RANKED = 25


class ObservationError(ValueError):
    """A release cannot be turned into an observation."""


def fbs_field(membership: pl.DataFrame, eligibility: pl.DataFrame, season: int, day: date) -> pl.DataFrame:
    """The FBS teams on `day`, each with its bid-eligibility flag for `season` (true unless sourced)."""
    current = membership.filter(
        (pl.col("division") == "fbs")
        & (pl.col("valid_from") <= day)
        & (pl.col("valid_to").is_null() | (pl.col("valid_to") >= day))
    )
    if current["team_id"].is_duplicated().any():
        raise ObservationError(f"a team has two FBS membership rows on {day}")
    flags = eligibility.filter(pl.col("season") == season).select("team_id", "cfp_eligible")
    return (
        current.select("team_id")
        .join(flags, on="team_id", how="left")
        .with_columns(pl.col("cfp_eligible").fill_null(True))
        .sort("team_id")
    )


def observations(release: pl.DataFrame, field: pl.DataFrame) -> pl.DataFrame:
    """Rows (release_id, team_id, rank, below_25, cfp_eligible) for one release over the whole field."""
    ids = release["release_id"].unique().to_list()
    if len(ids) != 1:
        raise ObservationError(f"expected one release, got {sorted(ids)}")
    if sorted(release["rank"].to_list()) != list(range(1, RANKED + 1)):
        raise ObservationError(f"{ids[0]}: a release must rank exactly {RANKED} teams")
    outside = sorted(set(release["team_id"]) - set(field["team_id"]))
    if outside:
        raise ObservationError(f"{ids[0]}: ranked team {outside[0]} is not an FBS team that season")
    return (
        field.join(release.select("team_id", "rank"), on="team_id", how="left")
        .with_columns(release_id=pl.lit(ids[0]), below_25=pl.col("rank").is_null())
        .select("release_id", "team_id", "rank", "below_25", "cfp_eligible")
        .sort(pl.col("rank").fill_null(RANKED + 1), "team_id")
    )


def label_leaked(visible_releases: pl.DataFrame, reveal: datetime) -> bool:
    """True if the release being forecast (or a later one) was already visible at the cutoff (SC-02)."""
    reveal = require_utc(reveal, "reveal")
    return visible_releases.filter(pl.col("reveal_utc") >= reveal).height > 0
