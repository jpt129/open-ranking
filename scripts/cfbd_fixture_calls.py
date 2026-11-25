"""Stage 1 of the P02a live calls: about ten small requests whose bodies become test fixtures.

Prints shapes only. Bodies are archived in lake/raw; nothing here prints or stores the key.
"""

from __future__ import annotations

import json
from typing import Any

from cfp.common.env import load_env
from cfp.common.timeutil import utc_now
from cfp.ingest.cfbd import Cfbd
from cfp.store.lake import Lake


def shape(value: Any, depth: int = 0) -> str:
    if isinstance(value, list):
        return f"list[{len(value)}] of " + (shape(value[0], depth + 1) if value else "?")
    if isinstance(value, dict):
        if depth >= 3:
            return "{...}"
        return "{" + ", ".join(f"{k}: {shape(v, depth + 1)}" for k, v in value.items()) + "}"
    return type(value).__name__


def main() -> None:
    load_env()
    lake = Lake("lake")
    cfbd = Cfbd.from_env(lake, utc_now())
    info = cfbd.info().json()
    print("info:", json.dumps(info))
    calls = {
        "games_2025_w1": lambda: cfbd.games(2025, "regular", week=1, reuse=True),
        "games_2025_w15": lambda: cfbd.games(2025, "regular", week=15, reuse=True),
        "games_2025_post": lambda: cfbd.games(2025, "postseason", reuse=True),
        "rankings_2025_w1": lambda: cfbd.rankings(2025, "regular", week=1, reuse=True),
        "rankings_2025_w11": lambda: cfbd.rankings(2025, "regular", week=11, reuse=True),
        "lines_2025_w1": lambda: cfbd.lines(2025, "regular", week=1, reuse=True),
        "calendar_2025": lambda: cfbd.calendar(2025, reuse=True),
        "conferences": lambda: cfbd.conferences(reuse=True),
        "fbs_teams_2025": lambda: cfbd.fbs_teams(2025, reuse=True),
    }
    with cfbd.fetcher.stage("fixtures", estimate=10):
        for name, call in calls.items():
            got = call()
            print(f"{name}: {got.raw_hash[:12]} {len(got.body)}B reused={got.reused}")
            print("   " + shape(got.json())[:1500])
    print("budget used:", cfbd.fetcher.budget.used("cfbd"), "info after:", json.dumps(cfbd.info().json()))


if __name__ == "__main__":
    main()
