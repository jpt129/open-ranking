"""Title pairings at a cutoff (FF-04): official rows, the schedule as a labelled fallback, scenarios, open."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from cfp.forecast.pairings import PairingError, conference_id, resolve_pairings, review_pairings

CUT = datetime(2026, 11, 29, 7, tzinfo=UTC)
HEAD = "season,conference,game_date,team_a,team_b,site,site_type,basis,source_url,notes,first_public_utc\n"
SCEN = (
    "season,conference,scenario,team_a,team_b,source_url,first_public_utc,notes,basis,source_url_2,outlets\n"
)
NAMES = {
    "Alpha": "A",
    "Beta": "B",
    "Gamma": "G",
    "Delta": "D",
    "Echo": "E",
    "Fox": "F",
    "Golf": "X",
    "Hotel": "H",
    "Zeta": "Z",
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
    "Z": "acc",
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
        "2026,ACC,if Echo wins,Echo,Fox,https://example.test/acc-tb,2026-11-28T12:00:00+00:00,,conference_scenarios,\n"
        "2026,ACC,if Echo loses,Fox,Zeta,https://example.test/acc-tb,2026-11-28T12:00:00+00:00,,conference_scenarios,\n"
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
    assert found.scenarios["acc"][0].listed_by == (
        "possible pairings worked out from the conference's published scenarios (https://example.test/acc-tb)"
    )
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
    unsourced = "2026,ACC,one,Echo,Fox,,2026-11-28T12:00:00+00:00,,conference_scenarios,\n"
    with pytest.raises(PairingError, match="label and a source"):
        resolve_pairings(*files(tmp_path, TITLES, unsourced), 2026, CUT, NAMES, schedule(), LEAGUE)


NAMED = ("acc", "big-ten", "big-12", "sec")
HEAD2 = HEAD.rstrip("\n") + ",result_url\n"


def test_a_pairing_is_final_only_on_the_conference_word(tmp_path: Path) -> None:
    """(a) the conference announced it, or (b) its published scenario and the deciding score are public."""
    media = TITLES.replace("conference_release", "si_tracker+fbschedules")
    found = resolve_pairings(*files(tmp_path, media), 2026, CUT, NAMES, schedule(), LEAGUE)
    assert "sec" not in found.decided  # a media tracker settles nothing
    assert any("sec" in note and "si_tracker" in note for note in found.ignored)
    rows = (
        "2026,SEC,2026-12-05,Alpha,Beta,,neutral,conference_scenario+result,https://example.test/sec-scen,,"
        "2026-11-29T04:10:00+00:00,https://example.test/final-score\n"
    )
    one, two = tmp_path / "title_games.csv", tmp_path / "title_scenarios.csv"
    one.write_text(HEAD2 + rows)
    two.write_text(SCEN)
    found = resolve_pairings(one, two, 2026, CUT, NAMES, schedule(), LEAGUE)
    assert found.decided["sec"].basis == "official"
    assert found.decided["sec"].source_url == "https://example.test/sec-scen https://example.test/final-score"
    one.write_text(HEAD2 + rows.replace(",https://example.test/final-score", ","))
    with pytest.raises(PairingError, match="result_url"):
        resolve_pairings(one, two, 2026, CUT, NAMES, schedule(), LEAGUE)


def review(tmp_path: Path, titles: str, scenarios: str = "", **over: object) -> object:
    one, two = files(tmp_path, titles, scenarios)
    args: dict[str, object] = {"games": schedule(), "named": NAMED, "group_leagues": ()}
    args |= over
    return review_pairings(one, two, 2026, CUT, NAMES, LEAGUE, **args)  # type: ignore[arg-type]


def test_the_operators_check(tmp_path: Path) -> None:
    def row(league: str, a: str, b: str, when: str = "2026-11-29T04:00:00+00:00") -> str:
        return (
            f"2026,{league},2026-12-05,{a},{b},,neutral,conference_release,https://example.test/x,,{when}\n"
        )

    full = row("SEC", "Alpha", "Beta") + row("Big Ten", "Gamma", "Delta") + row("ACC", "Echo", "Fox")
    good = review(tmp_path, full + row("Big 12", "Golf", "Hotel"))
    assert good.problems == []  # type: ignore[attr-defined]
    assert good.combinations == 1  # type: ignore[attr-defined]
    assert any("sec" in line and "A v B" in line for line in good.lines)  # type: ignore[attr-defined]

    open_named = review(
        tmp_path, full + "2026,Big 12,2026-12-04,,,,neutral,tracker,https://example.test/b,,\n"
    )
    assert any("big-12" in p and "not delivered" in p for p in open_named.problems)  # type: ignore[attr-defined]

    scen = (
        "2026,Big 12,Golf in,Golf,Hotel,https://example.test/s,2026-11-28T23:00:00+00:00,,conference_scenarios,\n"
        "2026,Big 12,Echo in,Golf,Echo,https://example.test/s,2026-11-28T23:00:00+00:00,,conference_scenarios,\n"
    )
    b12 = "2026,Big 12,2026-12-04,,,,neutral,tracker,https://example.test/b,,\n"
    wrong = review(tmp_path, full + b12, scen)
    assert any("Echo" in p and "big-12" in p for p in wrong.problems)  # type: ignore[attr-defined]
    twice = review(tmp_path, full + b12, scen.replace("Golf,Echo", "Hotel,Golf").replace("Echo in", "swap"))
    assert any("listed twice" in p for p in twice.problems)  # type: ignore[attr-defined]
    fine = review(tmp_path, full + b12, scen.splitlines(keepends=True)[0])
    assert fine.problems == []  # type: ignore[attr-defined]
    assert fine.combinations == 1  # type: ignore[attr-defined]

    late = review(tmp_path, full + row("Big 12", "Golf", "Hotel", "2026-11-29T08:00:00+00:00"))
    assert any("after the cutoff" in p for p in late.problems)  # type: ignore[attr-defined]
    blank = review(tmp_path, full + row("Big 12", "Golf", "Hotel", ""))
    assert any("no first-public time" in p for p in blank.problems)  # type: ignore[attr-defined]
    broken = review(tmp_path, "this is not, a title file\n")
    assert broken.problems  # type: ignore[attr-defined]
    assert any("not delivered" in p for p in broken.problems)  # type: ignore[attr-defined]
    sun = "2026,Sun Belt,2026-12-04,,,,neutral,tracker,https://example.test/sb,,\n"
    grouped = review(tmp_path, full + row("Big 12", "Golf", "Hotel") + sun, group_leagues=("sun-belt",))
    assert grouped.problems == []  # type: ignore[attr-defined]
    assert any("sun-belt" in w and "5%" in w for w in grouped.warnings)  # type: ignore[attr-defined]


def test_the_schedule_settles_nothing_for_a_named_conference(tmp_path: Path) -> None:
    """For the four named leagues the schedule is a cross-check only: it warns and changes nothing."""
    one, two = files(tmp_path, TITLES)
    games = schedule(("g-b1g", "G", "D", DEC5), ("g-sec", "A", "G", DEC5), ("g-b12", "X", "H", DEC5))
    found = resolve_pairings(one, two, 2026, CUT, NAMES, games, LEAGUE, named=("sec", "big-ten"))
    assert "big-ten" not in found.decided  # the schedule's game is not the conference's word
    assert found.decided["big-12"].basis == "cfbd_schedule"  # still on, secondary, for the others
    assert len(found.warnings) == 1  # the Big Ten game the schedule shows is reported, not used
    other = schedule(("g-sec", "A", "B2", DEC5))
    league = LEAGUE | {"B2": "sec"}
    found = resolve_pairings(one, two, 2026, CUT, NAMES | {"Beta Two": "B2"}, other, league, named=("sec",))
    assert (found.decided["sec"].team_a, found.decided["sec"].team_b) == ("A", "B")  # the file stands
    (warning,) = found.warnings
    assert all(word in warning for word in ("sec", "schedule", "Alpha v Beta Two", "file stands"))
    # scenarios on file and the schedule shows a pairing that is not among them
    b1g = "2026,Big Ten,D in,Gamma,Delta,https://example.test/s,2026-11-28T12:00:00+00:00,,conference_scenarios,\n"
    one, two = files(tmp_path, TITLES, b1g)
    odd = schedule(("g-b1g", "G", "D2", DEC5))
    found = resolve_pairings(
        one, two, 2026, CUT, NAMES | {"Delta Two": "D2"}, odd, LEAGUE | {"D2": "big-ten"}, named=("big-ten",)
    )
    assert any("not among the listed scenarios" in w for w in found.warnings)
    # nothing on file: the schedule is reported, and settles nothing
    found = resolve_pairings(*files(tmp_path, TITLES), 2026, CUT, NAMES, games, LEAGUE, named=("big-ten",))
    assert "big-ten" not in found.decided
    assert any("big-ten" in w and "settles nothing" in w for w in found.warnings)


def test_a_scenario_list_may_rest_on_two_outlets(tmp_path: Path) -> None:
    """The test for a scenario list is that it is complete: the conference's, or two outlets that agree."""
    base = "2026,ACC,{label},{a},{b},https://one.example.test/x,2026-11-28T12:00:00+00:00,,{basis},{second}\n"
    two_rows = base.format(
        label="E in", a="Echo", b="Fox", basis="two_outlets", second="https://two.example.org/y"
    )
    two_rows += base.format(
        label="Z in", a="Echo", b="Zeta", basis="two_outlets", second="https://two.example.org/y"
    )
    found = resolve_pairings(*files(tmp_path, TITLES, two_rows), 2026, CUT, NAMES, schedule(), LEAGUE)
    assert [p.listed_by for p in found.scenarios["acc"]] == [
        "possible pairings per one.example.test and two.example.org; not published by the ACC"
    ] * 2
    for bad, message in (
        (two_rows.replace("https://two.example.org/y", ""), "two outlets"),
        (two_rows.replace("https://two.example.org/y", "https://one.example.test/z"), "two outlets"),
        (two_rows.replace("https://two.example.org/y", "https://www.ONE.example.test./z"), "two outlets"),
        (two_rows.replace("two_outlets", "a_guess"), "basis"),
        (two_rows.replace("two_outlets", "conference_scenarios", 1), "one basis"),
    ):
        with pytest.raises(PairingError, match=message):
            resolve_pairings(*files(tmp_path, TITLES, bad), 2026, CUT, NAMES, schedule(), LEAGUE)


