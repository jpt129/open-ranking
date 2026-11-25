"""PointInTimeView: point-in-time reads of any table, for the forecasts, scoring and the Gap.

Never imported by `cfp.open_ranking` (import contract in pyproject.toml).
"""

from __future__ import annotations

from datetime import datetime

import polars as pl

from cfp.common.timeutil import require_utc
from cfp.store.lake import Lake
from cfp.store.types import Coverage, Mode, check_mode


class PointInTimeView:
    def __init__(self, lake: Lake, t: datetime, mode: Mode) -> None:
        check_mode(mode)
        self._lake = lake
        self.t = require_utc(t, "t")
        self.mode: Mode = mode
        self.coverage: dict[str, Coverage] = {}

    def table(self, name: str, season: int | None = None) -> pl.DataFrame:
        result = self._lake.as_of(name, self.t, self.mode, season=season)
        self.coverage[name] = result.coverage
        return result.frame
