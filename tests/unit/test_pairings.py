"""Title pairings at a cutoff (FF-04): official rows, the schedule as a labelled fallback, scenarios, open."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from cfp.forecast.pairings import PairingError, conference_id, resolve_pairings

CUT = datetime(2026, 11, 29, 7, tzinfo=UTC)
HEAD = "season,conference,game_date,team_a,team_b,site,site_type,basis,source_url,notes,first_public_utc\n"
SCEN = "season,conference,scenario,team_a,team_b,source_url,first_public_utc,notes\n"
NAMES = {
    "Alpha": "A",
    "Beta": "B",
    "Gamma": "G",
    "Delta": "D",
    "Echo": "E",
    "Fox": "F",
    "Golf": "X",
    "Hotel": "H",
}
LEAGUE = {
    "A": "sec",
    "B": "sec",
    "G": "big-ten",
    "D": "big-ten",
    "E": "acc",
    "F": "acc",
    "X": "big-12",
    "H": "big-12",
}


def files(tmp_path: Path, titles: str, scenarios: str = "") -> tuple[Path, Path]:
    one, two = tmp_path / "title_games.csv", tmp_path / "title_scenarios.csv"
    one.write_text(HEAD + titles)
    two.write_text(SCEN + scenarios)
    return one, two


def schedule(*rows: tuple[str, str, str, datetime]) -> pl.DataFrame:
    return pl.DataFrame(
        [{"game_id": g, "home_id": h, "away_id": a, "start_utc": when} for g, h, a, when in rows],
        schema={
            "game_id": pl.String,
            "home_id": pl.String,
            "away_id": pl.String,
            "start_utc": pl.Datetime("us", "UTC"),
        },
    )


DEC5 = datetime(2026, 12, 5, 21, tzinfo=UTC)
TITLES = (
    "2026,SEC,2026-12-05,Alpha,Beta,,neutral,conference_release,https://example.test/sec,,2026-11-29T05:00:00+00:00\n"
    "2026,Big Ten,2026-12-05,,,,neutral,tracker,https://example.test/b1g,,\n"
    "2026,ACC,2026-12-05,,,,neutral,tracker,https://example.test/acc,,\n"
    "2026,Big 12,2026-12-04,,,,neutral,tracker,https://example.test/b12,,\n"
    "2025,SEC,2025-12-06,Alpha,Beta,,neutral,x,https://example.test/old,,\n"
)


def test_sources_in_order(tmp_path: Path) -> None:
    scenarios = (
        "2026,ACC,if Echo wins,Echo,Fox,https://example.test/acc-tb,2026-11-28T12:00:00+00:00,\n"
        "2026,ACC,if Echo loses,Fox,Echo,https://example.test/acc-tb,2026-11-28T12:00:00+00:00,\n"
    )
    one, two = files(tmp_path, TITLES, scenarios)
    games = schedule(("g-b1g", "G", "D", DEC5), ("g-other", "A", "G", DEC5))
    found = resolve_pairings(one, two, 2026, CUT, NAMES, games, LEAGUE)
    assert (found.decided["sec"].basis, found.decided["sec"].team_a, found.decided["sec"].team_b) == (
        "official",
        "A",
        "B",
    )
    assert found.decided["sec"].source_url == "https://example.test/sec"
    assert (found.decided["big-ten"].basis, found.decided["big-ten"].team_a) == ("cfbd_schedule", "G")
    assert [p.scenario for p in found.scenarios["acc"]] == ["if Echo wins", "if Echo loses"]
    assert found.open == ["big-12"]
    assert len(found.sha256) == 64
    assert conference_id("Big Ten") == "big-ten"


def test_a_row_not_yet_public_is_not_official(tmp_path: Path) -> None:
    one, two = files(tmp_path, TITLES)
    early = CUT - timedelta(hours=3)  # before the SEC row's first-public time
    found = resolve_pairings(one, two, 2026, early, NAMES, schedule(), LEAGUE)
    assert "sec" not in found.decided
    assert found.open == ["acc", "big-12", "big-ten", "sec"]
    # the schedule is used only when it points to exactly one game
    two_games = schedule(("g1", "G", "D", DEC5), ("g2", "D", "G", DEC5 + timedelta(hours=3)))
    assert "big-ten" not in resolve_pairings(one, two, 2026, CUT, NAMES, two_games, LEAGUE).decided


def test_bad_rows_are_refused(tmp_path: Path) -> None:
    bad_time = TITLES.replace("2026-11-29T05:00:00+00:00", "2026-11-29T05:00:00")
    with pytest.raises(PairingError, match="UTC"):
        resolve_pairings(*files(tmp_path, bad_time), 2026, CUT, NAMES, schedule(), LEAGUE)
    unknown = TITLES.replace(
        "Alpha,Beta,,neutral,conference_release", "Alpha,Zulu,,neutral,conference_release"
    )
    with pytest.raises(PairingError, match="Zulu"):
        resolve_pairings(*files(tmp_path, unknown), 2026, CUT, NAMES, schedule(), LEAGUE)
    twice = TITLES + next(line for line in TITLES.splitlines(keepends=True) if line.startswith("2026,"))
    with pytest.raises(PairingError, match="listed twice"):
        resolve_pairings(*files(tmp_path, twice), 2026, CUT, NAMES, schedule(), LEAGUE)
    unsourced = "2026,ACC,one,Echo,Fox,,2026-11-28T12:00:00+00:00,\n"
    with pytest.raises(PairingError, match="label and a source"):
        resolve_pairings(*files(tmp_path, TITLES, unsourced), 2026, CUT, NAMES, schedule(), LEAGUE)
