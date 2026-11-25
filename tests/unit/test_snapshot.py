"""Snapshot builder (P04, OR-07): what is scored at a cutoff, what is left out, and why."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from cfp.snapshot.build import SnapshotBlocked, build_snapshot
from cfp.snapshot.data import (
    Forfeit,
    SnapshotDataError,
    TitleGame,
    Unplayed,
    load_forfeits,
    load_title_games,
    load_unplayed,
)
from cfp.store.lake import Lake

from .store_helpers import Clock, frame, game

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[2]
SUN_0200 = datetime(2026, 11, 29, 2, 0, tzinfo=ET).astimezone(UTC)
MON_0600 = datetime(2026, 11, 30, 6, 0, tzinfo=ET).astimezone(UTC)
SAT_NOON = datetime(2026, 11, 28, 12, 0, tzinfo=ET).astimezone(UTC)
SAT_2230 = datetime(2026, 11, 28, 22, 30, tzinfo=ET).astimezone(UTC)
PUBLIC_LAG = timedelta(hours=4, minutes=30)
AUG = datetime(2026, 8, 20, 4, 0, tzinfo=UTC)
TEAMS = {  # id: (name, division, conference)
    "T-TEX": ("Texas", "fbs", "sec"),
    "T-UGA": ("Georgia", "fbs", "sec"),
    "T-RICE": ("Rice", "fbs", "american-athletic"),
    "T-NDSU": ("North Dakota State", "fbs", "mountain-west"),
    "T-FCS": ("Made-up State", "fcs", "big-sky"),
    "T-D2": ("Made-up Tech", "ii", None),
}
SEC_TITLE = TitleGame(2026, "SEC", date(2026, 12, 5), "Texas", "Georgia", "https://example.test/sec")


def provenance(lake: Lake, label: str, public: datetime) -> dict[str, Any]:
    return {
        "source_id": "test",
        "event_time": public,
        "first_public_time": public,
        "ingest_time": None,
        "correction_version": 0,
        "raw_hash": lake.put_raw(label.encode()),
        "vintage": "reconstructed",
    }


def world(
    tmp_path: Path, games: list[dict[str, Any]], teams: dict[str, tuple[str, str, str | None]] | None = None
) -> Lake:
    lake = Lake(tmp_path / "lake", clock=Clock(MON_0600 + timedelta(days=30)))
    teams = TEAMS if teams is None else teams
    lake.append(
        "teams",
        frame(
            "teams",
            [
                {"team_id": i, "name": n, "cfbd_id": k, "espn_id": None, "kalshi_code": None}
                | provenance(lake, i, AUG)
                for k, (i, (n, _, _)) in enumerate(teams.items())
            ],
        ),
    )
    lake.append(
        "membership",
        frame(
            "membership",
            [
                {
                    "team_id": i,
                    "valid_from": date(2026, 8, 1),
                    "valid_to": date(2027, 7, 31),
                    "conference_id": conf,
                    "division": division,
                    "cfp_group": None,
                    "source_url": None,
                }
                | provenance(lake, "m" + i, AUG)
                for i, (_, division, conf) in teams.items()
            ],
        ),
    )
    if games:
        lake.append("games", frame("games", games))
    return lake


def played(
    lake: Lake, game_id: str, home: str, away: str, start: datetime = SAT_NOON, **over: Any
) -> dict[str, Any]:
    public = start + PUBLIC_LAG
    base = {
        "home_id": home,
        "away_id": away,
        "start_utc": start,
        "home_div": TEAMS[home][1],
        "away_div": TEAMS[away][1],
        "event_time": public,
        "first_public_time": public,
        "vintage": "reconstructed",
    }
    return game(lake, game_id, **(base | over))


def snap(lake: Lake, cutoff: datetime, **lists: Any) -> Any:
    lists.setdefault("title_games", [])
    return build_snapshot(lake.open_ranking_view(cutoff), 2026, **lists)


def test_a_late_saturday_game_is_out_on_sunday_morning_and_in_on_monday(tmp_path: Path) -> None:
    lake = Lake(tmp_path / "lake", clock=Clock(MON_0600))
    games = [played(lake, "noon", "T-TEX", "T-RICE"), played(lake, "late", "T-UGA", "T-RICE", SAT_2230)]
    lake = world(tmp_path, games)
    sunday, monday = snap(lake, SUN_0200), snap(lake, MON_0600)
    assert sunday.games["game_id"].to_list() == ["noon"]
    assert monday.games["game_id"].to_list() == ["late", "noon"]
    assert sunday.snapshot_hash != monday.snapshot_hash
    assert (sunday.cutoff, sunday.mode) == (SUN_0200, "replay")


def test_rows_carry_site_division_and_conference_on_the_game_date(tmp_path: Path) -> None:
    lake = Lake(tmp_path / "lake", clock=Clock(MON_0600))
    lake = world(
        tmp_path,
        [played(lake, "g", "T-TEX", "T-RICE", neutral=True, site="NRG Stadium", home_pts=31, away_pts=10)],
    )
    row = snap(lake, MON_0600).games.row(0, named=True)
    assert (row["home_conf"], row["away_conf"], row["home_div"], row["away_div"]) == (
        "sec",
        "american-athletic",
        "fbs",
        "fbs",
    )
    assert (row["neutral"], row["site"], row["winner_id"], row["ordinary_fbs"]) == (
        True,
        "NRG Stadium",
        "T-TEX",
        True,
    )
    assert (row["forfeit"], row["margin_excluded"], row["title_game"]) == (False, False, False)


def test_first_year_fbs_member_is_an_ordinary_fbs_opponent(tmp_path: Path) -> None:
    """John's ruling: North Dakota State in 2026 is FBS; a loss to it is never an FCS loss."""
    lake = Lake(tmp_path / "lake", clock=Clock(MON_0600))
    lake = world(
        tmp_path,
        [
            played(lake, "ndsu", "T-NDSU", "T-RICE", home_pts=35, away_pts=7),
            played(lake, "ndsu-fcs", "T-NDSU", "T-FCS"),
            played(lake, "fcs", "T-TEX", "T-FCS"),
        ],
    )
    rows = {r["game_id"]: r for r in snap(lake, MON_0600).games.iter_rows(named=True)}
    assert (rows["ndsu"]["home_div"], rows["ndsu"]["ordinary_fbs"]) == ("fbs", True)
    assert (rows["ndsu-fcs"]["ordinary_fbs"], rows["ndsu-fcs"]["away_div"]) == (False, "fcs")
    assert rows["fcs"]["ordinary_fbs"] is False


