"""Command-line entry point. Subcommands are added by later build prompts."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cfp import __version__

FIRST_SEASON = 2014


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cfp", description="Open Ranking command line.")
    parser.add_argument("--version", action="version", version=f"cfp {__version__}")
    parser.add_argument("--lake", default="lake", help="data lake directory (default: lake)")
    parser.add_argument("--data", default="data", help="hand-verified data directory (default: data)")
    commands = parser.add_subparsers(dest="command", metavar="<command>")

    ingest = commands.add_parser("ingest", help="fetch, verify and store source data")
    kinds = ingest.add_subparsers(dest="kind", metavar="<source>", required=True)
    releases = kinds.add_parser("releases", help="CFP committee releases for one or more seasons")
    releases.add_argument("--season", type=int, nargs="+", required=True)
    cfbd = kinds.add_parser("cfbd", help="CFBD games, polls and lines for one or more seasons")
    cfbd.add_argument("--season", type=int, nargs="+", required=True)
    cfbd.add_argument("--what", nargs="+", choices=("games", "rankings", "reference", "lines"), required=True)
    cfbd.add_argument("--stage", required=True, help="name for the call counter, e.g. season-2026")

    kinds.add_parser("odds", help="current game lines from The Odds API (3 credits a pull)")

    identity = commands.add_parser("identity", help="team identity and conference membership")
    identity.add_subparsers(dest="kind", metavar="<action>", required=True).add_parser(
        "build", help="rebuild teams, aliases and membership from archived payloads"
    )

    markets = commands.add_parser("markets", help="read-only market capture (evaluation only)")
    market_kinds = markets.add_subparsers(dest="kind", metavar="<action>", required=True)
    snap = market_kinds.add_parser("snapshot", help="capture listings, best quotes and order books now")
    snap.add_argument("--no-depth", action="store_true", help="skip the per-contract order books")
    hist = market_kinds.add_parser("history", help="hourly venue history for the depth-flagged events")
    hist.add_argument("--hours", type=int, default=48)

    snapshot = commands.add_parser("snapshot", help="the games the Open Ranking scores at a cutoff")
    snapshot_build = snapshot.add_subparsers(dest="kind", metavar="<action>", required=True).add_parser(
        "build", help="build and summarise a snapshot (writes nothing)"
    )
    snapshot_build.add_argument("--season", type=int, required=True)
    snapshot_build.add_argument(
        "--cutoff", required=True, help="ISO time with offset, e.g. 2026-11-29T02:00-05:00"
    )
    snapshot_build.add_argument("--mode", choices=["live", "replay"], default="replay")

    commands.add_parser("budget", help="show API calls used this month")
    return parser


def _ingest_releases(args: argparse.Namespace) -> int:
    from cfp.common.env import load_env
    from cfp.common.timeutil import utc_now
    from cfp.ingest.cfbd import Cfbd
    from cfp.ingest.errors import SourceError
    from cfp.ingest.run import LIVE_SEASON, ingest_releases
    from cfp.store.lake import Lake

    load_env()
    lake = Lake(args.lake)
    failed: list[int] = []
    for season in args.season:
        cfbd = None
        if season < LIVE_SEASON:
            cfbd = Cfbd.from_env(lake, utc_now())
            cfbd.sync_budget()
        try:
            result = ingest_releases(lake, season, Path(args.data), cfbd)
        except SourceError as error:  # one season's failure is reported and does not stop the others
            failed.append(season)
            print(f"{season}: FAILED, nothing written: {error}")
            continue
        print(f"{season}: new={result.new} corrected={result.corrected} unchanged={result.unchanged}")
    if failed:
        print(f"failed seasons: {failed}")
        return 1
    return 0


def _ingest_cfbd(args: argparse.Namespace) -> int:
    from cfp.common.env import load_env
    from cfp.common.timeutil import utc_now
    from cfp.ingest.cfbd import SOURCE, Cfbd
    from cfp.ingest.run import CALLS, ingest_cfbd_season
    from cfp.store.lake import Lake

    load_env()
    lake = Lake(args.lake)
    cfbd = Cfbd.from_env(lake, utc_now())
    budget = cfbd.fetcher.budget
    cfbd.sync_budget()  # the source's own count is the floor for ours
    estimate = len(args.season) * sum(CALLS[item] for item in args.what)
    print(
        f"stage {args.stage}: estimate {estimate} calls; used so far {budget.used(SOURCE)}; "
        f"allowance {cfbd.fetcher.allowance}"
    )
    with cfbd.fetcher.stage(args.stage, estimate=estimate):
        for season in args.season:
            report = ingest_cfbd_season(lake, cfbd, season, args.what)
            for result in report.results:
                print(f"  {season} {result.table}: new={result.new} corrected={result.corrected}")
            for note in report.notes:
                print(f"  NOTE {note}")
    print(f"checkpoint: stage used {budget.stage_used(SOURCE, args.stage)}; month used {budget.used(SOURCE)}")
    return 0


def _ingest_odds(args: argparse.Namespace) -> int:
    import polars as pl

    from cfp.common.env import load_env
    from cfp.ingest.cfp_releases import load_aliases
    from cfp.ingest.odds_api import MONTHLY_CREDITS, OddsApi, line_rows
    from cfp.ingest.upsert import upsert
    from cfp.store.lake import Lake

    load_env()
    lake = Lake(args.lake)
    espn = lake.scan("team_aliases").filter(pl.col("source") == "espn").collect()
    team_ids = dict(espn.select("alias", "team_id").iter_rows()) | load_aliases(
        Path(args.data) / "aliases_odds_api.csv"
    )
    api = OddsApi.from_env(lake)
    got = api.odds()
    rows, report = line_rows(got, team_ids, lake.scan("games").collect())
    result = upsert(lake, "lines", rows, got.fetched_at, "observed")
    print(f"lines: new={result.new} from {report.games} games; credits {api.used()}/{MONTHLY_CREDITS}")
    if report.in_play:
        print(f"  skipped {report.in_play} games already under way")
    for line in report.unmatched:
        print(f"  not matched: {line}")
    return 1 if report.unmatched else 0


def _snapshot(args: argparse.Namespace) -> int:
    from datetime import UTC, datetime

    import polars as pl

    from cfp.snapshot.build import build_snapshot
    from cfp.snapshot.data import load_forfeits, load_title_games, load_unplayed
    from cfp.store.lake import Lake

    cutoff = datetime.fromisoformat(args.cutoff)
    if cutoff.tzinfo is None:
        raise SystemExit("--cutoff needs a UTC offset")
    data = Path(args.data)
    view = Lake(args.lake).open_ranking_view(cutoff.astimezone(UTC), args.mode)
    result = build_snapshot(
        view,
        args.season,
        title_games=load_title_games(data / "title_games.csv"),
        forfeits=load_forfeits(data / "forfeits.csv"),
        unplayed=load_unplayed(data / "unplayed_games.csv"),
    )
    games = result.games
    print(f"snapshot {args.season} at {result.cutoff.isoformat()} ({result.mode}): {games.height} games")
    print(f"  ordinary FBS: {games['ordinary_fbs'].sum()}  title: {games['title_game'].sum()}", end="")
    latest = games.select(pl.col("start_utc").max().dt.strftime("%Y-%m-%dT%H:%MZ")).item()
    print(f"  forfeits: {games['forfeit'].sum()}  latest kickoff: {latest}")
    for reason, count in result.omissions.group_by("reason").len().sort("reason").iter_rows():
        print(f"  omitted {reason}: {count}")
    print(f"  hash {result.snapshot_hash}")
    return 0


def _markets(args: argparse.Namespace) -> int:
    from cfp.ingest.run import public_fetcher
    from cfp.markets.snapshot import (
        KALSHI,
        POLYMARKET_CLOB,
        POLYMARKET_GAMMA,
        Venues,
        history,
        load_events,
        snapshot,
    )
    from cfp.store.lake import Lake

    lake, data = Lake(args.lake), Path(args.data)
    venues = Venues(
        kalshi=public_fetcher(lake, "kalshi", KALSHI, rate=8.0),
        gamma=public_fetcher(lake, "polymarket_gamma", POLYMARKET_GAMMA, rate=4.0),
        clob=public_fetcher(lake, "polymarket_clob", POLYMARKET_CLOB, rate=8.0),
    )
    events = load_events(data / "market_events.csv")
    if args.kind == "snapshot":
        report = snapshot(lake, venues, events, data, depth=not args.no_depth)
        print(
            f"catalogue new={report.catalogue_new} changed={report.catalogue_changed}; quotes {report.quotes}"
        )
    else:
        report = history(lake, venues, events, args.hours)
        print(f"history rows: {report.quotes}")
    if report.unmapped:
        print(f"no team for {len(report.unmapped)} names: {sorted(report.unmapped)}")
    if report.empty:
        print(f"listed events that returned no contract: {report.empty}")
    return 0 if report.clean else 1


def _identity_build(args: argparse.Namespace) -> int:
    from cfp.common.env import load_env
    from cfp.common.timeutil import utc_now
    from cfp.identity.run import build_identity
    from cfp.ingest.cfbd import Cfbd
    from cfp.ingest.run import ESPN, LIVE_SEASON, public_fetcher
    from cfp.store.lake import Lake

    load_env()
    lake = Lake(args.lake)
    cfbd = Cfbd.from_env(lake, utc_now())
    espn = public_fetcher(lake, "espn", ESPN).get("/teams", {"limit": 1000, "groups": 80}, reuse=True)
    seasons = list(range(FIRST_SEASON, LIVE_SEASON + 1))
    report = build_identity(lake, cfbd, Path(args.data), seasons, espn)
    for result in report.results:
        if result.new or result.corrected:
            print(f"  {result.table}: new={result.new} corrected={result.corrected}")
    for line in report.unconfirmed_espn:
        print(f"  ESPN id not confirmed, left empty: {line}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
    elif args.command == "ingest" and args.kind == "releases":
        return _ingest_releases(args)
    elif args.command == "ingest" and args.kind == "odds":
        return _ingest_odds(args)
    elif args.command == "ingest" and args.kind == "cfbd":
        return _ingest_cfbd(args)
    elif args.command == "snapshot":
        return _snapshot(args)
    elif args.command == "markets":
        return _markets(args)
    elif args.command == "identity":
        return _identity_build(args)
    elif args.command == "budget":
        path = Path(args.lake) / "budget.json"
        print(json.dumps(json.loads(path.read_text()) if path.is_file() else {}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
