"""Team identity and dated membership (P03)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from cfp.identity import build
from cfp.identity.resolver import Resolver, UnknownTeam, membership_on
from cfp.identity.run import build_identity
from cfp.ingest.cfbd import Cfbd
from cfp.ingest.errors import CrossCheckFailed, MissingSource, SourceError
from cfp.ingest.http import Budget, Fetched, Fetcher, Response, TokenBucket
from cfp.store.lake import Lake
from cfp.store.views import ForbiddenTable

from .store_helpers import Clock

NOW = datetime(2026, 11, 25, 18, 0, tzinfo=UTC)
FIX = Path(__file__).resolve().parents[1] / "fixtures"
HEADER = "season,conference,group,basis,source_url,notes\n"


def side(
    prefix: str, team_id: int, name: str, division: str | None, conference: str | None
) -> dict[str, Any]:
    return {
        f"{prefix}Id": team_id,
        f"{prefix}Team": name,
        f"{prefix}Classification": division,
        f"{prefix}Conference": conference,
    }


def game(home: tuple[Any, ...], away: tuple[Any, ...]) -> dict[str, Any]:
    return side("home", *home) | side("away", *away)


TEXAS_23 = (251, "Texas", "fbs", "Big 12")
TEXAS_24 = (251, "Texas", "fbs", "SEC")
IRISH = (87, "Notre Dame", "fbs", "FBS Independents")
RICE = (242, "Rice", "fbs", "American Athletic")
FCS = (2000, "Made-up State", "fcs", "Big Sky")
NAIA = (9000, "Made-up Christian", None, None)
SEASONS = {
    2023: [game(TEXAS_23, RICE), game(IRISH, FCS), game(FCS, NAIA)],
    2024: [game(TEXAS_24, IRISH), game(RICE, FCS)],
}


def espn_team(team_id: int, location: str, display: str) -> dict[str, Any]:
    return {
        "team": {"id": str(team_id), "location": location, "displayName": display, "shortDisplayName": ""}
    }


ESPN_TEAMS = [
    espn_team(251, "Texas", "Texas Longhorns"),
    espn_team(87, "Notre Dame", "Notre Dame Fighting Irish"),
    espn_team(242, "Rice", "Rice Owls"),
    espn_team(2000, "Made-up State", "Made-up State Bears"),
    espn_team(9000, "Made-up State", "MC Bears"),  # a different spelling, on the hand-checked list
]
ESPN_MATCHES = "team_id,cfbd_name,espn_location,note\ncfbd-9000,Made-up Christian,Made-up State,hand\n"


def espn_payload(lake: Lake, teams: list[dict[str, Any]] | None = None) -> Fetched:
    body = json.dumps({"sports": [{"leagues": [{"teams": ESPN_TEAMS if teams is None else teams}]}]}).encode()
    return Fetched("espn", "https://espn.example.test/teams", lake.put_raw(body), body, NOW)


OVERRIDES = "team_id,name,reason\n"


def write_data(
    tmp_path: Path, groups: str | None = None, counts: str = "2023,3\n2024,3\n", overrides: str = OVERRIDES
) -> Path:
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    rows = groups
    if rows is None:
        rows = "".join(
            f"{season},{name},{group},primary,https://example.test/rule,\n"
            for season in (2023, 2024)
            for name, group in (
                ("Big 12", "power"),
                ("SEC", "power"),
                ("American Athletic", "non_power"),
                ("FBS Independents", "independent"),
            )
        )
    (data / "conference_groups.csv").write_text(HEADER + rows)
    (data / "fbs_counts.csv").write_text("season,played\n" + counts)
    (data / "team_name_overrides.csv").write_text(overrides)
    (data / "espn_id_matches.csv").write_text(ESPN_MATCHES)
    (data / "aliases_cfp_site.csv").write_text("alias,team_id\nTexas,cfbd-251\nNotre Dame,cfbd-87\n")
    return data


def archive(tmp_path: Path, seasons: dict[int, list[dict[str, Any]]]) -> tuple[Lake, Cfbd, list[str]]:
    """A lake whose fetch log already holds each season's /games payloads; later calls would be recorded."""
    clock = Clock(NOW)
    lake = Lake(tmp_path / "lake", clock=clock)
    urls: list[str] = []

    def transport(url: str, headers: Any, timeout: float) -> Response:
        urls.append(url)
        year = int(url.split("year=")[1][:4])
        body = seasons[year] if "seasonType=regular" in url else []
        return Response(200, json.dumps(body).encode(), {})

    fetcher = Fetcher(
        lake,
        "cfbd",
        "https://api.example.test",
        budget=Budget(tmp_path / "budget.json", clock=clock),
        allowance=100,
        bucket=TokenBucket(1000.0, 1000.0),
        transport=transport,
        clock=clock,
    )
    cfbd = Cfbd(fetcher)
    for season in seasons:
        cfbd.games(season, "regular")
        cfbd.games(season, "postseason")
    return lake, cfbd, urls


