"""Cut test fixtures for P02b from payloads archived in lake/raw. Fixtures hold only the fields tests read."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from cfp.ingest.cfp_releases import decode
from cfp.store.lake import Lake

OUT = Path("tests/fixtures")


def latest(lake: Lake, source: str, needle: str) -> bytes:
    log = [json.loads(line) for line in (lake.root / "fetch_log.jsonl").read_text().splitlines()]
    found = [e for e in log if e["source"] == source and needle in e["url"]]
    if not found:
        raise SystemExit(f"nothing archived for {source} {needle}")
    return lake.get_raw(found[-1]["raw_hash"])


def trim_site(payload: list[dict[str, Any]], keep: int | None = None) -> list[dict[str, Any]]:
    payload = sorted(payload, key=lambda r: r["releaseDate"])[:keep]
    return [
        {
            "id": r["id"],
            "year": r["year"],
            "week": r["week"],
            "releaseDate": r["releaseDate"],
            "teams": [{"rank": t["rank"], "team": t["team"], "record": t["record"]} for t in r["teams"]],
        }
        for r in payload
    ]


def main() -> None:
    lake = Lake("lake")
    OUT.mkdir(parents=True, exist_ok=True)

    def dump(name: str, value: Any) -> None:
        (OUT / name).write_text(json.dumps(value, indent=1, ensure_ascii=False) + "\n")

    dump("cfp_site_rankings_2026.json", trim_site(json.loads(latest(lake, "cfp_site", "year=2026"))))
    dump("cfp_site_rankings_2025_first.json", trim_site(json.loads(latest(lake, "cfp_site", "year=2025")), 1))
    for week in (10, 11, 12, 13):
        espn = json.loads(latest(lake, "espn", f"weeks={week}"))
        committee = [r for r in espn["rankings"] if r["type"] == "cfp"]
        trimmed = [
            {
                "type": r["type"],
                "name": r["name"],
                "date": r["date"],
                "ranks": [
                    {
                        "current": k["current"],
                        "team": {"id": k["team"]["id"], "location": k["team"]["location"]},
                    }
                    for k in r["ranks"]
                ],
            }
            for r in committee
        ]
        dump(f"espn_rankings_2026_w{week}.json", {"rankings": trimmed})
    page = decode(latest(lake, "wayback", "20251105073639id_"))
    article = re.search(r"(?is)<article\b.*?</article>", page)
    if article is None:
        raise SystemExit("no <article> in the archived press release")
    (OUT / "wayback_cfp_news_20251105073639.html").write_text(article.group(0) + "\n")
    print(sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
