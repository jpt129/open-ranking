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