def test_conference_slug() -> None:
    assert build.conference_id("Mid-American") == "mid-american"
    assert build.conference_id("FBS Independents") == "fbs-independents"
    assert build.conference_id("Big 12") == "big-12"
    assert build.conference_id(None) is None


def test_season_teams_from_recorded_title_week() -> None:
    teams = build.season_teams([json.loads((FIX / "cfbd_games_2025_w15.json").read_text())])
    ohio_state = teams["cfbd-194"]
    assert (ohio_state.name, ohio_state.division, ohio_state.conference) == ("Ohio State", "fbs", "Big Ten")
    assert sum(team.division == "fbs" for team in teams.values()) == 18
    assert {team.division for team in teams.values()} == {"fbs", "fcs", "iii"}


@pytest.mark.parametrize("change", ["conference", "division", "name"])
def test_a_team_that_changes_within_a_season_stops_the_build(change: str) -> None:
    moved = {"conference": (251, "Texas", "fbs", "SEC"), "division": (251, "Texas", "fcs", "Big 12")}
    other = moved.get(change, (251, "Texas Longhorns", "fbs", "Big 12"))
    with pytest.raises(build.IdentityError, match="within a season"):
        build.season_teams([[game(TEXAS_23, RICE), game(other, IRISH)]])


def test_build_writes_teams_aliases_and_dated_membership(tmp_path: Path) -> None:
    lake, cfbd, urls = archive(tmp_path, SEASONS)
    calls_before = len(urls)
    results = build_identity(lake, cfbd, write_data(tmp_path), [2023, 2024], espn_payload(lake))
    assert len(urls) == calls_before  # built from the archive; no call is made
    assert sum(r.new for r in results.results) > 0
    assert results.unconfirmed_espn == []

    teams = lake.scan("teams").collect().sort("team_id")
    assert teams["team_id"].to_list() == ["cfbd-2000", "cfbd-242", "cfbd-251", "cfbd-87", "cfbd-9000"]
    by_id = {row["team_id"]: row for row in teams.iter_rows(named=True)}
    assert (by_id["cfbd-251"]["name"], by_id["cfbd-251"]["cfbd_id"], by_id["cfbd-251"]["espn_id"]) == (
        "Texas",
        251,
        251,
    )
    assert by_id["cfbd-9000"]["espn_id"] == 9000  # confirmed by the hand-checked list
    assert set(teams["vintage"].to_list()) == {"reconstructed"}

    membership = lake.scan("membership").collect()
    assert membership.height == 5 + 4
    in_2023 = membership_on(membership, "cfbd-251", date(2023, 11, 25))
    in_2024 = membership_on(membership, "cfbd-251", date(2024, 11, 30))
    assert (in_2023["conference_id"], in_2023["cfp_group"]) == ("big-12", "power")
    assert (in_2024["conference_id"], in_2024["cfp_group"]) == ("sec", "power")
    irish = membership_on(membership, "cfbd-87", date(2024, 9, 1))
    assert (irish["conference_id"], irish["division"], irish["cfp_group"]) == (
        "fbs-independents",
        "fbs",
        "independent",
    )
    lower = membership_on(membership, "cfbd-2000", date(2023, 9, 1))
    assert (lower["division"], lower["cfp_group"]) == ("fcs", None)
    assert membership_on(membership, "cfbd-9000", date(2023, 9, 1))["division"] == "unknown"
    with pytest.raises(UnknownTeam):  # no row covers a season the team did not play
        membership_on(membership, "cfbd-9000", date(2024, 9, 1))

    # point in time: the 2024 move is not visible in a replay before 1 Aug 2024
    before = lake.as_of("membership", datetime(2024, 8, 19, tzinfo=UTC), "replay").frame
    assert before.filter(pl.col("team_id") == "cfbd-251")["conference_id"].to_list() == ["big-12"]

    again = build_identity(lake, cfbd, write_data(tmp_path), [2023, 2024], espn_payload(lake))
    assert sum(r.new + r.corrected for r in again.results) == 0


