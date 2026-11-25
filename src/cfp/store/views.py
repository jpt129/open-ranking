"""Read views over the lake (DS-04).

OpenRankingView is the only door `cfp.open_ranking` may use. It serves games, teams and membership and
refuses everything else, so the Open Ranking cannot read committee releases, polls, lines, market tables or
chair remarks even by accident. PointInTimeView serves the forecasts and records coverage per table.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

import polars as pl

from cfp.common.timeutil import require_utc
from cfp.store.asof import Coverage, Mode
from cfp.store.lake import Lake


class ForbiddenTable(PermissionError):
    """The view does not serve this table."""


class OpenRankingView:
    ALLOWED: ClassVar[frozenset[str]] = frozenset({"games", "teams", "membership"})
    __slots__ = ("__lake", "mode", "t")

    def __init__(self, lake: Lake, t: datetime, mode: Mode = "replay") -> None:
        self.__lake = lake
        self.t = require_utc(t, "t")
        self.mode: Mode = mode

    def table(self, name: str) -> pl.DataFrame:
        if name not in self.ALLOWED:
            raise ForbiddenTable(f"OpenRankingView serves only {sorted(self.ALLOWED)}; refused {name!r}")
        return self.__lake.as_of(name, self.t, self.mode).frame


class PointInTimeView:
    def __init__(self, lake: Lake, t: datetime, mode: Mode) -> None:
        self._lake = lake
        self.t = require_utc(t, "t")
        self.mode: Mode = mode
        self.coverage: dict[str, Coverage] = {}

    def table(self, name: str) -> pl.DataFrame:
        result = self._lake.as_of(name, self.t, self.mode)
        self.coverage[name] = result.coverage
        return result.frame
