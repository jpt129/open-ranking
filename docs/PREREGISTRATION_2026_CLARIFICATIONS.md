# Market contest 2026: clarifications to the preregistration

Written by Track D on 27 Nov 2026 from John's rulings of that day, before any outcome exists and before
any score is computed. `docs/PREREGISTRATION_2026.md` (SHA-256
`6ff0dafbcde6dd571124b30f195a6858e5a00c2d567851330bcefe83971ae412`) is not changed. These five paragraphs say
how five points it leaves open are read. Hashed before the cutoff of Issue 1, 29 Nov 2026 07:00 UTC.

**1. Rules text (sections 2 and 9).** A contract is scored for an issue only if the rules text in the same
capture as the scored book matches the hash in the appendix. "The same capture" is the venue's listing
fetched last before that book and no more than 30 minutes before it; each capture fetches a venue's listing
and then its books. Once a capture shows a text that differs from the appendix, the contract is excluded
from every issue whose cutoff is at or after that capture, whatever later captures show. The report prints
both times for each such contract: the last capture whose text matched and the first whose text differed.

**2. Missing rules text.** If the listing in the scored book's capture carries no rules text for the
contract, or there is no listing in that capture, the contract is excluded from that issue only and is
listed as "rules text missing". It is not a change of text and it does not carry to later issues.

**3. Rows (section 6).** A row is a team and event with a contract in the appendix at either venue and a
probability in the edition. A contract whose team has no probability in the edition is counted as
unmatched, beside rows with no qualifying venue. A team with a probability and no contract at either venue
is not a row; the report gives the number of such teams for each scored issue and event.

**4. Leaked releases.** Eligibility reads the edition's `label_leaked` mark. An edition so marked is
excluded, and listed as excluded with its source, only if the edition records a public source for the leak
dated before its cutoff. The mark with no such record does not exclude the edition; the report says the
edition carries it.

**5. Top-four probability (section 2).** P(bye) is the edition's count of paths in which the team is seeded
1 to 4, divided by the edition's number of paths, under the edition's own publishing rule.
