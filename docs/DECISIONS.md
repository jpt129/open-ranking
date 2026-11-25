# Decisions

Format: ID | choice | reason | alternatives. SPEC IDs are added once docs/SPEC.md exists.

## 2026-11-25 — Critical-review suggestions a–l (final build package §1.4)

John accepted all twelve. These are tagged [S] in SPEC.md.

| # | Choice |
|---|---|
| a | Independents get ridge penalty 1/(σc²+σu²); publish Notre Dame's ledger under both penalties. |
| b | Keep the frozen pregame `t` for v1; report leave-one-game-out retrospective calibration as a diagnostic; decide before the 2027 freeze. |
| c | Open Ranking keeps FCS win 0 / loss −99; the CFP "at most one FCS win" rule is stored as a 2027+ eligibility note. |
| d | Integer centipoints: q = round_half_even(p×10⁴); win 10000−q, loss −q, FCS win 0, FCS loss −9900; boundary flag when p×10⁴ is within 10⁻⁶ of a .5 boundary; Python canonical; tiebreak gaps are integers (≤2500). |
| e | Definitions: ordinary FBS game; Week 7 = CFBD calendar week 7; cutoff = Monday 06:00 ET after the week's last game; transitioning programs use NCAA status on the game date with CFP eligibility as a separate flag. |
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
