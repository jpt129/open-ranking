"""OpenRankingView: the only door `cfp.open_ranking` may use (DS-04, OR-12).

It serves games, teams and membership and refuses everything else, so the Open Ranking cannot read committee
releases, polls, lines, market tables or chair remarks. This module deliberately imports nothing that can
open the lake: a view is handed a reader by `Lake.open_ranking_view`, and that reader enforces the same
allow-list again. Python has no real privacy, so the remaining layers are the import contracts, the
source scan in tests/unit/test_open_ranking_backdoors.py and, once editions exist, the test that deletes the
forbidden tables and demands a byte-identical edition.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import ClassVar, Final, final

import polars as pl

from cfp.common.timeutil import require_utc
from cfp.store.types import AsOf, Coverage, Mode, check_mode

__all__ = ["ALLOWED_TABLES", "ForbiddenTable", "OpenRankingView"]

ALLOWED_TABLES: Final[frozenset[str]] = frozenset({"games", "teams", "membership"})

Reader = Callable[[str, int | None], AsOf]


class ForbiddenTable(PermissionError):
    """The view does not serve this table."""


def refuse_unless_allowed(name: str) -> None:
    if name not in ("games", "teams", "membership"):
        raise ForbiddenTable(f"OpenRankingView serves only games, membership and teams; refused {name!r}")


@final
class OpenRankingView:
    ALLOWED: ClassVar[frozenset[str]] = ALLOWED_TABLES
    __slots__ = ("_read", "coverage", "mode", "t")

    def __init__(self, read: Reader, t: datetime, mode: Mode = "replay") -> None:
        check_mode(mode)
        self._read = read
        self.t = require_utc(t, "t")
        self.mode: Mode = mode
        self.coverage: dict[str, Coverage] = {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("OpenRankingView cannot be subclassed")

    def table(self, name: str, season: int | None = None) -> pl.DataFrame:
        refuse_unless_allowed(name)
        result = self._read(name, season)
        self.coverage[name] = result.coverage
        return result.frame
