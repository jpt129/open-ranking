"""The public page for one Open Ranking edition: one self-contained HTML file.

Everything shown is read from the edition document and the gate report, except team names, which come from
the store's teams table when the page is first written. Points are shown to two decimals;
the whole centipoints in edition.json are the record. If the edition's sensitivity file was written and the
gate's rerun of it matched, its numbers are shown too; otherwise sensitivity is listed as not delivered.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from html import escape
from typing import Any, Final
from zoneinfo import ZoneInfo

EASTERN: Final = ZoneInfo("America/New_York")
SENSITIVITY: Final = "Sensitivity intervals"
SHOWN: Final = 40  # sensitivity rows on the page: the top 40, and anyone else who reached the field
NOT_DELIVERED: Final = (
    (SENSITIVITY, "how far each team's rank moves when the strength fit is re-weighted"),
    ("Rank-reversal report", "the published list of rank reversals"),
    ("What-if tool", "flip a result and regenerate every ledger and the bracket"),
    ("Calibration report", "how well the win probabilities behind the ledger matched results"),
    ("Bracket", "the field and seeds this ranking would produce"),
)
STYLE: Final = """
:root{--bg:#fff;--fg:#16181d;--mute:#5b6270;--line:#d9dde3;--soft:#f4f5f7;--good:#0b6b3a;--bad:#a12622}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#14161a;--fg:#e8eaee;--mute:#9aa2b1;
--line:#2c313a;--soft:#1c1f25;--good:#5fd08f;--bad:#ff8a84}}
:root[data-theme="dark"]{--bg:#14161a;--fg:#e8eaee;--mute:#9aa2b1;--line:#2c313a;--soft:#1c1f25;
--good:#5fd08f;--bad:#ff8a84}
body{background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px}
main{max-width:920px;margin:0 auto}h1{margin:0 0 4px}h2{margin:32px 0 8px;font-size:1.15rem}
p,li{max-width:70ch}.mute{color:var(--mute)}code{font-size:.85em;word-break:break-all}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
td.n,th.n{text-align:right}.wrap{overflow-x:auto}
details{border-bottom:1px solid var(--line)}summary{cursor:pointer;padding:8px 4px;display:flex;gap:12px}
summary .r{width:2.5em;color:var(--mute)}summary .t{flex:1}summary .p{font-variant-numeric:tabular-nums}
details table{background:var(--soft);font-size:.9rem;margin-bottom:8px}
.pos{color:var(--good)}.neg{color:var(--bad)}.box{background:var(--soft);padding:12px 16px;border-radius:6px}
"""


def _points(cp: int) -> str:
    return f"{cp / 100:+.2f}"


def _signed(cp: int) -> str:
    return f'<span class="{"pos" if cp > 0 else "neg" if cp < 0 else ""}">{_points(cp)}</span>'


def _when(text: str) -> str:
    moment = datetime.fromisoformat(text).astimezone(EASTERN)
    return f"{moment:%a} {moment.day} {moment:%b %Y %H:%M} ET"


def _row(row: Mapping[str, Any], names: Mapping[str, str]) -> str:
    where = {"home": "home", "away": "away", "neutral": "neutral"}.get(row["site"], str(row["site"]))
    chance = "" if row["q"] is None else f"{row['q'] / 100:.2f}%"
    change = "" if row.get("revision_cp") is None else _signed(row["revision_cp"])
    note = []
    if row["title_game"]:
        note.append("title game")
    if row["policy_exception"]:
        note.append(str(row["policy_exception"]).replace("_", " "))
    if row["boundary"]:
        note.append("rounding boundary")
    return (
        f"<tr><td>{escape(str(row['week']))}</td>"
        f"<td>{escape(names.get(row['opponent_id'], row['opponent_id']))}</td>"
        f"<td>{escape(where)}</td><td>{escape(str(row['result']))}</td><td class=n>{chance}</td>"
        f"<td class=n>{_signed(row['points_cp'])}</td><td class=n>{change}</td>"
        f"<td>{escape(', '.join(note))}</td></tr>"
    )


def _team(team: Mapping[str, Any], names: Mapping[str, str]) -> str:
    rows = "".join(_row(row, names) for row in team["rows"])
    decided = f" · head-to-head: {escape(str(team['head_to_head']))}" if team.get("head_to_head") else ""
    decided += f" · raw rank {int(team['raw_rank'])}"
    return (
        f"<details><summary><span class=r>{team['open_rank']}</span>"
        f"<span class=t>{escape(names.get(team['team_id'], team['team_id']))} "
        f"<span class=mute>{team['wins']}-{team['losses']}{decided}</span></span>"
        f"<span class=p>{_signed(team['total_cp'])}</span></summary>"
        "<div class=wrap><table><tr><th>Wk</th><th>Opponent</th><th>Site</th><th>Result</th>"
        "<th class=n>Bubble team's chance</th><th class=n>Points</th>"
        "<th class=n>Change since last edition</th><th>Note</th></tr>"
        f"{rows}</table></div></details>"
    )


def _route(row: Mapping[str, Any], scenario: Mapping[str, Any], refits: int) -> str:
    """How the team is in the published field, in words, so that a margin is not read as in or out."""
    route = row["route_as_published"]
    other = row["qualifies"] - row["qualifies_at_large"]
    some = f"in other than at large in {100 * other / refits:.1f}% of refits" if other else ""
    if route is None:
        return f"not in; {some}" if some else ""
    if route == "auto:group":
        return "place for the best of the other conferences"
    if route.startswith("auto:"):
        return "champion (stand-in)" if route[5:] in scenario["stand_ins"] else "champion"
    if route == "guarantee":
        return "guarantee in the season's rules"
    return f"at large; {some}" if some else "at large"


def _share(row: Mapping[str, Any], scenario: Mapping[str, Any], refits: int) -> str:
    """Share of refits in the field. A stand-in champion is in every refit by assumption, not as a result."""
    route = row["route_as_published"] or ""
    if route.startswith("auto:") and route[5:] in scenario["stand_ins"]:
        return "assumed"
    return f"{100 * row['qualifies'] / refits:.1f}%"


def _sensitivity(report: Mapping[str, Any], names: Mapping[str, str]) -> str:
    """The section for a sensitivity report whose refits the gate reran."""
    refits = int(report["refits"])
    scenario = report["scenario"]
    where = report["environment"]
    rows = []
    for row in report["teams"]:
        if row["open_rank"] > SHOWN and not row["qualifies"]:
            continue
        low, high = row["cut_margin_cp_80"]
        first, last = row["rank_80"]
        rows.append(
            f"<tr><td>{row['open_rank']}</td><td>{escape(names.get(row['team_id'], row['team_id']))}</td>"
            f"<td class=n>{first} to {last}</td><td class=n>{_signed(row['cut_margin_cp'])}</td>"
            f"<td class=n>{_points(low)} to {_points(high)}</td>"
            f"<td class=n>{_share(row, scenario, refits)}</td>"
            f"<td>{escape(_route(row, scenario, refits))}</td></tr>"
        )
    fixed = scenario["champions"] | scenario["stand_ins"]
    held = "; ".join(
        f"{escape(str(league))}: {escape(names.get(team, team))}"
        + (" (stand-in)" if league in scenario["stand_ins"] else "")
        for league, team in sorted(fixed.items())
    )
    return f"""<h2>Sensitivity to the observed games</h2>
<p>{escape(str(report["label"]))}</p>
<p>Results are held fixed. In each of {refits} refits every game gets a random weight (exponential, mean
one) in the strength fit, the same weight in every team's fold. The bubble level, every ledger and the
bracket are then worked again. Each range below is the middle 80% of refits.</p>
<p><b>Cut line.</b> {escape(str(report["cut_line"]["definition"]))} It is the at-large line only: a team
marked in the last column as in by a champion's place, the other conferences' place or a guarantee is in the
field whatever its margin, and a negative margin for such a team does not mean it is out. A team ruled
ineligible is out above the line.</p>
<p><b>Bracket scenario.</b> {escape(str(scenario["note"]))} Champions used in every refit:
{held or "none"}.</p>
<div class=wrap><table><tr><th>Rank</th><th>Team</th><th class=n>Rank range</th>
<th class=n>Margin to cut line</th><th class=n>Margin range</th><th class=n>In the field</th>
<th>In by</th></tr>
{"".join(rows)}</table></div>
<p class=mute>"Assumed" marks a stand-in champion: its place is an input to the scenario, not a result.
The top {SHOWN} teams and any other team that reached the field in a refit. Every team is in
<a href="sensitivity.json">sensitivity.json</a>, with the seed (<code>{report["seed"]}</code>) and a digest
of each refit.</p>
<p class=mute>Reproducible in the recorded environment: {escape(where["os"])}, {escape(where["python"])},
numpy {escape(where["numpy"])}, polars {escape(where["polars"])}, BLAS {escape(where["blas"])}. The same
refits have not been tested on other systems.</p>
"""


def render(
    doc: Mapping[str, Any],
    names: Mapping[str, str],
    gate: Mapping[str, Any],
    sha256: str,
    sensitivity: Mapping[str, Any] | None = None,
) -> str:
    """The page for one edition. `gate` is the gate report's document."""
    manifest = doc["manifest"]
    params = manifest["params"]
    replay = "" if doc["mode"] == "live" else " This is a replay edition, built after the fact."
    correction = f" It supersedes {escape(doc['supersedes'])}." if doc.get("supersedes") else ""
    missing = "".join(
        f"<li><b>{escape(name)}</b> ({escape(what)}): not delivered in the pilot.</li>"
        for name, what in NOT_DELIVERED
        if not (sensitivity is not None and name == SENSITIVITY)
    )
    measured = _sensitivity(sensitivity, names) if sensitivity is not None else ""
    checks = "".join(
        f"<tr><td>{'pass' if check['passed'] else 'FAIL'}</td><td>{escape(check['name'])}</td>"
        f"<td>{escape(check['detail'])}</td></tr>"
        for check in gate["checks"]
    )
    teams = "".join(_team(team, names) for team in doc["teams"])
    reproduced = (
        "Independent code reproduced these numbers."
        if manifest["second_implementation"] == "match"
        else "The numbers have not yet been reproduced by independent code."
    )
    omitted = (
        ", ".join(f"{count} {escape(reason)}" for reason, count in manifest["omissions"].items()) or "none"
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Open Ranking</title><style>{STYLE}</style></head><body><main>
<h1>Open Ranking</h1>
<p class=mute>{doc["season"]} season · results through {_when(doc["cutoff_utc"])} · edition
<code>{escape(doc["edition_id"])}</code>.{replay}{correction}</p>
<p>Each game is scored against what a team at the playoff cut line would be expected to do in that same
game. 100 points is one win. A win earns 100 minus the bubble team's chance of winning it; a loss costs the
bubble team's chance of winning it. A win over an FCS team earns 0 and a loss to one costs 99. A team's own
margins never change its total. Polls, committee rankings and betting lines are never read.</p>
<p>The ranking reads three tables: games, teams and conference membership. The games carry three hand-verified
annotation lists, each row with its source. <code>title_games.csv</code> names the conference title games:
it marks them, and it keeps one that the source files with the postseason from being left out with the bowls.
A title game is scored like any other game. <code>forfeits.csv</code> records forfeits made public by the
cutoff: the certified result is scored as a normal win or loss, its margin is left out of the strength fit,
and the game is left out of the head-to-head tiebreak. <code>unplayed_games.csv</code> lists scheduled games
that were cancelled or never played, so their absence is explained. None of the three changes the scoring
formula. A hash of the lists' entries is in the manifest of <a href="edition.json">edition.json</a>.</p>
<div class=box>
<p><b>What this edition does not include.</b></p>
<ul>{missing}
<li><b>Second implementation: {escape(str(manifest["second_implementation"]))}.</b> {reproduced}</li>
<li><b>Settings are {escape(str(params["status"]))}.</b> They were fitted on earlier seasons' game results
only and frozen before this edition (link scale {params["t"]}, margin cap {params["cap"]}).</li>
</ul></div>
<h2>Ranking and ledgers</h2>
<p class=mute>{len(doc["teams"])} teams, {manifest["games"]} games. Open a team to see every game.
Games left out: {omitted}.</p>
{teams}
{measured}<h2>Release checks</h2>
<div class=wrap><table><tr><th></th><th>Check</th><th>Result</th></tr>{checks}</table></div>
<h2>Reproduce it</h2>
<p>SHA-256 of <a href="edition.json">edition.json</a>: <code>{sha256}</code><br>
Games: <a href="games.jsonl">games.jsonl</a> <code>{manifest["games_sha256"]}</code><br>
Snapshot: <code>{manifest["snapshot_hash"]}</code><br>
Frozen settings: <code>{manifest["params_sha256"]}</code><br>
Formula: <code>{manifest["formula_hash"]}</code><br>
Code: <code>{escape(str(manifest["code_hash"]))}</code> · rule version
<code>{escape(str(manifest["rule_version_id"]))}</code> · <a href="gate.json">gate.json</a></p>
</main></body></html>
"""
