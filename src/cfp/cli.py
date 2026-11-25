"""Command-line entry point. Subcommands are added by later build prompts."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cfp import __version__


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

    commands.add_parser("budget", help="show API calls used this month")
    return parser


def _ingest_releases(args: argparse.Namespace) -> int:
    from cfp.common.env import load_env
    from cfp.common.timeutil import utc_now
    from cfp.ingest.cfbd import Cfbd
    from cfp.ingest.run import LIVE_SEASON, ingest_releases
    from cfp.store.lake import Lake

    load_env()
    lake = Lake(args.lake)
    for season in args.season:
        cfbd = None
        if season < LIVE_SEASON:
            cfbd = Cfbd.from_env(lake, utc_now())
            cfbd.sync_budget()
        result = ingest_releases(lake, season, Path(args.data), cfbd)
        print(f"{season}: new={result.new} corrected={result.corrected} unchanged={result.unchanged}")
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
    elif args.command == "ingest" and args.kind == "releases":
        return _ingest_releases(args)
    elif args.command == "ingest" and args.kind == "cfbd":
        return _ingest_cfbd(args)
    elif args.command == "budget":
        path = Path(args.lake) / "budget.json"
        print(json.dumps(json.loads(path.read_text()) if path.is_file() else {}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
