"""CFP release ingest (P02b): 25 rows, sourced reveal time, cross-check, vintage. Fixtures are recorded."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from cfp.common.hashing import sha256_hex
from cfp.ingest.cfp_releases import (
    Capture,
    Release,
    capture_queries,
    cross_check,
    find_capture,
    ingest_season,
    load_aliases,
    load_schedule,
    page_matches,
    parse_cfbd,
    parse_espn,
    parse_site,
    resolve,
    vintage_for,
)
from cfp.ingest.errors import CrossCheckFailed, MissingSource, SourceError
from cfp.ingest.http import Budget, Fetched, Fetcher, Response, TokenBucket
from cfp.store.lake import Lake

from .store_helpers import Clock

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures"
SCHEDULE = load_schedule(ROOT / "data" / "cfp_reveals.csv")
ALIASES = load_aliases(ROOT / "data" / "aliases_cfp_site.csv")
NOW = datetime(2026, 11, 25, 15, 0, tzinfo=UTC)


def site_2026() -> list[dict[str, Any]]:
    return json.loads((FIX / "cfp_site_rankings_2026.json").read_text())  # type: ignore[no-any-return]


def espn_2026() -> dict[date, list[str]]:
    out: dict[date, list[str]] = {}
    for week in (10, 11, 12, 13):
        parsed = parse_espn(json.loads((FIX / f"espn_rankings_2026_w{week}.json").read_text()))
        assert parsed is not None
        out[parsed[0]] = parsed[1]
    return out


def fetched(lake: Lake, payload: Any, at: datetime = NOW) -> Fetched:
    body = json.dumps(payload).encode()
    return Fetched("cfp_site", "https://example.test/api/v2/rankings?year=2026", lake.put_raw(body), body, at)


def test_parse_site_numbers_releases_by_date() -> None:
    releases = parse_site(site_2026(), 2026)
    assert [(r.release_id, r.day.isoformat()) for r in releases] == [
        ("cfp-2026-01", "2026-11-03"),
        ("cfp-2026-02", "2026-11-10"),
        ("cfp-2026-03", "2026-11-17"),
        ("cfp-2026-04", "2026-11-24"),
    ]
    assert all(len(r.names) == 25 for r in releases)
    assert releases[3].names[:4] == ("Georgia", "Utah", "Texas", "Notre Dame")


@pytest.mark.parametrize("damage", ["drop_row", "repeat_rank", "repeat_team", "wrong_year", "repeat_date"])
def test_parse_site_rejects_malformed_releases(damage: str) -> None:
    payload = site_2026()
    teams = payload[0]["teams"]
    if damage == "drop_row":
        teams.pop()
    elif damage == "repeat_rank":
        teams[4]["rank"] = 4
    elif damage == "repeat_team":
        teams[4]["team"] = teams[3]["team"]
    elif damage == "wrong_year":
        payload[0]["year"] = 2025
    else:
        payload[1]["releaseDate"] = payload[0]["releaseDate"]
    with pytest.raises(SourceError):
        parse_site(payload, 2026)


def test_empty_payload_is_a_missing_source() -> None:
    with pytest.raises(MissingSource):
        parse_site([], 2026)


def test_schedule_times_are_eastern_and_sourced() -> None:
    assert SCHEDULE[date(2026, 11, 24)].show_start == datetime(2026, 11, 25, 0, 30, tzinfo=UTC)  # 19:30 ET
    assert SCHEDULE[date(2026, 12, 1)].show_start == datetime(2026, 12, 2, 0, 0, tzinfo=UTC)  # 19:00 ET
    assert SCHEDULE[date(2026, 12, 6)].show_start == datetime(2026, 12, 6, 17, 0, tzinfo=UTC)  # noon ET
    assert SCHEDULE[date(2025, 11, 4)].show_start == datetime(2025, 11, 5, 1, 0, tzinfo=UTC)  # 20:00 ET, EST
    assert SCHEDULE[date(2014, 10, 28)].show_start == datetime(2014, 10, 28, 23, 30, tzinfo=UTC)  # 19:30 EDT
    # the site misdates the 2016 final; the show aired Sunday 4 Dec at noon ET
    assert SCHEDULE[date(2016, 12, 6)].show_start == datetime(2016, 12, 4, 17, 0, tzinfo=UTC)
    assert all(reveal.source_url.startswith("https://") for reveal in SCHEDULE.values())
    for key, reveal in SCHEDULE.items():
        local = reveal.show_start.astimezone(UTC) - timedelta(hours=5)
        assert local.weekday() in (1, 6), key  # Tuesday or Sunday


def test_every_archived_name_has_an_alias() -> None:
    for release in parse_site(site_2026(), 2026):
        assert len(set(resolve(release, ALIASES))) == 25


def test_unknown_name_fails_loudly() -> None:
    release = parse_site(site_2026(), 2026)[0]
    renamed = Release(
        release.season, release.release_no, release.day, ("Georgia Tech State", *release.names[1:])
    )
    with pytest.raises(MissingSource, match="Georgia Tech State"):
        resolve(renamed, ALIASES)


def test_cross_check_agrees_with_espn_for_all_four_2026_releases() -> None:
    second = espn_2026()
    for release in parse_site(site_2026(), 2026):
        cross_check(release, resolve(release, ALIASES), second.get(release.day), "espn")


def test_cross_check_fails_on_swap_and_on_missing_release() -> None:
    release = parse_site(site_2026(), 2026)[3]
    ids = resolve(release, ALIASES)
    swapped = [ids[1], ids[0], *ids[2:]]
    with pytest.raises(CrossCheckFailed, match="#1"):
        cross_check(release, ids, swapped, "espn")
    with pytest.raises(CrossCheckFailed, match="no matching release"):
        cross_check(release, ids, None, "espn")
    with pytest.raises(CrossCheckFailed):
        cross_check(release, ids, ids[:24], "espn")


def test_parse_cfbd_orders_regular_then_postseason() -> None:
    def week(season_type: str, number: int, first: int) -> dict[str, Any]:
        ranks = [{"rank": r, "teamId": first + r, "school": "x"} for r in range(1, 26)]
        polls = [{"poll": "AP Top 25", "ranks": []}, {"poll": "Playoff Committee Rankings", "ranks": ranks}]
        return {"season": 2025, "seasonType": season_type, "week": number, "polls": polls}

    payload = [week("postseason", 1, 300), week("regular", 11, 100), week("regular", 12, 200)]
    payload.append(
        {"season": 2025, "seasonType": "regular", "week": 2, "polls": [{"poll": "AP Top 25", "ranks": []}]}
    )
    got = parse_cfbd(payload)
    assert [ids[0] for ids in got] == ["cfbd-101", "cfbd-201", "cfbd-301"]


def test_page_matches_recorded_press_release() -> None:
    page = (FIX / "wayback_cfp_news_20251105073639.html").read_text()
    first_2025 = parse_site(json.loads((FIX / "cfp_site_rankings_2025_first.json").read_text()), 2025)[0]
    assert page_matches(page, first_2025.names)
    swapped = (first_2025.names[1], first_2025.names[0], *first_2025.names[2:])
    assert not page_matches(page, swapped)
    assert not page_matches(page, parse_site(site_2026(), 2026)[0].names)


def test_page_matches_needs_rank_next_to_name() -> None:
    names = [f"Team{chr(65 + i)}" for i in range(25)]
    listed = " ".join(f"<li>{rank}. {name} (9-0)</li>" for rank, name in enumerate(names, 1))
    assert page_matches(listed, names)
    assert not page_matches(" ".join(names), names)
    assert not page_matches(listed.replace("<li>7. TeamG", "<li>7. TeamGX"), names)


def test_page_matches_rejects_a_name_that_is_only_a_prefix() -> None:
    """ "3. Texas A&M" must not verify a release that has Texas third (nor Oklahoma State for Oklahoma)."""
    names = ["Georgia", "Utah", "Texas", "Oklahoma"] + [f"Team{chr(65 + i)}" for i in range(21)]
    page = " ".join(f"<td>{rank}</td><td>{name}</td><td>9-2</td>" for rank, name in enumerate(names, 1))
    assert page_matches(page, names)
    assert not page_matches(page.replace("<td>Texas</td>", "<td>Texas A&amp;M</td>"), names)
    assert not page_matches(page.replace("<td>Oklahoma</td>", "<td>Oklahoma State</td>"), names)
    bare = " ".join(f"{rank}. {name}" for rank, name in enumerate(names, 1))  # no records on the page
    assert page_matches(bare, names)
    assert not page_matches(bare.replace("3. Texas", "3. Texas Tech"), names)


def test_vintage_rules() -> None:
    reveal = datetime(2025, 11, 5, 1, 0, tzinfo=UTC)
    inside = Capture(reveal + timedelta(hours=6), "u", "0" * 64)
    assert vintage_for(reveal, reveal + timedelta(days=1), None) == "live"
    assert vintage_for(reveal, reveal + timedelta(days=7), None) == "live"
    assert vintage_for(reveal, reveal + timedelta(days=380), inside) == "archived_authentic"
    assert vintage_for(reveal, reveal + timedelta(days=380), None) == "reconstructed"
    late = Capture(reveal + timedelta(days=7, seconds=1), "u", "0" * 64)
    early = Capture(reveal - timedelta(seconds=1), "u", "0" * 64)
    assert vintage_for(reveal, reveal + timedelta(days=380), late) == "reconstructed"
    assert vintage_for(reveal, reveal + timedelta(days=380), early) == "reconstructed"


def _ingest(
    lake: Lake, payload: Any, second: Mapping[date, list[str]], captures: Mapping[date, Capture]
) -> Any:
    return ingest_season(lake, 2026, fetched(lake, payload), SCHEDULE, ALIASES, second, "espn", captures)


def test_ingest_season_writes_100_rows_with_provenance(tmp_path: Path) -> None:
    lake = Lake(tmp_path, clock=Clock(NOW))
    capture = Capture(
        datetime(2026, 11, 4, 9, 0, tzinfo=UTC), "https://web.archive.org/x", lake.put_raw(b"page")
    )
    result = _ingest(lake, site_2026(), espn_2026(), {date(2026, 11, 3): capture})
    assert (result.new, result.corrected, result.unchanged) == (100, 0, 0)
    rows = lake.scan("committee_releases").collect().sort("release_id", "rank")
    by_release = dict(rows.group_by("release_id").agg(v=pl.col("vintage").first()).iter_rows())
    assert by_release == {
        "cfp-2026-01": "archived_authentic",  # three weeks old, verified by a capture
        "cfp-2026-02": "reconstructed",  # two weeks old, no capture
        "cfp-2026-03": "reconstructed",  # eight days old
        "cfp-2026-04": "live",  # captured the morning after
    }
    last = rows.filter(rows["release_id"] == "cfp-2026-04")
    assert last["team_id"].to_list()[:3] == ["cfbd-61", "cfbd-254", "cfbd-251"]
    assert last["source_name"].to_list()[:3] == ["Georgia", "Utah", "Texas"]
    assert set(last["first_public_time"].to_list()) == {datetime(2026, 11, 25, 0, 30, tzinfo=UTC)}
    assert set(last["reveal_utc"].to_list()) == {datetime(2026, 11, 25, 0, 30, tzinfo=UTC)}
    first = rows.filter(rows["release_id"] == "cfp-2026-01")
    assert set(first["archive_capture_utc"].to_list()) == {capture.taken}
    assert set(first["archive_raw_hash"].to_list()) == {capture.raw_hash}
    assert last["archive_capture_utc"].null_count() == 25

    # the release is invisible one second before its show and visible at the start
    show = datetime(2026, 11, 25, 0, 30, tzinfo=UTC)
    before = lake.as_of("committee_releases", show - timedelta(seconds=1), "replay").frame
    assert "cfp-2026-04" not in set(before["release_id"].to_list())
    assert lake.as_of("committee_releases", show, "replay").frame.height == 100
    # ... but a live issue only sees it once we had ingested it
    assert lake.as_of("committee_releases", show, "live").frame.height == 0
    assert lake.as_of("committee_releases", NOW, "live").frame.height == 100

    again = _ingest(lake, site_2026(), espn_2026(), {date(2026, 11, 3): capture})
    assert (again.new, again.corrected, again.unchanged) == (0, 0, 100)


def test_ingest_writes_nothing_when_any_release_fails(tmp_path: Path) -> None:
    lake = Lake(tmp_path, clock=Clock(NOW))
    second = espn_2026()
    bad = copy.deepcopy(second)
    last = bad[date(2026, 11, 24)]
    last[23], last[24] = last[24], last[23]
    with pytest.raises(CrossCheckFailed, match="cfp-2026-04"):
        _ingest(lake, site_2026(), bad, {})
    del second[date(2026, 11, 10)]
    with pytest.raises(CrossCheckFailed, match="cfp-2026-02"):
        _ingest(lake, site_2026(), second, {})
    schedule = {k: v for k, v in SCHEDULE.items() if k != date(2026, 11, 17)}
    with pytest.raises(MissingSource, match="show start"):
        ingest_season(lake, 2026, fetched(lake, site_2026()), schedule, ALIASES, espn_2026(), "espn", {})
    assert lake.scan("committee_releases").collect().height == 0


def test_release_captured_before_its_show_is_refused(tmp_path: Path) -> None:
    lake = Lake(tmp_path, clock=Clock(NOW))
    early = fetched(lake, site_2026(), datetime(2026, 11, 25, 0, 29, tzinfo=UTC))
    with pytest.raises(SourceError, match="before its scheduled reveal"):
        ingest_season(lake, 2026, early, SCHEDULE, ALIASES, espn_2026(), "espn", {})


class Wayback:
    """Serves a CDX index and pages from memory."""

    def __init__(self, index: dict[str, list[list[str]]], pages: dict[str, bytes]) -> None:
        self.index, self.pages, self.urls = index, pages, []  # type: ignore[var-annotated]

    def __call__(self, url: str, headers: Mapping[str, str], timeout: float) -> Response:
        self.urls.append(url)
        if "cdx/search" in url:
            for needle, rows in self.index.items():
                if needle in url:
                    return Response(
                        200, json.dumps([["urlkey", "timestamp", "original"], *rows]).encode(), {}
                    )
            return Response(200, b"[]", {})
        for stamp, body in self.pages.items():
            if f"/web/{stamp}id_/" in url:
                return Response(200, body, {})
        return Response(404, b"", {})


def test_find_capture_takes_first_matching_page_inside_the_window(tmp_path: Path) -> None:
    import gzip

    lake = Lake(tmp_path, clock=Clock(NOW))
    release = parse_site(json.loads((FIX / "cfp_site_rankings_2025_first.json").read_text()), 2025)[0]
    reveal = SCHEDULE[release.day].show_start  # 2025-11-05 01:00 UTC
    page = (FIX / "wayback_cfp_news_20251105073639.html").read_bytes()
    story = "https://collegefootballplayoff.com/news/2025/11/4/cfp-rankings.aspx"
    index = {
        "news%2F2025%2F11%2F4": [
            ["k", "20251105005900", story],  # a minute before the show: outside the window
            ["k", "20251105024046", "https://collegefootballplayoff.com/news/2025/11/4/25-first-round.aspx"],
            ["k", "20251105073639", story],
        ]
    }
    packed = gzip.compress(page, mtime=0)
    pages = {"20251105005900": page, "20251105024046": b"<p>another story</p>", "20251105073639": packed}
    transport = Wayback(index, pages)
    wayback = Fetcher(
        lake,
        "wayback",
        "https://web.archive.org",
        budget=Budget(tmp_path / "budget.json", clock=lambda: NOW),
        allowance=100,
        bucket=TokenBucket(1000.0, 1000.0),
        transport=transport,
        clock=lambda: NOW,
    )
    assert capture_queries(release)[0] == {
        "url": "collegefootballplayoff.com/news/2025/11/4/",
        "matchType": "prefix",
    }
    capture = find_capture(wayback, release, reveal)
    assert capture is not None
    assert capture.taken == datetime(2025, 11, 5, 7, 36, 39, tzinfo=UTC)
    assert capture.raw_hash == sha256_hex(packed)
    assert not any("20251105005900id_" in url for url in transport.urls)

    none = find_capture(wayback, parse_site(site_2026(), 2026)[0], SCHEDULE[date(2026, 11, 3)].show_start)
    assert none is None


def test_release_missing_from_the_payload_fails_and_ids_do_not_shift(tmp_path: Path) -> None:
    lake = Lake(tmp_path, clock=Clock(NOW))
    without_second = [r for r in site_2026() if not r["releaseDate"].startswith("2026-11-10")]
    with pytest.raises(SourceError, match="lacks releases already shown"):
        _ingest(lake, without_second, espn_2026(), {})
    assert lake.scan("committee_releases").collect().height == 0
    # before the 17 Nov show, a payload with two releases is complete, and numbers follow the schedule
    early = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
    first_two = [r for r in site_2026() if r["releaseDate"][:10] in ("2026-11-03", "2026-11-10")]
    lake2 = Lake(tmp_path / "second", clock=Clock(early))
    ingest_season(lake2, 2026, fetched(lake2, first_two, early), SCHEDULE, ALIASES, espn_2026(), "espn", {})
    assert sorted(set(lake2.scan("committee_releases").collect()["release_id"].to_list())) == [
        "cfp-2026-01",
        "cfp-2026-02",
    ]


def test_finding_or_losing_a_capture_later_writes_no_correction(tmp_path: Path) -> None:
    lake = Lake(tmp_path, clock=Clock(NOW))
    _ingest(lake, site_2026(), espn_2026(), {})
    capture = Capture(
        datetime(2026, 11, 11, 9, 0, tzinfo=UTC), "https://web.archive.org/x", lake.put_raw(b"page")
    )
    for captures in ({date(2026, 11, 10): capture}, {}):
        again = _ingest(lake, site_2026(), espn_2026(), captures)
        assert (again.new, again.corrected, again.unchanged) == (0, 0, 100)
    stored = lake.scan("committee_releases").collect()
    assert stored["correction_version"].max() == 0
    assert set(stored.filter(pl.col("release_id") == "cfp-2026-02")["vintage"].to_list()) == {"reconstructed"}


def test_schedule_row_without_a_source_is_refused(tmp_path: Path) -> None:
    header = "season,release_date,show_date,show_start_et,basis,source_url,quote,notes\n"
    path = tmp_path / "reveals.csv"
    path.write_text(header + "2026,2026-12-01,2026-12-01,19:00,,,,\n")
    with pytest.raises(SourceError, match="no source"):
        load_schedule(path)
    path.write_text(header + "2026,2026-12-01,2026-12-01,,,,,\n")
    assert load_schedule(path) == {}


def test_old_seasons_cannot_be_ingested_without_cfbd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """There is no switch that lets a 2014-25 season through on a weaker check."""
    from cfp.cli import build_parser
    from cfp.ingest import run

    with pytest.raises(SystemExit):
        build_parser().parse_args(["ingest", "releases", "--season", "2025", "--second", "espn"])
    lake = Lake(tmp_path, clock=Clock(NOW))
    body = (FIX / "cfp_site_rankings_2025_first.json").read_bytes()

    class Site:
        def get(self, path: str, params: Any = None, reuse: bool = False) -> Fetched:
            return Fetched("cfp_site", "u", lake.put_raw(body), body, NOW)

    monkeypatch.setattr(run, "public_fetcher", lambda *a, **k: Site())
    with pytest.raises(ValueError, match="CFBD cross-check"):
        run.ingest_releases(lake, 2025, ROOT / "data", None)


def test_parse_cfbd_drops_a_postseason_copy_of_the_final_release() -> None:
    def week(season_type: str, number: int, first: int) -> dict[str, Any]:
        ranks = [{"rank": r, "teamId": first + r} for r in range(1, 26)]
        polls = [{"poll": "Playoff Committee Rankings", "ranks": ranks}]
        return {"season": 2014, "seasonType": season_type, "week": number, "polls": polls}

    copied = parse_cfbd([week("regular", 15, 100), week("regular", 16, 200), week("postseason", 1, 200)])
    assert [ids[0] for ids in copied] == ["cfbd-101", "cfbd-201"]
    distinct = parse_cfbd([week("regular", 15, 100), week("postseason", 1, 200)])
    assert [ids[0] for ids in distinct] == ["cfbd-101", "cfbd-201"]


def test_parse_espn_core() -> None:
    from cfp.ingest.cfp_releases import parse_espn_core

    base = "http://sports.core.api.espn.com/v2/sports/football/leagues/college-football/seasons/2023/teams"
    ranks = [
        {"current": r, "team": {"$ref": f"{base}/{1000 + r}?lang=en&region=us"}} for r in range(25, 0, -1)
    ]
    payload = {"type": "cfp", "date": "2023-10-31T07:00Z", "ranks": ranks}
    day, ids = parse_espn_core(payload)
    assert day == date(2023, 10, 31)
    assert ids[:2] == ["cfbd-1001", "cfbd-1002"]
    assert len(ids) == 25
    with pytest.raises(SourceError):
        parse_espn_core(payload | {"type": "ap"})
    with pytest.raises(SourceError):
        parse_espn_core(payload | {"ranks": ranks[:24]})