def test_omissions_are_logged_with_reasons(tmp_path: Path) -> None:
    lake = Lake(tmp_path / "lake", clock=Clock(MON_0600))
    lake = world(
        tmp_path,
        [
            played(lake, "kept", "T-TEX", "T-RICE"),
            played(lake, "bowl", "T-TEX", "T-RICE", season_type="postseason"),
            played(lake, "lower", "T-FCS", "T-D2"),
            played(lake, "sched", "T-UGA", "T-RICE", status="scheduled", home_pts=None, away_pts=None),
        ],
    )
    gone = Unplayed(2026, date(2026, 11, 14), "Texas", "Rice", "cancelled", "https://example.test/c")
    later = Unplayed(2026, date(2026, 12, 12), "Texas", "Georgia", "cancelled", "https://example.test/d")
    result = snap(lake, MON_0600, unplayed=[gone, later])
    assert result.games["game_id"].to_list() == ["kept"]
    reasons = dict(result.omissions.select("reason", "game_id").iter_rows())
    assert reasons == {
        "postseason": "bowl",
        "no_fbs_team": "lower",
        "not_final_at_cutoff": "sched",
        "cancelled": None,
    }
    assert result.omissions.filter(result.omissions["reason"] == "cancelled")["detail"].to_list() == [
        "https://example.test/c"
    ]


def test_listed_forfeit_is_a_result_but_not_a_margin(tmp_path: Path) -> None:
    lake = Lake(tmp_path / "lake", clock=Clock(MON_0600))
    lake = world(tmp_path, [played(lake, "ff", "T-TEX", "T-RICE", home_pts=0, away_pts=2)])
    with pytest.raises(SnapshotBlocked, match="looks like a forfeit"):
        snap(lake, MON_0600)
    row = snap(lake, MON_0600, forfeits=[Forfeit("ff", "T-RICE", "https://example.test/f")]).games.row(
        0, named=True
    )
    assert (row["winner_id"], row["forfeit"], row["margin_excluded"], row["ordinary_fbs"]) == (
        "T-RICE",
        True,
        True,
        False,
    )
    with pytest.raises(SnapshotBlocked, match="did not play"):
        snap(lake, MON_0600, forfeits=[Forfeit("ff", "T-UGA", "https://example.test/f")])


def test_title_game_comes_from_the_list_and_keeps_its_real_site(tmp_path: Path) -> None:
    kick = datetime(2026, 12, 5, 16, 0, tzinfo=ET).astimezone(UTC)
    after = datetime(2026, 12, 7, 6, 0, tzinfo=ET).astimezone(UTC)
    lake = Lake(tmp_path / "lake", clock=Clock(after))
    lake = world(
        tmp_path, [played(lake, "sec", "T-TEX", "T-UGA", kick, neutral=False, season_type="postseason")]
    )
    row = snap(lake, after, title_games=[SEC_TITLE]).games.row(0, named=True)
    assert (row["title_game"], row["neutral"], row["ordinary_fbs"]) == (
        True,
        False,
        True,
    )  # not forced neutral
    assert snap(lake, after).omissions["reason"].to_list() == [
        "postseason"
    ]  # unlisted: an ordinary postseason game


