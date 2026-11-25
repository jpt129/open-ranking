# Progress

Updated at the end of every session (docs/PROTOCOL.md).

## 2026-11-25 — P00 Bootstrap + P-SPEC

Done
- Repo, signing, pack files (CLAUDE.md, PROTOCOL.md, 8 agents, 8 skills, settings, guard hook).
- uv project (Python 3.12), `src/cfp` skeleton, `cfp` CLI stub, CI workflow.
- Boundary: three import-linter contracts; `test_import_boundary` runs them in the suite.
- P00 acceptance: smoke tests pass; contract proven to fail on a planted `open_ranking -> forecast` import, probe deleted.
- `docs/SPEC.md` written with traceability table. No model code.

Commands run: `uv sync`, `uv run ruff check .`, `uv run mypy src`, `uv run lint-imports`, `uv run pytest -q` (18 passed).

Open
- spec-guardian review of SPEC.md against the proposal PDF.
- Repo is private; must be public before Issue 1 (Sun 29 Nov 07:00 UTC).

Next prompt: P01 (store and point-in-time API), then P02a/P02b, P03, P04, P15, P23 per docs/PLAN.md §7.

## 2026-11-25 — P01 Store and point-in-time API (DS-01..DS-04)

Done
- `cfp.store.schemas`: 12 tables, each with the six provenance fields and vintage; validation on write.
- `cfp.store.lake`: raw payloads addressed by SHA-256; append-only Parquet partitioned by season; rejects rows citing a missing raw payload and duplicate (key, correction_version).
- `cfp.store.asof`: `as_of(rows, spec, t, mode)` with live / replay / scored modes and a coverage report.
- `cfp.store.views`: `OpenRankingView` (games, teams, membership only) and `PointInTimeView`.
- Guard hook: fixed false positives on the bare word for the frozen-parameters folder; hook behaviour is now covered by tests.
- SPEC.md revised after spec-guardian review (see DECISIONS.md).

Budget: as_of over 1,000,000 rows = 31 ms (budget 1 s).

Open
- SC-04a (open-points vintage for the Sunday issue) and the forfeit interpretation need John's decision.
- Scored mode drops only unknown vintage, as the spec says; reconstructed rows are kept and counted in coverage.

### P01 review round (same day)

spec-guardian confirmed six defects in the first P01 commit; all fixed with tests (see DECISIONS.md "P01 store rules"): backdatable ingest_time, non-atomic multi-season batches, unvalidated raw hashes, a bypassable OpenRankingView, weak import contracts, and silent drops in scored mode.

Commands run: `uv run ruff format .`, `uv run ruff check .`, `uv run mypy src`, `uv run lint-imports` (4 kept, 0 broken), `uv run pytest -q` (129 passed). Budget: as_of over 999,999 lake-backed rows with three corrections per key = 24 ms.

Still to build for DS-04: `test_open_ranking_runs_without_forbidden_tables` (needs editions, P14).

Next prompt: P02a (CFBD client), P02b (CFP releases).

## 2026-11-25 — P02a (CFBD) and P02b (CFP releases)

Decisions: John ruled on SC-04a, forfeits and replay/ingest time, and set conditions for P02 (DECISIONS.md). SPEC.md updated; no [OPEN] items remain. One proposal awaits John: a Selection Day Open Ranking edition with cutoff Sun 6 Dec 02:00 ET.

Done
- `cfp.ingest.http`: one fetch path with token bucket, monthly budget and stage limits (written before each call), retries with jitter, raw archive, fetch log, key scrubbing.
- `cfp.ingest.public_time`, `cfp.ingest.upsert`: err-late first-public rules (kickoff + 4.5 h) and change-only appends.
- `cfp.ingest.cfp_releases` + `cfp ingest releases`: parse, sourced show time, alias resolution, cross-check, Wayback verification, vintage.
- **The four 2026 releases are in the lake** (100 rows), each identical to ESPN's copy. Vintage: release 1 archived_authentic, 2 and 3 reconstructed, 4 live.
- `cfp.ingest.cfbd`, `cfbd_normalize`, `cfp ingest cfbd`: client, parsers and staged season ingest, written against CFBD's published schema.
- Tests: no key-shaped string under tests/, and configured keys appear in no tracked file.

Blocked
- **CFBD rejects the key (HTTP 401).** Three calls were attempted; none succeeded. No games, polls or lines yet, and 2014–25 releases wait on the CFBD cross-check. See DATA_GAPS.md.

Commands run: `uv run ruff format .`, `uv run ruff check .`, `uv run mypy src` (31 files), `uv run lint-imports` (4 kept), `uv run pytest -q` (180 passed), `uv run cfp ingest releases --season 2026` (new=100).

Next: once the key works — `scripts/cfbd_fixture_calls.py`, then `cfp ingest cfbd --season 2026 --what reference games rankings --stage season-2026`, then 2014–25 rankings and games, `cfp ingest releases --season 2014..2025`, lines last. Then P03.

### P02 review round and live ingest (same day)

- spec-guardian confirmed sixteen defects in the first P02 commit; all fixed with tests (DECISIONS.md). One of them, the .env loader keeping an inline comment, was the cause of the CFBD 401s.
- CFBD live calls, in John's order: fixtures (9), 2026 season (10, including a rerun), 2014–25 games and polls (35), lines (26). 118 calls used this month against an allowance of 700.
- In the lake: 31,269 game rows (2014–2026), 9,855 poll rows, 38,479 closing-line rows, and 70 committee releases (1,750 rows) for every season except 2019. Release vintage: 30 archived_authentic, 1 live, 39 reconstructed.
- Recorded, trimmed fixtures now back the CFBD parser tests.

Commands run: `uv run ruff format .`, `uv run ruff check .`, `uv run mypy src`, `uv run lint-imports` (4 kept), `uv run pytest -q` (206 passed), `cfp ingest cfbd ...` and `cfp ingest releases ...` as above.

Open
- 2019 releases (CFBD lacks one); three confirmations from John (Selection Day edition, narrower "live" label, Selection Day public time).

Next prompt: P03 (team identity and membership), then P04, P15, P23.
