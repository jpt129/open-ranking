# Decisions

Format: ID | choice | reason | alternatives. SPEC IDs are added once docs/SPEC.md exists.

## 2026-11-25 — Critical-review suggestions a–l (final build package §1.4)

John accepted all twelve. These are tagged [S] in SPEC.md.

| # | Choice |
|---|---|
| a | Independents get ridge penalty 1/(σc²+σu²); publish Notre Dame's ledger under both penalties. |
| b | Keep the frozen pregame `t` for v1; report leave-one-game-out retrospective calibration as a diagnostic; decide before the 2027 freeze. |
| c | Open Ranking keeps FCS win 0 / loss −99; the CFP "at most one FCS win" rule is stored as a 2027+ eligibility note. |
| d | Integer centipoints: q = round_half_even(p×10⁴); win 10000−q, loss −q, FCS win 0, FCS loss −9900; boundary flag when p×10⁴ is within 10⁻⁶ of a .5 boundary; the Python value is canonical and the cross-check tolerates mismatches only on flagged games; tiebreak gaps are integers (≤2500); display rounds half-even. |
| e | Definitions: ordinary FBS game = a completed regular-season or title game between two teams classified FBS on the game date, not a forfeit; Week 7 = CFBD calendar week 7; cutoff = Monday 06:00 ET after the week's last game; transitioning programs use NCAA status on the game date with CFP eligibility as a separate flag. |
| f | Head-to-head series = every meeting that season, title games included; a 1–1 split keeps points order. |
| g | Title games are included in the strength fit; bowls and playoff games are excluded. **Amendment (accepted with the plan, docs/PLAN.md §5.3):** the site comes from the official site/home designation, not forced neutral, because several title games are played on campus. This overrides the "title games neutral" wording in prompt P04. |
| h | Resolve times in America/New_York and store UTC; on a DST-change Sunday use the later 02:00. |
| i | Prove pre-reveal issue by publishing the edition bundle's SHA-256 via a signed public git tag, an RFC 3161 timestamp token and a public post. |
| j | Add a secondary weekly score on the union of the forecast top 35 and the actual top 25; verify the 2026 FBS count (136 vs 138). |
| k | Bubble cohort = Baseline 2 cohort frozen at issue, used for every model. |
| l | Champion-naming rules are loaded per season as data; the 2027 freeze is blocked until each is published. |

## 2026-11-25 — Naming and repo

- One repository holds everything.
- Public display names: the project and the ranking are **Open Ranking**; the forecasting side is presented as **Open Ranking Models**. (Claude's reading of John's note; the exact wording of the second name was "Open Ranking Models or something like that" and is not final.)
- Internal names in the proposal and code (Shadow Committee, Committee Gap, `cfp.forecast`) are unchanged.

## 2026-11-25 — Sources available

- CFBD API key: available. Odds API key: available. Both live in `.env` (git-ignored).

## 2026-11-25 — Pack installation: departures from the final build package

Made by Claude while installing §5.1–5.5; flagged here for John's review.

- **guard.py is anchored to the project root** instead of substring matching. Reason: the pack's version blocked `ts/src/` in the clean-room session and read-only shell commands naming the frozen-parameters folder. Edits and writes under the editions and frozen folders are still blocked, as are shell commands that name those paths together with a mutating verb (including interpreters and redirects). The hook matcher also covers Grep and Glob so a clean-room session cannot search `src/`. Alternative: keep the pack's version and avoid a `src/` folder under `ts/`.
- **CLAUDE.md has a "Project notes" section** appended after the pack's verbatim text (decision overrides, CLI-only writes to frozen paths, display names, where the prompts live, key names).
- **docs/PROPOSAL.md** is a transcription of the Revised Proposal PDF with page markers; reference URLs were taken from the PDF's link annotations.

## 2026-11-25 — Pilot scope (accepted by John)