def test_title_list_and_source_must_agree(tmp_path: Path) -> None:
    lake = Lake(tmp_path / "lake", clock=Clock(MON_0600))
    lake = world(tmp_path, [played(lake, "odd", "T-TEX", "T-RICE", title_game=True)])
    assert snap(lake, MON_0600).games["title_game"].to_list() == [
        False
    ]  # no list for the season: the flag is ignored
    with pytest.raises(SnapshotBlocked, match="not on the list"):
        snap(lake, MON_0600, title_games=[SEC_TITLE])
    unknown = TitleGame(2026, "ACC", date(2026, 12, 5), "Clemson", "Miami", "https://example.test/acc")
    with pytest.raises(SnapshotBlocked, match="no team is named"):
        snap(lake, MON_0600, title_games=[unknown])
    late = datetime(2026, 12, 20, tzinfo=UTC)
    lake2 = world(
        tmp_path / "b", [played(Lake(tmp_path / "b" / "lake", clock=Clock(late)), "g", "T-TEX", "T-RICE")]
    )
    with pytest.raises(SnapshotBlocked, match="not in the data"):
        snap(lake2, late, title_games=[SEC_TITLE])


def test_classification_clash_or_missing_membership_blocks(tmp_path: Path) -> None:
    lake = Lake(tmp_path / "lake", clock=Clock(MON_0600))
    lake = world(tmp_path, [played(lake, "g", "T-TEX", "T-NDSU", away_div="fcs")])
    with pytest.raises(SnapshotBlocked, match="ask before building"):
        snap(lake, MON_0600)
    fewer = {k: v for k, v in TEAMS.items() if k != "T-RICE"}
    lake2 = world(
        tmp_path / "b",
        [played(Lake(tmp_path / "b" / "lake", clock=Clock(MON_0600)), "g", "T-TEX", "T-RICE")],
        fewer,
    )
    with pytest.raises(SnapshotBlocked, match="membership does not cover"):
        snap(lake2, MON_0600)


def test_ties_and_missing_scores_block(tmp_path: Path) -> None:
    lake = Lake(tmp_path / "lake", clock=Clock(MON_0600))
    lake = world(tmp_path, [played(lake, "tie", "T-TEX", "T-RICE", home_pts=21, away_pts=21)])
    with pytest.raises(SnapshotBlocked, match="tie"):
        snap(lake, MON_0600)


def test_hash_depends_on_content_not_on_row_order_or_cutoff(tmp_path: Path) -> None:
    a = Lake(tmp_path / "a" / "lake", clock=Clock(MON_0600))
    a = world(tmp_path / "a", [played(a, "g1", "T-TEX", "T-RICE"), played(a, "g2", "T-UGA", "T-RICE")])
    b = Lake(tmp_path / "b" / "lake", clock=Clock(MON_0600))
    b = world(tmp_path / "b", [played(b, "g2", "T-UGA", "T-RICE"), played(b, "g1", "T-TEX", "T-RICE")])
    first, second = snap(a, MON_0600), snap(b, MON_0600)
    assert first.snapshot_hash == second.snapshot_hash
    assert snap(a, MON_0600 + timedelta(hours=1)).snapshot_hash == first.snapshot_hash
    assert len(first.snapshot_hash) == 64


def test_a_corrected_score_changes_the_hash_only_once_public(tmp_path: Path) -> None:
    lake = Lake(tmp_path / "lake", clock=Clock(MON_0600 + timedelta(days=2)))
    lake = world(tmp_path, [played(lake, "g", "T-TEX", "T-RICE", home_pts=28, away_pts=24)])
    fixed_at = MON_0600 + timedelta(days=1)
    fix = played(
        lake,
        "g",
        "T-TEX",
        "T-RICE",
        home_pts=27,
        away_pts=24,
        correction_version=1,
        first_public_time=fixed_at,
    )
    lake.append("games", frame("games", [fix]))
    before, after = snap(lake, MON_0600), snap(lake, fixed_at)
    assert (before.games["home_pts"][0], after.games["home_pts"][0]) == (28, 27)
    assert before.snapshot_hash != after.snapshot_hash


def test_data_loaders_validate(tmp_path: Path) -> None:
    path = tmp_path / "t.csv"
    header = "season,conference,game_date,team_a,team_b,site,site_type,basis,source_url,notes\n"
    path.write_text(
        header
        + "2020,Pac-12,2020-12-18,,,,not_played,x,https://example.test/a,\n2026,SEC,2026-12-05,,,,neutral,x,https://example.test/b,\n"
    )
    assert [(t.season, t.team_a) for t in load_title_games(path)] == [(2026, "")]
    path.write_text(header + "2026,SEC,2026-12-05,Texas,,,neutral,x,https://example.test/b,\n")
    with pytest.raises(SnapshotDataError, match="one team"):
        load_title_games(path)
    path.write_text(header + "2026,SEC,2026-12-05,Texas,Georgia,,neutral,x,,\n")
    with pytest.raises(SnapshotDataError, match="no source"):
        load_title_games(path)
    path.write_text(
        "scheduled_date,home,away,status,made_up_date,basis,source_url,notes\n2020-11-14,A,B,vanished,,x,https://example.test/c,\n"
    )
    with pytest.raises(SnapshotDataError, match="unknown status"):
        load_unplayed(path)
    path.write_text("game_id,winner_id,source_url,note\ng1,T-TEX,https://example.test/f,\n")
    assert load_forfeits(path) == [Forfeit("g1", "T-TEX", "https://example.test/f")]
