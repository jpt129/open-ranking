"""Draft data/aliases_cfp_site.csv from archived payloads. The output is then checked by hand.

Names printed by the CFP site are matched exactly to ESPN's team `location`; the exceptions below were
resolved by hand. Every row carries ESPN's display name so a reader can verify the match.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from cfp.store.lake import Lake

EXCEPTIONS = {
    "Appalachian State": "App State",
    "Baylor University": "Baylor",
    "Mississippi": "Ole Miss",
    "Northwestern University": "Northwestern",
    "Oklahoma State University": "Oklahoma State",
    "San Jose State": "San José State",
    "San Jose State University": "San José State",
    "Southern California": "USC",
}
# ESPN lists more than one school at these locations; the FBS program's ESPN id, chosen by hand.
HAND_IDS = {"Troy": "2653"}


def main() -> None:
    lake = Lake("lake")
    log = [json.loads(line) for line in (lake.root / "fetch_log.jsonl").read_text().splitlines()]
    names: set[str] = set()
    teams: dict[str, list[dict[str, str]]] = {}
    for entry in log:
        body = json.loads(lake.get_raw(entry["raw_hash"]))
        if entry["source"] == "cfp_site":
            names |= {" ".join(t["team"].split()) for release in body for t in release["teams"]}
        if entry["source"] == "espn" and "/teams" in entry["url"]:
            for item in body["sports"][0]["leagues"][0]["teams"]:
                team = item["team"]
                known = teams.setdefault(team["location"], [])
                if team["id"] not in [t["id"] for t in known]:
                    known.append(team)
    out = Path("data/aliases_cfp_site.csv")
    with out.open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["alias", "team_id", "espn_display_name", "match"])
        for name in sorted(names):
            location = EXCEPTIONS.get(name, name)
            found = [t for t in teams.get(location, []) if HAND_IDS.get(location, t["id"]) == t["id"]]
            if len(found) != 1:
                raise SystemExit(f"no single ESPN team for {name!r}: {[t['displayName'] for t in found]}")
            team = found[0]
            writer.writerow(
                [
                    name,
                    f"cfbd-{team['id']}",
                    team["displayName"],
                    "hand" if name in EXCEPTIONS or name in HAND_IDS else "exact",
                ]
            )
    print(f"wrote {len(names)} aliases to {out}")


if __name__ == "__main__":
    main()