- **Pilot track additions.** Cut-down P11 (frozen parameters, labelled provisional), P14 (public ledger edition without the TypeScript what-if), P20 (scoring) and P22 (Gap) join the pilot track. Reason: the pilot cannot produce a ledger or score the 1 Dec reveal without them. Alternative: ship forecasts only.
- **RL-01a.** Until the second implementation exists, the release gate records "second implementation: not run" in the manifest and public page and does not fail on it. Alternative: every pilot release fails the gate.

## 2026-11-25 — SPEC review (spec-guardian) and resulting choices

The reviewer found PROPOSAL.md faithful to the PDF and SPEC.md's numbers verbatim, and listed places where SPEC.md went beyond or fell short of the proposal. Resolutions:

- **[K] tag.** Constraints that come from the final build package rather than the proposal (write-once editions, the OpenRankingView allow-list, hashing the preregistration before the first scored issue, "report complete, not empty", display rounding only at render, post-cutoff games excluded) are kept and tagged [K]. Reason: John approved building with the pack, whose CLAUDE.md and prompts state them. Alternative: drop them to the proposal's weaker wording.
- **VT-07 vs the boundary.** The closing-line benchmark is a report computed in `cfp.scoring`, outside `cfp.open_ranking`, and never selects a parameter. Alternative: carve calibration out of the boundary.
- **Forfeits (OR-07d), Claude's interpretation.** A forfeit is scored in the ledger as a win or loss at its reference probability with the policy exception "forfeit"; its margin stays out of the fit; the exact-flip test is not asserted for it. Needs John's confirmation.
- **Missing requirements added:** OR-13, OR-14, CG-05, DS-06, DS-07, RL-05 to RL-10.
- **Open: SC-04a.** Which open-points vintage the Sunday 02:00 ET forecast uses. Proposed: computed at the issue's own cutoff as a feature build.

## 2026-11-25 — P01 store rules (after spec-guardian review of the first P01 commit)

The review confirmed six defects; each now has a test. Choices made (DS-01..DS-04):

- **The lake stamps ingest_time from its own clock.** A caller-supplied value is ignored, so a row cannot be backdated into a past live view. Alternative: trust ingest code to set it.
- **Correction versions are strict per key:** start at 0, rise by one, no gaps, no out-of-order appends. Alternative: any unique version number.
- **A batch lands in full or not at all**, under a per-table file lock; a failed batch leaves nothing and can be retried.
- **Raw payloads are verified on append** (digest format and bytes), and `put_raw` repairs a corrupt copy.
- **OpenRankingView holds no lake.** It is handed a reader that enforces the allow-list again, cannot be subclassed, and lives in a module that imports nothing able to open the lake. PointInTimeView moved to `cfp.store.pit`. Import contracts now forbid the lake transitively for open_ranking, snapshot and rules; a source scan test covers routes imports cannot see. Python has no real privacy: the last layer is still the planned test that deletes forbidden tables and demands a byte-identical edition (P14).
- **Scored reads report coverage through both views**, including the first dropped keys, and can be scoped to a season.
- **`as_of` raises on tied rows** instead of returning both.
- **Replay and scored modes ignore ingest_time** (only live mode requires it). Reason: backfilled history is ingested long after the fact, so requiring it would make every historical replay empty. Consequence: scored replays rest on the first_public_time asserted for reconstructed rows, which is why vintage is tracked. Read strictly, DS-03 asks for both conditions on every forecast query; this is a deliberate narrowing to live issues. Needs John's confirmation.
- **A row cannot be public after it was ingested** (first_public_time <= ingest_time is enforced). Ingest code must clamp estimated public times to the ingest time. Not in the proposal; a store invariant.
- **Scored mode drops only unknown vintage**, as DS-02 says; reconstructed rows are kept and counted in coverage.
- **Guard hook:** destructive commands are now parsed (including `cd` and quoted or bare folder arguments) rather than pattern-matched.

## 2026-11-25 — Trading policy

- John confirmed that nobody on the project trades the covered markets (playoff qualifier, seed and related futures on the venues the project benchmarks against).

## 2026-11-25 — Hash-proof signing

- Edition tags are signed with an SSH key (git `gpg.format ssh`), configured per-repo. The public key must also be registered on GitHub as a signing key so tags show as verified.
