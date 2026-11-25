"""Command-line entry point. Subcommands are added by later build prompts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Callable, Sequence
from datetime import date, datetime
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
    others = kinds.add_parser("ap-others", help="AP votes for teams outside the top 25, from ESPN")
    others.add_argument("--season", type=int, required=True)
    others.add_argument("--weeks", type=int, nargs="+", default=[], help="ESPN week numbers")
    others.add_argument("--current", action="store_true", help="also read ESPN's current poll")

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

    forecast = commands.add_parser("forecast", help="Open Ranking Models: forecast issues")
    forecast_kinds = forecast.add_subparsers(dest="kind", metavar="<action>", required=True)
    draw = forecast_kinds.add_parser("draw", help="write the season's tiebreak draw to the data directory")
    draw.add_argument("--season", type=int, required=True)
    due = forecast_kinds.add_parser("due", help="print the issue due now, its reveal date and cutoff, if any")
    due.add_argument("--season", type=int, required=True)
    due.add_argument("--now", help="frozen clock, for tests")
    issue = forecast_kinds.add_parser("issue", help="build, write and prove one forecast issue")
    issue.add_argument("--season", type=int, required=True)
    issue.add_argument("--issue", choices=["sun0200", "tminus60"], required=True)
    issue.add_argument("--reveal", required=True, help="date of the committee show, YYYY-MM-DD")
    issue.add_argument("--mode", choices=["live", "replay"], default="live")
    issue.add_argument("--revision", type=int, default=1, help="a correction is a new edition: 2, 3, ...")
    issue.add_argument("--no-proof", action="store_true", help="skip the timestamp token and the signed tag")
    issue.add_argument("--push", action="store_true", help="push the signed tag to origin")
    issue.add_argument(
        "--now", help="dry run at a frozen time: separate edition ID, never scored; needs --no-proof"
    )
    issue.add_argument("--frozen", default="frozen", help="frozen-parameters directory (for open points)")
    issue.add_argument(
        "--allow-unresolved",
        action="store_true",
        help="issue even if games that should be final are still scheduled, and list them in the edition",
    )

    ranking = commands.add_parser("open-ranking", help="Open Ranking editions")
    ranking_kinds = ranking.add_subparsers(dest="kind", metavar="<action>", required=True)
    build = ranking_kinds.add_parser("build", help="build one edition and write it once")
    build.add_argument("--season", type=int, required=True)
    build.add_argument("--cutoff", required=True, help="ISO time with a UTC offset; nothing later is read")
    build.add_argument("--mode", choices=("live", "replay"), default="live")
    build.add_argument("--revision", type=int, default=1)
    build.add_argument("--previous", help="edition to measure revisions against; 'none' for no comparison")
    build.add_argument(
        "--corrected-as-of",
        help="for --revision 2+: re-read the superseded edition's games as public at this later time",
    )
    build.add_argument("--frozen", default="frozen", help="frozen-parameters directory")

    calibrate = commands.add_parser(
        "calibrate", help="Open Ranking link scale and penalties (game results only)"
    )
    calibrate_kinds = calibrate.add_subparsers(dest="kind", metavar="<action>", required=True)
    for name, text in (
        ("report", "search the grid on earlier seasons and print the result (writes nothing)"),
        ("freeze", "search, then write the season's frozen parameters once"),
    ):
        action = calibrate_kinds.add_parser(name, help=text)
        action.add_argument("--season", type=int, required=True, help="the season the parameters are for")
        action.add_argument("--first-training-season", type=int, default=2015)
        action.add_argument("--frozen", default="frozen", help="frozen-parameters directory")

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


def _ingest_ap_others(args: argparse.Namespace) -> int:
    import polars as pl

    from cfp.ingest.errors import SourceError
    from cfp.ingest.espn_polls import others_rows
    from cfp.ingest.run import ESPN, LIVE_SEASON, public_fetcher
    from cfp.ingest.upsert import upsert
    from cfp.store.lake import Lake

    lake = Lake(args.lake)
    espn = public_fetcher(lake, "espn", ESPN)
    teams = lake.scan("teams").filter(pl.col("espn_id").is_not_null()).collect()
    latest = teams.sort("correction_version").unique("team_id", keep="last")
    by_espn = dict(latest.select("espn_id", "team_id").iter_rows())
    stored = lake.scan("polls").filter((pl.col("season") == args.season) & (pl.col("poll") == "ap")).collect()
    stored = stored.sort("correction_version").unique(["week", "team_id"], keep="last")
    live = args.season == LIVE_SEASON
    failed = False
    queries: list[tuple[str, dict[str, object]]] = [
        (f"ESPN week {week}", {"seasons": args.season, "types": 2, "weeks": week}) for week in args.weeks
    ]
    if args.current:
        queries.append(("ESPN current poll", {}))
    if not queries:
        print("nothing to do: give --weeks or --current", file=sys.stderr)
        return 2
    for label, query in queries:
        got = espn.get("/rankings", query, reuse=not live)
        try:
            rows = others_rows(got, stored, by_espn, live)
        except SourceError as error:
            failed = True
            print(f"{label}: FAILED, nothing written: {error}")
            continue
        result = upsert(lake, "polls", rows, got.fetched_at, "observed" if live else "asserted")
        print(
            f"{label} -> AP week {rows['week'][0]}: {rows.height} teams with votes; "
            f"new={result.new} corrected={result.corrected} unchanged={result.unchanged}"
        )
    return 1 if failed else 0


def _forecast_draw(args: argparse.Namespace) -> int:
    from datetime import date

    import polars as pl

    from cfp.common.draw import PHRASE, draw_positions
    from cfp.common.timeutil import utc_now
    from cfp.forecast.observations import fbs_field
    from cfp.store.lake import Lake

    lake = Lake(args.lake)
    path = Path(args.data) / f"preseason_draw_{args.season}.csv"
    if path.exists():
        print(f"{path} already exists; a published draw is not redrawn", file=sys.stderr)
        return 1
    now = utc_now()
    membership = lake.as_of("membership", now, "replay").frame
    none = pl.DataFrame(schema={"season": pl.Int32, "team_id": pl.String, "cfp_eligible": pl.Boolean})
    field = fbs_field(membership, none, args.season, date(args.season, 11, 1))
    names = dict(lake.as_of("teams", now, "replay").frame.select("team_id", "name").iter_rows())
    phrase = PHRASE.format(season=args.season)
    positions = draw_positions(field["team_id"].to_list(), phrase)
    lines = [f'{args.season},{place},{team},"{names[team]}"\n' for team, place in positions.items()]
    path.write_text("season,position,team_id,name\n" + "".join(lines))
    print(f"{path}: {len(lines)} teams drawn from the phrase {phrase!r}")
    return 0


EXIT_EXISTS = 17  # the edition is already written
EXIT_TOO_EARLY = 75  # the cutoff has not passed; try again
EXIT_UNRESOLVED = 18  # results look stale: games that should be final are still scheduled
TOKEN_ATTEMPTS = 3


def _forecast_due(args: argparse.Namespace) -> int:
    from datetime import datetime

    from cfp.common.timeutil import require_utc, utc_now
    from cfp.forecast.cutoffs import ET, issue_time
    from cfp.ingest.cfp_releases import load_schedule
    from cfp.release.issue import due_issue

    now = require_utc(datetime.fromisoformat(args.now), "--now") if args.now else utc_now()
    schedule = load_schedule(Path(args.data) / "cfp_reveals.csv")
    shows = [reveal.show_start for day, reveal in schedule.items() if day.year == args.season]
    due = due_issue(shows, now)
    if due is None:
        return 0
    issue, reveal = due
    cutoff = issue_time(issue, reveal)
    print(f"{issue} {reveal.astimezone(ET).date().isoformat()} {int(cutoff.timestamp())}")
    return 0


def _code_hash() -> str:
    import subprocess

    try:
        git = ["git", "-C", str(Path(__file__).resolve().parent)]  # this code's repository, not the caller's
        head = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        dirty = subprocess.run([*git, "status", "--porcelain"], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return head.stdout.strip() + ("-dirty" if dirty.stdout.strip() else "")


def _forecast_issue(args: argparse.Namespace, clock: Callable[[], datetime] | None = None) -> int:
    import subprocess

    import polars as pl

    from cfp.common.draw import load_draw
    from cfp.common.timeutil import require_utc, utc_now
    from cfp.ingest.cfp_releases import load_schedule
    from cfp.ingest.upsert import upsert
    from cfp.release import proof
    from cfp.release.edition import EditionExists, write_edition
    from cfp.release.issue import PRODUCT, RULE_VERSION, IssueRefused, TooEarly, Unresolved, build_issue
    from cfp.store.lake import Lake
    from cfp.store.schemas import TABLES

    if args.now and not args.no_proof:
        print("--now is a dry run and cannot be combined with a proof", file=sys.stderr)
        return 2
    dry = bool(args.now)
    clock = clock or utc_now
    now = require_utc(datetime.fromisoformat(args.now), "--now") if dry else clock()
    lake = Lake(args.lake, clock=clock)
    data = Path(args.data)
    schedule = load_schedule(data / "cfp_reveals.csv")
    shows = {day: reveal.show_start for day, reveal in schedule.items() if day.year == args.season}
    day = date.fromisoformat(args.reveal)
    if day not in shows:
        print(f"refused: {day} is not a sourced reveal date for {args.season}", file=sys.stderr)
        return 1
    frozen, lists, note = None, None, None
    try:  # open points (SC-04a); without them the issue still goes out and says so
        from cfp.open_ranking.frozen import FrozenError, load_frozen
        from cfp.snapshot.data import load_forfeits, load_title_games, load_unplayed

        frozen = load_frozen(args.frozen, args.season)
        lists = {
            "title_games": load_title_games(data / "title_games.csv"),
            "forfeits": load_forfeits(data / "forfeits.csv"),
            "unplayed": load_unplayed(data / "unplayed_games.csv"),
        }
    except (FrozenError, OSError, ValueError) as error:
        frozen, lists, note = None, None, f"{type(error).__name__}: {error}"
    try:
        built = build_issue(
            lake,
            season=args.season,
            issue=args.issue,
            reveal=shows[day],
            reveals=list(shows.values()),
            mode=args.mode,
            now=now,
            code_hash=_code_hash(),
            draw=load_draw(data / f"preseason_draw_{args.season}.csv", args.season),
            revision=args.revision,
            dry_run=dry,
            allow_unresolved=args.allow_unresolved,
            frozen=frozen,
            lists=lists,
            open_points_note=note,
        )
    except TooEarly as error:
        print(str(error), file=sys.stderr)
        return EXIT_TOO_EARLY
    except Unresolved as error:
        print(str(error), file=sys.stderr)
        return EXIT_UNRESOLVED
    except (IssueRefused, OSError, ValueError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    if built.doc["open_points_error"]:
        print(f"WARNING: open points are missing: {built.doc['open_points_error']}", file=sys.stderr)
    folder = lake.root / "editions"
    superseded = built.doc["supersedes"]
    if superseded and not (folder / superseded).is_dir():
        print(
            f"refused: revision {args.revision} would supersede {superseded}, which does not exist",
            file=sys.stderr,
        )
        return 1

    def record() -> None:
        """Append the editions row unless it is there already (a dry run records nothing)."""
        if dry:
            return
        held = lake.scan("editions").filter(pl.col("edition_id") == built.edition_id).collect()
        if held.height:
            return
        body = (folder / built.edition_id / "edition.json").read_bytes()
        issued = require_utc(
            datetime.fromisoformat(
                json.loads((folder / built.edition_id / "receipt.json").read_text())["issued_utc"]
            ),
            "issued_utc",
        )
        doc = json.loads(body)
        row = {
            "edition_id": built.edition_id,
            "season": args.season,
            "product": PRODUCT,
            "issue_utc": built.cutoff,
            "input_ids": doc["inputs"],
            "seed": None,
            "code_hash": doc["code_hash"],
            "rule_version_id": RULE_VERSION,
            "sha256": hashlib.sha256(body).hexdigest(),
            "source_id": "cfp:forecast issue",
            "event_time": built.cutoff,
            "first_public_time": issued,
            "raw_hash": lake.put_raw(body),
            "vintage": "live" if args.mode == "live" else "reconstructed",
        }
        keep = ("correction_version", "ingest_time")
        schema = {k: v for k, v in TABLES["editions"].schema.items() if k not in keep}
        upsert(lake, "editions", pl.DataFrame([row], schema=schema), clock(), "asserted")

    if (folder / built.edition_id).exists():
        record()  # repairs a run that died between writing the folder and recording it
        print(f"edition {built.edition_id} already exists; use --revision for a correction", file=sys.stderr)
        return EXIT_EXISTS
    receipt: dict[str, object] = {
        "edition_id": built.edition_id,
        "sha256": built.sha256,
        "issued_utc": now.isoformat(),
        "dry_run": dry,
        "tag_name": None if args.no_proof else proof.tag_name(built.edition_id),
        "timestamp_authority": None,
    }
    extra: dict[str, bytes] = {}
    problems: list[str] = []
    if not args.no_proof:
        for attempt in range(TOKEN_ATTEMPTS):
            try:
                token, authority = proof.request_token(built.sha256)
            except proof.ProofError as error:
                if attempt + 1 == TOKEN_ATTEMPTS:
                    problems.append(str(error))
                else:
                    time.sleep(5)
            else:
                extra["timestamp.tsr"] = token
                receipt["timestamp_authority"] = authority
                break
    try:
        where = write_edition(folder, built.edition_id, built.body, receipt, extra)
    except EditionExists as error:
        print(str(error), file=sys.stderr)
        return EXIT_EXISTS
    record()
    if not args.no_proof:
        for command in proof.tag_commands(built.edition_id, built.sha256, args.push):
            try:
                done = subprocess.run(command, capture_output=True, text=True, check=False, timeout=90)
            except subprocess.TimeoutExpired:
                problems.append(f"{' '.join(command[:3])} timed out")
                break
            if done.returncode != 0:
                problems.append(f"{' '.join(command[:3])} failed: {done.stderr.strip()[:200]}")
                break
    top = built.doc["forecasts"][built.doc["headline_forecast"]]["rows"][:25]
    print(f"edition {built.edition_id} written to {where}")
    print(f"  eligible for prospective scoring: {built.doc['prospective_eligible']}")
    print(f"  not available at this issue: {', '.join(built.doc['missing_inputs'])}")
    if built.doc["unresolved_games"]:
        print(f"  games still listed as scheduled: {', '.join(built.doc['unresolved_games'])}")
    for placed in top:
        print(f"  {placed['position']:>2}. {placed['name']}")
    print()
    print(proof.post_text(built.edition_id, built.sha256, built.cutoff, built.reveal))
    for problem in problems:
        print(f"PROOF INCOMPLETE: {problem}", file=sys.stderr)
    return 3 if problems else 0


def _open_ranking_build(args: argparse.Namespace, clock: Callable[[], datetime] | None = None) -> int:
    import re
    from datetime import UTC

    import polars as pl

    from cfp.common.draw import load_draw
    from cfp.common.timeutil import require_utc, utc_now
    from cfp.ingest import upsert as ingest
    from cfp.open_ranking.frozen import FrozenError, load_frozen
    from cfp.open_ranking.release import PRODUCT, ReleaseError, build_edition, load_built
    from cfp.release.edition import EditionExists, write_edition
    from cfp.snapshot.build import SnapshotBlocked, build_snapshot, restrict
    from cfp.snapshot.data import load_forfeits, load_title_games, load_unplayed
    from cfp.store.lake import Lake
    from cfp.store.schemas import TABLES

    clock = clock or utc_now
    now = clock()
    times = {}
    for flag, text in (("--cutoff", args.cutoff), ("--corrected-as-of", args.corrected_as_of)):
        if text is None:
            continue
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            moment = None
        if moment is None or moment.tzinfo is None:
            print(f"{flag} needs an ISO time with a UTC offset", file=sys.stderr)
            return 2
        times[flag] = moment.astimezone(UTC)
    cutoff = times["--cutoff"]
    read_at = times.get("--corrected-as-of", cutoff)
    if read_at > now:
        print(f"refused: {read_at.isoformat()} has not passed", file=sys.stderr)
        return 1
    data, lake = Path(args.data), Lake(args.lake, clock=clock)
    folder = lake.root / "editions"
    live = args.mode == "live"
    tail = "" if live else "-replay"
    name = re.compile(rf"^or-{args.season}-(\d{{8}}t\d{{4}}z){tail}-e(\d+)$")
    stamp = cutoff.strftime("%Y%m%dt%H%Mz")

    def record(edition_id: str) -> None:
        """Append the editions row from the folder's own bytes, unless it is there already."""
        if lake.scan("editions").filter(pl.col("edition_id") == edition_id).collect().height:
            return
        body = (folder / edition_id / "edition.json").read_bytes()
        doc = json.loads(body)
        receipt = json.loads((folder / edition_id / "receipt.json").read_text())
        row = {
            "edition_id": edition_id,
            "season": doc["season"],
            "product": PRODUCT,
            "issue_utc": require_utc(datetime.fromisoformat(doc["cutoff_utc"]), "cutoff_utc"),
            "input_ids": doc["inputs"],
            "seed": None,
            "code_hash": doc["manifest"]["code_hash"],
            "rule_version_id": doc["manifest"]["rule_version_id"],
            "sha256": hashlib.sha256(body).hexdigest(),
            "source_id": "cfp:open-ranking build",
            "event_time": require_utc(datetime.fromisoformat(doc["data_as_of_utc"]), "data_as_of_utc"),
            "first_public_time": require_utc(datetime.fromisoformat(receipt["issued_utc"]), "issued_utc"),
            "raw_hash": lake.put_raw(body),
            "vintage": "live" if doc["mode"] == "live" else "reconstructed",
        }
        keep = ("correction_version", "ingest_time")
        schema = {k: v for k, v in TABLES["editions"].schema.items() if k not in keep}
        ingest.upsert(lake, "editions", pl.DataFrame([row], schema=schema), clock(), "asserted")

    try:
        previous = None
        if args.previous != "none":
            chosen = args.previous
            if chosen is None and folder.is_dir():  # the latest earlier edition of the same kind
                held = [
                    (m.group(1), int(m.group(2)), p.name)
                    for p in folder.iterdir()
                    if (m := name.match(p.name))
                ]
                earlier = sorted(item for item in held if item[0] < stamp)
                chosen = earlier[-1][2] if earlier else None
            if chosen is not None:
                previous = load_built((folder / chosen / "edition.json").read_bytes())
        snapshot = build_snapshot(
            lake.open_ranking_view(read_at, args.mode),
            args.season,
            title_games=load_title_games(data / "title_games.csv"),
            forfeits=load_forfeits(data / "forfeits.csv"),
            unplayed=load_unplayed(data / "unplayed_games.csv"),
        )
        superseded = f"or-{args.season}-{stamp}{tail}-e{args.revision - 1}" if args.revision > 1 else None
        if superseded and not (folder / superseded).is_dir():
            raise ReleaseError(f"revision {args.revision} would supersede {superseded}, which does not exist")
        if read_at > cutoff:  # a correction: the superseded edition's games, as they read now
            if not superseded:
                raise ReleaseError("a correction is a new revision of the edition it supersedes")
            old = load_built((folder / superseded / "edition.json").read_bytes())
            snapshot = restrict(snapshot, {r["game_id"] for t in old.doc["teams"] for r in t["rows"]})
        built = build_edition(
            snapshot,
            load_frozen(args.frozen, args.season),
            load_draw(data / f"preseason_draw_{args.season}.csv", args.season),
            code_hash=_code_hash(),
            revision=args.revision,
            previous=previous,
            cutoff=cutoff,
        )
    except (ReleaseError, FrozenError, SnapshotBlocked, OSError, ValueError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    receipt = {"edition_id": built.edition_id, "product": PRODUCT, "sha256": built.sha256}
    try:
        write_edition(
            folder,
            built.edition_id,
            built.body,
            receipt | {"issued_utc": now.isoformat()},
            {"games.jsonl": built.games_file},
        )
    except EditionExists as error:
        record(built.edition_id)  # repairs a run that wrote the folder and died before the table row
        print(str(error), file=sys.stderr)
        return EXIT_EXISTS
    record(built.edition_id)
    manifest = built.doc["manifest"]
    print(f"edition {built.edition_id}  sha256 {built.sha256}")
    print(f"  games {manifest['games']}  teams {len(built.doc['teams'])}")
    print(f"  rows on a rounding boundary: {manifest['boundary_rows']}")
    print(f"  measured against: {previous.edition_id if previous else 'nothing'}")
    print("  second implementation: not run")
    return 0


def _calibrate(args: argparse.Namespace) -> int:
    from datetime import UTC

    from cfp.open_ranking import RULE_VERSION_ID
    from cfp.open_ranking.calibration import DEFAULT_GRID, FIRST_WEEK, report, search, venue_only
    from cfp.open_ranking.frozen import FrozenError, write_frozen
    from cfp.snapshot.build import build_snapshot
    from cfp.snapshot.data import load_forfeits, load_title_games, load_unplayed
    from cfp.store.lake import Lake

    data, lake = Path(args.data), Lake(args.lake)
    years = list(range(args.first_training_season, args.season))
    if len(years) < 3:
        print("refused: calibration needs at least three earlier seasons", file=sys.stderr)
        return 1
    titles = load_title_games(data / "title_games.csv")
    forfeits = load_forfeits(data / "forfeits.csv")
    unplayed = load_unplayed(data / "unplayed_games.csv")
    games, hashes = {}, {}
    for year in years:  # each finished season as it stood on 1 Feb of the next year
        view = lake.open_ranking_view(datetime(year + 1, 2, 1, 5, 0, tzinfo=UTC), "replay")
        snapshot = build_snapshot(view, year, title_games=titles, forfeits=forfeits, unplayed=unplayed)
        games[year], hashes[str(year)] = snapshot.games, snapshot.snapshot_hash
    found = search(games, DEFAULT_GRID, FIRST_WEEK)
    choice = found.choose(years)
    flat_ll, flat_brier = venue_only(found.predictions(choice.params, years))
    rolling = report(found, years[3:])
    print(
        f"calibration for {args.season} on {years[0]}-{years[-1]}, games from week {FIRST_WEEK}, n={choice.n}"
    )
    print(f"  lambda_c={choice.params.lambda_c}  lambda_u={choice.params.lambda_u}  t={choice.t}")
    print(f"  log loss {choice.log_loss:.4f} (venue only {flat_ll:.4f})")
    print(f"  Brier {choice.brier:.4f} (venue only {flat_brier:.4f})")
    if choice.at_grid_edge:
        print(f"  WARNING: on the edge of the grid: {', '.join(choice.at_grid_edge)}")
    print("  out of sample (parameters chosen on earlier seasons only):")
    for row in rolling["rolling"]:
        print(
            f"    {row['season']}: n={row['n']} log loss {row['log_loss']:.4f} "
            f"(venue only {row['venue_only_log_loss']:.4f}) t={row['t']}"
        )
    print("  reliability, out of sample (predicted -> observed home win rate):")
    for row in rolling["reliability"]:
        if row["n"]:
            print(f"    {row['bin']}: n={row['n']} {row['mean_predicted']:.3f} -> {row['home_win_rate']:.3f}")
    if args.kind != "freeze":
        return 0
    if choice.at_grid_edge:
        print("refused: the chosen point is on the edge of the grid; widen the grid first", file=sys.stderr)
        return 1

    def tidy(value: object) -> object:
        return round(value, 6) if isinstance(value, float) else value

    document = {
        "season": args.season,
        "status": "provisional",
        "rule_version_id": RULE_VERSION_ID,
        "lambda_c": choice.params.lambda_c,
        "lambda_u": choice.params.lambda_u,
        "t": choice.t,
        "cap": choice.params.cap,
        "independent_penalty": choice.params.independent_penalty,
        "objective": "pooled log loss of rolling pregame predictions of FBS-v-FBS results",
        "inputs_used": "game results only; no committee ranking, poll or betting line",
        "trained_on": years,
        "first_week": FIRST_WEEK,
        "n_games": choice.n,
        "log_loss": tidy(choice.log_loss),
        "brier": tidy(choice.brier),
        "venue_only_log_loss": tidy(flat_ll),
        "venue_only_brier": tidy(flat_brier),
        "grid": {"lambda_c": DEFAULT_GRID.lambda_c, "lambda_u": DEFAULT_GRID.lambda_u, "t": DEFAULT_GRID.t},
        "out_of_sample": [{k: tidy(v) for k, v in row.items()} for row in rolling["rolling"]],
        "reliability": [{k: tidy(v) for k, v in row.items()} for row in rolling["reliability"]],
        "snapshot_hashes": hashes,
        "code_hash": _code_hash(),
        "not_done": ["closing-line comparison", "leave-one-game-out diagnostic", "public adoption review"],
    }
    try:
        path, digest = write_frozen(args.frozen, args.season, document)
    except FrozenError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    print(f"frozen: {path}  sha256 {digest}")
    return 0


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
    elif args.command == "ingest" and args.kind == "ap-others":
        return _ingest_ap_others(args)
    elif args.command == "forecast" and args.kind == "draw":
        return _forecast_draw(args)
    elif args.command == "forecast" and args.kind == "due":
        return _forecast_due(args)
    elif args.command == "forecast" and args.kind == "issue":
        return _forecast_issue(args)
    elif args.command == "ingest" and args.kind == "cfbd":
        return _ingest_cfbd(args)
    elif args.command == "open-ranking":
        return _open_ranking_build(args)
    elif args.command == "calibrate":
        return _calibrate(args)
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