def test_the_pairings_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from cfp import cli

    from .test_issue import world

    pairs = {
        "SEC": ("T01", "T02"),
        "Big Ten": ("T03", "T04"),
        "Big 12": ("T05", "T06"),
        "ACC": ("T07", "T08"),
    }
    leagues = {t: conference_id(label) for label, pair in pairs.items() for t in pair}
    world(tmp_path, leagues=leagues | {"T26": "sun-belt", "T27": "sun-belt"})
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    row = (
        "2026,{league},2026-12-05,School {a},School {b},,neutral,conference_release,https://example.test/x,,"
        "2026-11-28T12:00:00+00:00\n"
    )
    good = HEAD + "".join(row.format(league=label, a=a, b=b) for label, (a, b) in pairs.items())
    argv = ["--lake", str(tmp_path / "lake"), "--data", str(data), "forecast", "pairings", "--season", "2026"]
    argv += ["--cutoff", "2026-11-29T07:00:00+00:00"]
    (data / "title_games.csv").write_text(good)
    assert cli.main(argv) == 0
    assert capsys.readouterr().out.rstrip().splitlines()[-1].startswith("OK")
    (data / "title_games.csv").write_text("\ufeff" + good)
    assert cli.main(argv) != 0
    said = capsys.readouterr()
    assert "PROBLEM" in said.err
    assert "title_games.csv" in said.err
    assert said.out.rstrip().splitlines()[-1].startswith("NOT OK")
    (data / "title_games.csv").write_text(good + "2026,Sun Belt,2026-12-05,School T26,School T27\n")
    assert cli.main(argv) != 0
    said = capsys.readouterr()
    assert "PROBLEM" in said.err
    assert "title_games.csv" in said.err
    assert said.out.rstrip().splitlines()[-1].startswith("NOT OK")