def test_resolver_is_exact_and_fails_loudly(tmp_path: Path) -> None:
    lake, cfbd, _ = archive(tmp_path, SEASONS)
    build_identity(lake, cfbd, write_data(tmp_path), [2023, 2024], espn_payload(lake))
    resolver = Resolver(lake.scan("team_aliases").collect())
    assert resolver.resolve("cfbd", "Texas") == "cfbd-251"
    assert resolver.resolve("cfp_site", "Notre  Dame") == "cfbd-87"  # whitespace only
    assert resolver.resolve("espn", "Texas Longhorns") == "cfbd-251"
    for source, name in (
        ("cfbd", "texas"),
        ("cfp_site", "Rice"),
        ("kalshi", "Texas"),
        ("espn", "Springfield"),
    ):
        with pytest.raises(UnknownTeam):  # wrong case, unlisted, unknown source, a name two schools share
            resolver.resolve(source, name)
    assert resolver.resolve("espn", "Made-up State Bears") == "cfbd-2000"


def test_checks_run_before_anything_is_written(tmp_path: Path) -> None:
    lake, cfbd, _ = archive(tmp_path, SEASONS)
    with pytest.raises(CrossCheckFailed, match="2024"):
        build_identity(
            lake, cfbd, write_data(tmp_path, counts="2023,3\n2024,4\n"), [2023, 2024], espn_payload(lake)
        )
    with pytest.raises(MissingSource, match="FBS team count"):
        build_identity(lake, cfbd, write_data(tmp_path, counts="2023,3\n"), [2023, 2024], espn_payload(lake))
    no_sec = "".join(
        f"{s},{n},{g},primary,https://example.test/rule,\n"
        for s in (2023, 2024)
        for n, g in (
            ("Big 12", "power"),
            ("American Athletic", "non_power"),
            ("FBS Independents", "independent"),
        )
    )
    with pytest.raises(MissingSource, match="SEC"):
        build_identity(lake, cfbd, write_data(tmp_path, groups=no_sec), [2023, 2024], espn_payload(lake))
    with pytest.raises(SourceError, match="no source"):
        build_identity(
            lake,
            cfbd,
            write_data(tmp_path, groups="2023,SEC,power,primary,,\n"),
            [2023, 2024],
            espn_payload(lake),
        )
    with pytest.raises(MissingSource, match="no archived"):
        build_identity(lake, cfbd, write_data(tmp_path), [2022, 2023], espn_payload(lake))
    for table in ("teams", "team_aliases", "membership"):
        assert lake.scan(table).collect().height == 0


def test_alias_pointing_at_two_teams_or_at_no_team_stops_the_build(tmp_path: Path) -> None:
    clash = {2023: [game(TEXAS_23, RICE)], 2024: [game((999, "Texas", "fbs", "SEC"), RICE)]}
    teams = {season: build.season_teams([games]) for season, games in clash.items()}
    _lake, cfbd, _ = archive(tmp_path, clash)
    sources = {season: cfbd.games(season, "regular", reuse=True) for season in clash}
    with pytest.raises(build.IdentityError, match="points at both"):
        build.alias_rows(teams, sources, {}, {}, {})
    with pytest.raises(build.IdentityError, match="in no game payload"):
        build.alias_rows({2023: teams[2023]}, sources, {"Georgia": "cfbd-61"}, {}, {})


def test_open_ranking_view_reads_identity_tables_only(tmp_path: Path) -> None:
    lake, cfbd, _ = archive(tmp_path, SEASONS)
    build_identity(lake, cfbd, write_data(tmp_path), [2023, 2024], espn_payload(lake))
    view = lake.open_ranking_view(NOW)
    assert view.table("teams").height == 5
    assert view.table("membership").height == 9
    with pytest.raises(ForbiddenTable):
        view.table("team_aliases")


