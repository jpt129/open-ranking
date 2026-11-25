"""The field section of an issue (FF-01 to FF-05): pairings, prices, paths and rules in one document."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl
import pytest

from cfp.forecast.final_field import FieldError
from cfp.forecast.noise_params import Noise
from cfp.forecast.pairings import Pairing, Pairings
from cfp.release.field import build_field

from .test_sim_inputs import GAME_SCHEMA, LINE_SCHEMA, game, past, quote

CUT = datetime(2026, 11, 29, 7, tzinfo=UTC)
BOUNDARY = datetime(2026, 12, 2, 0, tzinfo=UTC)  # the reveal of the last weekly release
DAY = datetime(2026, 12, 5, 21, tzinfo=UTC)
TEAMS = [f"R{k:02d}" for k in range(1, 41)]
TITLES = {"sec": ("R01", "R06"), "big-ten": ("R02", "R09"), "big-12": ("R03", "R14"), "acc": ("R05", "R16")}
NOISE = Noise(
    2026,
    "ab" * 32,
    {
        "trained_on": [2024, 2025],
        "temperatures": {"baseline2": {"sun0200": {"final": {"tau": 1.3}, "final_two_back": {"tau": 3.0}}}},
    },
)


def league() -> dict[str, str]:
    out = {team: "sec" for team in TEAMS} | {"R04": "fbs-independents", "R22": "sun-belt", "R30": "sun-belt"}
    for conference, pair in TITLES.items():
        for team in pair:
            out[team] = conference
    return out


def frames(skip: str | None = None) -> tuple[pl.DataFrame, pl.DataFrame]:
    old = [past(season) for season in (2024, 2025)]
    rows, quotes = [], []
    for conference, (home, away) in TITLES.items():
        if conference == skip:
            continue
        gid = f"t-{conference}"
        rows.append(game(gid, start_utc=DAY, home_id=home, away_id=away, neutral=True, title_game=True))
        quotes.append(quote(gid, "a", 3, (-150, 130), -3.0))
    games = pl.concat(
        [f[0] for f in old] + [pl.DataFrame(rows, schema_overrides=GAME_SCHEMA)], how="diagonal_relaxed"
    )
    lines = pl.concat(
        [f[1] for f in old] + [pl.DataFrame(quotes, schema_overrides=LINE_SCHEMA)], how="diagonal_relaxed"
    )
    return games, lines


def pairings(skip: str | None = None, **more: Any) -> Pairings:
    decided = {
        conference: Pairing(conference, DAY.date(), home, away, "official", "https://example.test/x", CUT)
        for conference, (home, away) in TITLES.items()
        if conference != skip
    }
    return Pairings(decided, more.get("scenarios", {}), more.get("open", []), "cd" * 32)


def section(**over: Any) -> dict[str, Any]:
    games, lines = frames(over.pop("skip_game", None))
    rows = [
        {"team_id": t, "initial": k, "losses": 0, "cfp_eligible": True} for k, t in enumerate(TEAMS, start=1)
    ]
    args: dict[str, Any] = {
        "season": 2026,
        "issue": "sun0200",
        "cutoff": CUT,
        "target": 5,
        "total": 6,
        "boundary": BOUNDARY,
        "rows": rows,
        "names": {t: f"School {t}" for t in TEAMS},
        "conference_of": league(),
        "games": games,
        "lines": lines,
        "noise": NOISE,
        "pairings": pairings(),
        "estimate": None,
        "stem": "scw-2026-r05-sun0200",
        "paths": 2000,
    }
    return build_field(**(args | over))


def test_section_holds_the_whole_forecast() -> None:
    doc = section()
    assert (doc["model"], doc["kind"], doc["tau"], doc["paths"]) == ("baseline", "final_two_back", 3.0, 2000)
    run = doc["forecast"]
    assert doc["scenarios"] is None
    assert sum(t["field_paths"] for t in run["teams"]) == 12 * 2000
    assert sum(t["bye_paths"] for t in run["teams"]) == 4 * 2000
    assert all(0.0 < t["p_field"] < 1.0 for t in run["teams"])
    assert [g["title_for"] for g in run["games"]] == ["acc", "big-12", "big-ten", "sec"]
    assert all(g["source"] == "moneyline" and g["title_week"] for g in run["games"])
    by = {t["team_id"]: t for t in run["teams"]}
    assert by["R14"]["next_game"]["field_if_win"] == by["R14"]["next_game"]["win_paths"]
    # the six-conference place is filled on every path, by one of that group's teams
    group = by["R22"]["route_paths"].get("automatic", 0) + by.get("R30", {"route_paths": {}})[
        "route_paths"
    ].get("automatic", 0)
    assert group == 2000
    assert len(run["today"]["field"]) == 12
    assert isinstance(run["seeds"]["games"], int)
    assert any("five" in note or "5 places" in note for note in doc["notes"])
    assert section() == doc  # the same inputs, the same section
    # a team with two games left is conditioned on the earlier one
    games, lines = frames()
    soon = pl.DataFrame(
        [game("rival", start_utc=CUT + timedelta(hours=10), home_id="R01", away_id="R20")],
        schema_overrides=GAME_SCHEMA,
    )
    price = pl.DataFrame([quote("rival", "a", 3, (-400, 300), None)], schema_overrides=LINE_SCHEMA)
    both = section(
        games=pl.concat([games, soon], how="diagonal_relaxed"),
        lines=pl.concat([lines, price], how="diagonal_relaxed"),
    )
    first = {t["team_id"]: t for t in both["forecast"]["teams"]}["R01"]["next_game"]
    assert first["game_id"] == "rival"
    assert first["win_paths"] + first["lose_paths"] == 2000
    assert section(target=6)["kind"] == "final"
    with pytest.raises(FieldError, match="last two releases"):
        section(target=3)


def test_unknown_pairings_become_scenarios_or_stop_the_section() -> None:
    with pytest.raises(FieldError, match="no champion or title game for sec"):
        section(skip_game="sec", pairings=pairings(skip="sec", open=["sec"]))
    options = [
        Pairing(
            "sec",
            DAY.date(),
            "R01",
            "R06",
            "scenario",
            "https://example.test/s",
            CUT,
            "R06 wins the tiebreak",
        ),
        Pairing(
            "sec",
            DAY.date(),
            "R01",
            "R07",
            "scenario",
            "https://example.test/s",
            CUT,
            "R07 wins the tiebreak",
        ),
    ]
    with pytest.raises(FieldError, match="no strength estimate"):
        section(skip_game="sec", pairings=pairings(skip="sec", scenarios={"sec": options}))
    doc = section(
        skip_game="sec",
        pairings=pairings(skip="sec", scenarios={"sec": options}),
        estimate=lambda home, away, neutral: 0.6,
    )
    assert doc["forecast"] is None
    assert [run["scenario"] for run in doc["scenarios"]] == [
        "sec: R06 wins the tiebreak",
        "sec: R07 wins the tiebreak",
    ]
    assert all(sum(t["field_paths"] for t in run["teams"]) == 12 * 2000 for run in doc["scenarios"])
    sec = next(g for g in doc["scenarios"][1]["games"] if g["title_for"] == "sec")
    assert (sec["away_id"], sec["source"], sec["p_home"]) == ("R07", "strength", 0.6)


def test_a_title_game_already_played_gives_its_champion() -> None:
    games, lines = frames()
    done = games.with_columns(
        status=pl.when(pl.col("game_id") == "t-sec").then(pl.lit("final")).otherwise(pl.col("status")),
        home_pts=pl.when(pl.col("game_id") == "t-sec").then(20).otherwise(pl.col("home_pts")),
        away_pts=pl.when(pl.col("game_id") == "t-sec").then(27).otherwise(pl.col("away_pts")),
    )
    doc = section(games=done, lines=lines, pairings=pairings(), cutoff=CUT)
    run = doc["forecast"]
    assert run["champions_decided"] == {"sec": "R06"}
    assert "t-sec" not in [g["game_id"] for g in run["games"]]
    assert {t["team_id"]: t for t in run["teams"]}["R06"]["field_paths"] == 2000
