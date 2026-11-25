# docs/PROTOCOL.md — every P-prompt follows this
1. Read CLAUDE.md, the cited SPEC IDs, docs/PROGRESS.md and the listed files. Summarize the change.
2. Plan the files, interfaces and tests. Wait for approval.
3. Write the acceptance tests first; run them and show they fail.
4. Implement the minimum. Run the full suite, ruff, mypy and lint-imports, and paste the outputs.
5. Ask spec-guardian to review the diff against the IDs. Fix what it finds.
6. Record decisions (ID, choice, reason, alternatives) in DECISIONS.md and gaps in DATA_GAPS.md.
7. Stop and ask if the spec is ambiguous, a source or key is missing, a test would require loosening an invariant, or a budget is missed by more than 2×.
8. Completion report: IDs done; tests added and their status; commands run; budgets measured; open issues; next prompt.