def test_repo_data_files_load_and_cover_every_season() -> None:
    data = Path(__file__).resolve().parents[2] / "data"
    groups = build.load_groups(data / "conference_groups.csv")
    counts = build.load_counts(data / "fbs_counts.csv")
    assert set(counts) == set(range(2014, 2027))
    assert (counts[2014], counts[2020], counts[2026]) == (128, 127, 138)
    assert {season for season, _ in groups} == set(range(2014, 2027))
    assert groups[(2023, "Pac-12")] == "power"
    assert groups[(2026, "Pac-12")] == "non_power"
    assert all(groups[(season, "FBS Independents")] == "independent" for season in range(2014, 2027))


def test_one_name_for_two_teams_needs_a_hand_kept_override(tmp_path: Path) -> None:
    seasons = {2023: [game(TEXAS_23, IRISH), game(FCS, (999, "Texas", None, None))]}
    lake, cfbd, _ = archive(tmp_path, seasons)
    with pytest.raises(build.IdentityError, match="points at both"):
        build_identity(lake, cfbd, write_data(tmp_path, counts="2023,2\n"), [2023], espn_payload(lake))
    fixed = OVERRIDES + "cfbd-999,Texas (other),a different school\n"
    build_identity(
        lake, cfbd, write_data(tmp_path, counts="2023,2\n", overrides=fixed), [2023], espn_payload(lake)
    )
    resolver = Resolver(lake.scan("team_aliases").collect())
    assert (resolver.resolve("cfbd", "Texas"), resolver.resolve("cfbd", "Texas (other)")) == (
        "cfbd-251",
        "cfbd-999",
    )
    with pytest.raises(SourceError, match="reason"):
        build.load_overrides(_no_reason(tmp_path))


def _no_reason(tmp_path: Path) -> Path:
    path = tmp_path / "bad.csv"
    path.write_text(OVERRIDES + "cfbd-1,X,\n")
    return path


def test_espn_id_is_kept_only_when_espn_names_the_same_school(tmp_path: Path) -> None:
    lake, cfbd, _ = archive(tmp_path, SEASONS)
    other = [t for t in ESPN_TEAMS if t["team"]["id"] != "2000"] + [
        espn_team(2000, "Elsewhere Tech", "Elsewhere Tech Owls")
    ]
    report = build_identity(lake, cfbd, write_data(tmp_path), [2023, 2024], espn_payload(lake, other))
    assert report.unconfirmed_espn == ["cfbd-2000: CFBD 'Made-up State', ESPN 'Elsewhere Tech'"]
    teams = {r["team_id"]: r["espn_id"] for r in lake.scan("teams").collect().iter_rows(named=True)}
    assert (teams["cfbd-2000"], teams["cfbd-251"]) == (None, 251)
    aliases = lake.scan("team_aliases").collect()
    assert aliases.filter(pl.col("alias") == "Elsewhere Tech").height == 0


def test_an_fbs_team_espn_does_not_confirm_stops_the_build(tmp_path: Path) -> None:
    lake, cfbd, _ = archive(tmp_path, SEASONS)
    wrong = [t for t in ESPN_TEAMS if t["team"]["id"] != "242"] + [
        espn_team(242, "Houston Christian", "HCU Huskies")
    ]
    with pytest.raises(build.IdentityError, match="ESPN does not confirm"):
        build_identity(lake, cfbd, write_data(tmp_path), [2023, 2024], espn_payload(lake, wrong))
    missing = [t for t in ESPN_TEAMS if t["team"]["id"] != "242"]
    with pytest.raises(build.IdentityError, match="ESPN does not confirm"):
        build_identity(lake, cfbd, write_data(tmp_path), [2023, 2024], espn_payload(lake, missing))
    assert lake.scan("teams").collect().height == 0


def test_alias_rows_cite_their_own_source(tmp_path: Path) -> None:
    lake, cfbd, _ = archive(tmp_path, SEASONS)
    data = write_data(tmp_path)
    espn = espn_payload(lake)
    build_identity(lake, cfbd, data, [2023, 2024], espn)
    aliases = lake.scan("team_aliases").collect()
    by_source = {
        s: (i, h) for s, i, h in aliases.select("source", "source_id", "raw_hash").unique().iter_rows()
    }
    assert by_source["espn"] == ("espn:/teams", espn.raw_hash)
    assert by_source["cfp_site"][0] == "data:aliases_cfp_site.csv"
    assert lake.get_raw(by_source["cfp_site"][1]) == (data / "aliases_cfp_site.csv").read_bytes()
    assert by_source["cfbd"][0] == "cfbd:/games"
