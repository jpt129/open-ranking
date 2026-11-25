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

Next prompt: P02a (CFBD client), P02b (CFP releases).
