"""Replace one conference's rows in a title pairing file, written with a CSV writer.

    uv run python scripts/pairing_rows.py data/title_scenarios.csv rows.json

rows.json: {"season": 2026, "conference": "SEC", "rows": [{"scenario": ..., "team_a": ..., ...}, ...]}
Every row of that season and conference is replaced by the given rows, at the place of the first one (or at
the end). Other lines are left byte for byte as they are. An empty "rows" removes the conference's rows.
Run `cfp forecast pairings` afterwards; the commit hook does so too.
"""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path


def replace_rows(path: Path, season: int, conference: str, rows: list[dict[str, str]]) -> None:
    lines = path.read_text(encoding="utf-8").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    header = next(csv.reader([lines[0]]))
    fresh = []
    for row in rows:
        row = {"season": str(season), "conference": conference} | {k: str(v) for k, v in row.items()}
        unknown = sorted(set(row) - set(header))
        if unknown:
            raise SystemExit(f"{path.name} has no column {unknown}")
        if any("\n" in value or "\r" in value for value in row.values()):
            raise SystemExit("a value contains a line break")
        out = io.StringIO()
        csv.writer(out, lineterminator="").writerow([row.get(column, "") for column in header])
        fresh.append(out.getvalue())
    kept: list[str] = [lines[0]]
    placed = False
    for line in lines[1:]:
        cells = next(csv.reader([line]))
        if len(cells) != len(header):
            raise SystemExit(f"{path.name}: a line has {len(cells)} fields; the header has {len(header)}")
        if cells[header.index("season")] == str(season) and cells[header.index("conference")] == conference:
            if not placed:
                kept.extend(fresh)
                placed = True
            continue
        kept.append(line)
    if not placed:
        kept.extend(fresh)
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")


if __name__ == "__main__":
    target, spec_path = Path(sys.argv[1]), Path(sys.argv[2])
    spec = json.loads(spec_path.read_text())
    replace_rows(target, int(spec["season"]), spec["conference"], spec["rows"])
    print(f"{target}: {len(spec['rows'])} row(s) for {spec['season']} {spec['conference']}")