def test_outlets_are_named_when_the_url_is_a_carrier(tmp_path: Path) -> None:
    """A wire story is read on a carrier's site; the edition names the outlet and keeps the site."""
    row = (
        "2026,ACC,{label},Echo,{b},https://carrier.example.test/ap,2026-11-28T12:00:00+00:00,,two_outlets,"
        "https://two.example.org/y,Associated Press; Second Outlet\n"
    )
    rows = row.format(label="F in", b="Fox") + row.format(label="Z in", b="Zeta")
    found = resolve_pairings(*files(tmp_path, TITLES, rows), 2026, CUT, NAMES, schedule(), LEAGUE)
    assert found.scenarios["acc"][0].listed_by == (
        "possible pairings per Associated Press (carrier.example.test) and Second Outlet (two.example.org); "
        "not published by the ACC"
    )
    checked = (
        "2026,ACC,F in,Echo,Fox,https://example.test/acc,2026-11-28T12:00:00+00:00,,conference_scenarios,"
        "https://carrier.example.test/ap,Associated Press\n"
    )
    found = resolve_pairings(*files(tmp_path, TITLES, checked), 2026, CUT, NAMES, schedule(), LEAGUE)
    assert found.scenarios["acc"][0].listed_by == (
        "possible pairings worked out from the conference's published scenarios (https://example.test/acc); "
        "cross-checked against Associated Press (carrier.example.test)"
    )
    assert found.scenarios["acc"][0].source_url.split() == [
        "https://example.test/acc",
        "https://carrier.example.test/ap",
    ]
    same = rows.replace("Associated Press; Second Outlet", "Associated Press; associated press")
    with pytest.raises(PairingError, match="outlets must name"):
        resolve_pairings(*files(tmp_path, TITLES, same), 2026, CUT, NAMES, schedule(), LEAGUE)
    bad = rows.replace("Associated Press; Second Outlet", "Associated Press")
    with pytest.raises(PairingError, match="outlets must name"):
        resolve_pairings(*files(tmp_path, TITLES, bad), 2026, CUT, NAMES, schedule(), LEAGUE)


def test_the_real_hand_files_are_well_formed() -> None:
    """Every row of the two files in data/ has the header's width, and the title list loads."""
    import csv

    from cfp.snapshot.data import load_title_games

    data = Path(__file__).resolve().parents[2] / "data"
    for name in ("title_games.csv", "title_scenarios.csv"):
        with (data / name).open(newline="") as handle:
            rows = list(csv.reader(handle))
        assert {len(row) for row in rows} == {len(rows[0])}, name
    assert load_title_games(data / "title_games.csv")
