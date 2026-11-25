"""Name -> team_id, by source. Exact matches only; an unknown name is an error, never a guess."""

from __future__ import annotations

from datetime import date

import polars as pl


class UnknownTeam(LookupError):
    """A source printed a name the alias list does not hold."""


class Resolver:
    def __init__(self, aliases: pl.DataFrame) -> None:
        rows = aliases.select("source", "alias", "team_id").iter_rows()
        self._ids: dict[tuple[str, str], str] = {(str(s), str(a)): str(t) for s, a, t in rows}

    def resolve(self, source: str, name: str) -> str:
        key = (source, " ".join(name.split()))
        if key not in self._ids:
            raise UnknownTeam(
                f"{source}: no team is listed under the name {name!r}; add it to the alias list"
            )
        return self._ids[key]


def membership_on(membership: pl.DataFrame, team_id: str, day: date) -> dict[str, object]:
    """The membership row in force for a team on a date."""
    rows = membership.filter(
        (pl.col("team_id") == team_id)
        & (pl.col("valid_from") <= day)
        & (pl.col("valid_to").is_null() | (pl.col("valid_to") >= day))
    )
    if rows.height != 1:
        raise UnknownTeam(f"{team_id}: {rows.height} membership rows cover {day}")
    return rows.row(0, named=True)
