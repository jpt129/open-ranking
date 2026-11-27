# Market contest preregistration, 2026 pilot

This text is in force from the moment its SHA-256 is posted as described in section 9. It was hashed before
the cutoff of Issue 1 (Sunday 29 November 2026, 07:00 UTC), whether or not Issue 1 delivers a field section
(SPEC MK-02). It is not edited afterwards; a change is a new file with a new hash, and counts only if posted
before that cutoff.

The 2026 contest is a pilot. Results are reported with their intervals. No claim that the forecast is better
than the market is made from this season alone.

Prices are for evaluation only. They never enter a predictor, and nobody on the project trades or advises on
the covered markets.

## 1. Venues

Kalshi and Polymarket, the two venues whose order books the project has archived since 25 Nov 2026,
16:51 UTC. Sportsbook futures are not included: no two-sided archive exists. Any result is stated as against
Kalshi and Polymarket. No statement is made about sportsbooks.

## 2. Events and settlement

| Event | Our probability | Outcome |
|---|---|---|
| Team makes the 12-team field (primary) | `P(field)` in the issue's field section | 1 if the team is in the field the committee announces on Selection Day, 6 Dec 2026; otherwise 0 |
| Team is a top-four seed (secondary) | `P(bye)` in the issue's field section | 1 if the team is seeded 1 to 4 in that announcement; otherwise 0 |

The secondary event is reported separately. Nothing is said about the market on the strength of the
secondary event.

The contracts compared are those listed in the appendix, with each venue's rules text as captured and its
hash. A contract whose rules settle on anything other than the event in this table is excluded and listed.
If a venue's rules text for a contract changes after this file is hashed, the change is reported and that
contract is excluded from the first issue after the change onward. If a venue settles a contract differently
from the committee's announcement, the outcome above is still used and the difference is reported.

## 3. Issues

The live issues of the pilot, by cutoff: Issue 1, 29 Nov 2026 07:00 UTC; Issue 2, 1 Dec 23:00 UTC; Issue 3,
6 Dec 07:00 UTC; Issue 4, 6 Dec 16:00 UTC. Only the first edition of an issue counts; a corrected edition
does not replace it. Replay and rehearsal editions never count.

An issue is scored only if its field section is delivered and is not conditional on title-game pairings
(the edition's `market_contest` field reads "eligible"). An issue whose field section is not delivered, or
is conditional, contributes no rows. It is not replaced by another issue, a later edition or one of its
scenario forecasts. It is listed in the report with the reason from the edition, and the number of excluded
issues is reported beside the number scored.

## 4. Which market price is compared

- Contract side: the Yes contract for the team.
- Source: the last order book the project archived for that contract at or before the issue's cutoff
  (rows of kind "book", captured by the project itself). Venue price history and last-trade prices are not
  used.
- Bid and ask: the best Yes bid and the best Yes ask. On Kalshi, where both sides of the book are bids, the
  Yes ask is 1 minus the best No bid. A side with nothing resting is empty, never 0 or 1.
- Venue probability: the midpoint of that bid and ask. No fee or margin adjustment is made.

## 5. Filters (MK-01)

A venue's book for a contract qualifies for an issue only if all three hold:

- two-sided: a bid and an ask are both present;
- fresh: captured no more than 30 minutes before the cutoff, and not after it;
- spread: ask minus bid is at most 5 percentage points.

Every quote, its depth and every exclusion with its reason (no quote by the cutoff, one-sided, stale, wide)
is archived, and published with the contest report.

## 6. Scoring rule

- Row: one team, one event, one scored issue. A row is matched if the issue's field section gives the
  team a probability and at least one venue qualifies. Otherwise it is unmatched and counted.
- Benchmark: the median of the qualifying venues' probabilities for the row. With two venues that is their
  mean; with one, that venue's probability.
- Primary score: paired log loss on matched rows of the primary event, ours minus the benchmark. A negative
  number favours the forecast. For log loss only, every probability (ours and the benchmark's) is clipped to
  [0.000001, 0.999999]; the number of clipped values is reported. Raw field totals are kept.
- Horizons: Issue 1; Issue 2; Issues 3 and 4 together. A horizon uses whichever of its issues qualify. A
  horizon with no scored issue is reported as such.
- Weights: a unit is one team, one event, one horizon. Repeated issues are averaged within the unit. Units
  weigh equally. The headline number for an event is the mean over its units; each horizon is also reported
  on its own. The season is one block.
- Also reported: each venue separately on the rows where it qualifies, Brier scores, matched and unmatched
  counts, clip counts, and bubble calibration.
- Bubble calibration is reported on the cohort of SPEC VT-12: the teams within five Baseline 2 places of
  the projected last at-large team, frozen at each issue and recorded in the edition. The bubble row is
  descriptive: the cohort is about ten teams, and no conclusion is drawn from it. An issue that cannot
  work out the field as it stands has no cohort and no bubble row.

## 7. Intervals

Each paired difference is reported with a 95% interval from 10,000 bootstrap resamples of teams within the
season (seed 2026; a team's units are resampled together). Teams' outcomes are not independent, so this
interval describes the spread across teams and understates the uncertainty. No season-block interval is
reported, because there is one season (SPEC MK-03).

## 8. What is not done

No venue, event, filter, weight or horizon is added, dropped or changed after the hash is posted. Nothing
here is tuned on 2026 prices. Analyses outside this text may be reported only if labelled as not
preregistered.

## 9. Proof

The SHA-256 of this file is carried by a signed git tag `prereg/2026-market` and an RFC 3161 timestamp
token, both in the public repository https://github.com/jpt129/open-ranking, and by a public post.

## Appendix: contracts and their rules as captured

The rules text for each contract is taken from the venue's public listing as archived by the project. The
hash of the archived payload is given for each event; the payloads are published with the contest report.

### Kalshi: Team makes the 12-team field (primary)

Event `KXNCAAFPLAYOFF-26`, "College Football Playoff Qualifiers" (2026-27). 61 contracts. Captured 2026-11-25 16:51:29 UTC; archived payload SHA-256 `54909fe5f4b6730924a1f9468e84f48622cedeff191fe73662cade70fea6dccb`. Rules address for every row: https://kalshi.com/markets/kxncaafplayoff (formed from the venue's series ticker; the rules text below is the `rules_primary` field of the venue's own listing). Settlement sources named by the venue: ESPN (https://www.espn.com/); Fox Sports (https://www.foxsports.com/); The Wall Street Journal (https://www.wsj.com/). Second rules field, the same for every contract: "Kalshi is not affiliated, associated, authorized, endorsed by, or in any way officially connected with the NCAA. All trademarks, logos, and brand names are the property of their respective owners."

| Contract | Team | Rules text as captured | SHA-256 of the rules text |
|---|---|---|---|
| `KXNCAAFPLAYOFF-26-ALA` | Alabama | If Alabama is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `91c07620e5dfb1885b6ee6d336933c2e83e571bb6f03113280a7efd78711fe3f` |
| `KXNCAAFPLAYOFF-26-ARIZ` | Arizona | If Arizona is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `3a47a5d2d70fa205be2d6b644f789d644f6529c680365c3f21ec3a92cd27f683` |
| `KXNCAAFPLAYOFF-26-ASU` | Arizona State | If Arizona St. is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `12c141a55e00a3ba4005d8dc342385dcb06c0aae5724d65235e6353df444e3cd` |
| `KXNCAAFPLAYOFF-26-ARK` | Arkansas | If Arkansas is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `fe632daa8ad1fdaed82fef3d817c72af5c71b82fb878ed62663609fec1481a35` |
| `KXNCAAFPLAYOFF-26-AUB` | Auburn | If Auburn is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `8d4b4cf26de7685736d6b8d7551c24d1270c2750bd4b29546db4005903a7e8f4` |
| `KXNCAAFPLAYOFF-26-BYU` | BYU | If BYU is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `020813db1dcd67b05ab1525b4a51201214b5b613e9f9e0f1bb1da00ea37cad7c` |
| `KXNCAAFPLAYOFF-26-BAY` | Baylor | If Baylor is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `dc37127c9e875810c927776c1cd13dae24f7f84a62c2f565fb4f15823ae15a4f` |
| `KXNCAAFPLAYOFF-26-BSU` | Boise State | If Boise St. is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `05a43c03e8792a2c98c25df151b7517d92e32922327d6bf9fef4302a2175e681` |
| `KXNCAAFPLAYOFF-26-CAL` | California | If California is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `57aa195ff85bb8a00fb31fa2397bb147bdf46b2857ec287a43474841d7eaab4c` |
| `KXNCAAFPLAYOFF-26-CLEM` | Clemson | If Clemson is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `ec376c3d69b1024fce87c875071c48c939a1c9712c8defee69349c7e3162d633` |
| `KXNCAAFPLAYOFF-26-FLA` | Florida | If Florida is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `ceeb1b427814c8b0abf12e37bf5d829c4e58e4a27c97a4686c25785362bf8972` |
| `KXNCAAFPLAYOFF-26-FSU` | Florida State | If Florida St. is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `59b4bdff03ac50eebcb10756ee7d35a8c6086eea38eef417a50959ca1d38c60b` |
| `KXNCAAFPLAYOFF-26-UGA` | Georgia | If Georgia is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `996e936749fc942a6dc05b3edde256dfcf2b35562f33c1f04620fe5712880909` |
| `KXNCAAFPLAYOFF-26-GT` | Georgia Tech | If Georgia Tech is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `6e56c78257fea82a5fa99ae96701aba6bdf817042eae6a40b0f71f6b094277b0` |
| `KXNCAAFPLAYOFF-26-HOU` | Houston | If Houston is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `a4f0563270e48f454c16991221c19b4e44a14eea95cca3da5dd0e86727d882d3` |
| `KXNCAAFPLAYOFF-26-ILL` | Illinois | If Illinois is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `5fba2c51e25f3082eabd3f312222d7bc00af63821f6e32a2358e7d97f81ba67b` |
| `KXNCAAFPLAYOFF-26-IND` | Indiana | If Indiana is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `6b76e9b7f434b9919d9d81706bf1ec7fbe37192c97db9d4c7d694e7e33f5cf7b` |
| `KXNCAAFPLAYOFF-26-IOWA` | Iowa | If Iowa is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `ff5a4d474f8d8a325b5e0e0fc4ab49fe2b068f7713cd08f718a15798319d9ccb` |
| `KXNCAAFPLAYOFF-26-JMU` | James Madison | If James Madison is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `69e83e2258c0dae22aba3a7a238f6a349a2ec73d41a97b2e899a2914bbe3ae1d` |
| `KXNCAAFPLAYOFF-26-KSU` | Kansas State | If Kansas St. is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `02c257ee4135e6bb2e123584db2c891f2698df53831d0419e352acb60f516de0` |
| `KXNCAAFPLAYOFF-26-UK` | Kentucky | If Kentucky is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `c430b1d0b0bece4f008bf110de5e6aa58f461c5f158b278531595530f507437b` |
| `KXNCAAFPLAYOFF-26-LSU` | LSU | If LSU is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `e2d5da8439e2b68dbe08faf958f3a4bce8854727a753268b98df0f0b21da806a` |
| `KXNCAAFPLAYOFF-26-LIB` | Liberty | If Liberty is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `3ab31a50b13eefec110f40a4c1dd67df838b21f64483243a6446458cf6a12a2c` |
| `KXNCAAFPLAYOFF-26-LOU` | Louisville | If Louisville is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `0afcdee8e55063706d2f01c70e67e93a37361e4da4b3314d93c6624ad6ff15ba` |
| `KXNCAAFPLAYOFF-26-MIA` | Miami | If Miami (FL) is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `80d4ab5bdd32ec1be0e42fc8395321b56360bde321fbd6b57f84d08957ad0a55` |
| `KXNCAAFPLAYOFF-26-MOH` | Miami (OH) | If Miami (OH) is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `5382635458d9c99ba7515eaecfc9b4883d2d04602c0f7f092f87efc4fd3cd019` |
| `KXNCAAFPLAYOFF-26-MICH` | Michigan | If Michigan is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `8b42aea72bf7a92f70688f27248cc4cde8acc870307409573100cfc44c54d4ac` |
| `KXNCAAFPLAYOFF-26-MSST` | Mississippi State | If Mississippi St. is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `7c173818ddceb6dd7e9c2a0a995d5fb4abd64decfb73b8f6366383dcd4af2834` |
| `KXNCAAFPLAYOFF-26-MIZZ` | Missouri | If Missouri is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `1ded56392c5c9bce2cf61ba3876735dae9e485eacae315292a809e8c7f3197a6` |
| `KXNCAAFPLAYOFF-26-UNM` | New Mexico | If New Mexico is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `b5bab639027b1d7274f9d751e96339049be3dfdd6a9561325ed3d634f0ad58b7` |
| `KXNCAAFPLAYOFF-26-NCST` | NC State | If North Carolina St. is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `40cb86a7ccf740c8adcbf456f9450a268d0c88eba1b35584902a52d6f4fd0e1d` |
| `KXNCAAFPLAYOFF-26-UNT` | North Texas | If North Texas is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `643d2395fe4a2d0bde0eb8705e2212e52eea723c97d2b44d90da97722e506a41` |
| `KXNCAAFPLAYOFF-26-NW` | Northwestern | If Northwestern is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `927d027bf55ccd63093ea4a75dbc135fad37ac6d16b39c99dec779aad4a6f38f` |
| `KXNCAAFPLAYOFF-26-ND` | Notre Dame | If Notre Dame is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `b801d4d94d031bac17386737fc4caa9044235bdaa638733ecbe5de1723bf3b08` |
| `KXNCAAFPLAYOFF-26-OSU` | Ohio State | If Ohio St. is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `d5caabca4f46f29a0db83a147989837b1d54e6714e90e2441f8f74ab65c7b113` |
| `KXNCAAFPLAYOFF-26-OKLA` | Oklahoma | If Oklahoma is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `6feabdf8de46e0a1ebac0b32d08ab15b42e93dd3c9d1fe1c19e241e0951609b2` |
| `KXNCAAFPLAYOFF-26-OKST` | Oklahoma State | If Oklahoma St. is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `7618b174ef8da107895324f0f6f8f8490d6f6f40af95dd25b0516832c4661d98` |
| `KXNCAAFPLAYOFF-26-MISS` | Ole Miss | If Ole Miss is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `fa0a5bce29fead6c8f302f909b8fc63232bff6dcdd36b18f565499028cff06a2` |
| `KXNCAAFPLAYOFF-26-ORE` | Oregon | If Oregon is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `4cf0465612fde3d1968da5d91bb9d3fcc3e2273624fa04f63c6bbf7bd777471a` |
| `KXNCAAFPLAYOFF-26-ORST` | Oregon State | If Oregon St. is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `61203c1c0a0ec6847fcd93c132b12e6cd7b0f289b5341a126faed27536dba0d8` |
| `KXNCAAFPLAYOFF-26-PSU` | Penn State | If Penn St. is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `c06c7d888eee1f8c61a0a0f1a33d680356dedda65f3aafd16e2ebda72fa75b04` |
| `KXNCAAFPLAYOFF-26-PITT` | Pittsburgh | If Pittsburgh is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `e4f64732ca11a9366658d5ee1821975dfad5986c240792401a61349da284d138` |
| `KXNCAAFPLAYOFF-26-SMU` | SMU | If SMU is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `bb4a2f00bf3656cb816f301f74035f01b9d75354d19aeabc1111e52a9b20465c` |
| `KXNCAAFPLAYOFF-26-SCAR` | South Carolina | If South Carolina is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `e31089480fb7037b30a5e62b715f6e6bfcecb25a9d0b5aebfa7c8779d5efff00` |
| `KXNCAAFPLAYOFF-26-TCU` | TCU | If TCU is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `9e7810873ab7912eed147315641dd8963434666a669990b10b5593574b95a59d` |
| `KXNCAAFPLAYOFF-26-TENN` | Tennessee | If Tennessee is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `3dd01bce65f8201feb66ef5b82b6e0b44dfdb70d2955d4529f5989f9fb4bac01` |
| `KXNCAAFPLAYOFF-26-TEX` | Texas | If Texas is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `0aa26e5f4e4211a39557df32f76165128724fb2b4cdcc60865c2deafbb0f6d6b` |
| `KXNCAAFPLAYOFF-26-TXAM` | Texas A&M | If Texas A&M is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `3797443c987156318524a5253ea76d4bbc35e00e3affc62ef7bbaa02d5256f50` |
| `KXNCAAFPLAYOFF-26-TTU` | Texas Tech | If Texas Tech is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `455d4769bfe3dafe7f1a123ce0582eaa8f3fcc8792777a071a5df6b527dd6085` |
| `KXNCAAFPLAYOFF-26-TULN` | Tulane | If Tulane is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `c82cd544e4e33ee0dbe81a7536bdf51cb89370e58925d7d4430a7761e5def3bf` |
| `KXNCAAFPLAYOFF-26-UCLA` | UCLA | If UCLA is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `a65e23b1e183f7f830edc4acc9808906b3730412a426a2611435bb4124f76676` |
| `KXNCAAFPLAYOFF-26-MASS` | Massachusetts | If UMass is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `7f8400f9066d7c5a1b112141e12eaac815cfe08e2df04224e14605c6b10401dd` |
| `KXNCAAFPLAYOFF-26-USC` | USC | If USC is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `8e6370aaef31778bcb33986706306f99aedced50b2de047e6b7b4e463e9d01a6` |
| `KXNCAAFPLAYOFF-26-UTAH` | Utah | If Utah is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `1a0841d1e21bb4afc55ebfbe691fd5561eab969d28f8906529238e0ea2f39416` |
| `KXNCAAFPLAYOFF-26-VAN` | Vanderbilt | If Vanderbilt is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `c782e62ffcf85561d0396dc6788f316f2a700e24f4cdff72a7a6b1c3db49bfd0` |
| `KXNCAAFPLAYOFF-26-UVA` | Virginia | If Virginia is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `6ae551b05d3826a2e36f4bd402e7e503cecc82be1348ce03fc7106c03ecaad73` |
| `KXNCAAFPLAYOFF-26-VT` | Virginia Tech | If Virginia Tech is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `b572e5dc369c4edc3d3094d6cc90be9c5ed8642528a8ecff750e3af3f260f11b` |
| `KXNCAAFPLAYOFF-26-WAKE` | Wake Forest | If Wake Forest is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `e33318548af278ff6e400b9d378a978a4543fec50d6465681b80c274d51cdf7a` |
| `KXNCAAFPLAYOFF-26-WASH` | Washington | If Washington is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `9bb905a96775d3e3810620bdb12b3937cb91440e01334c53525a4f8aa21a1d6f` |
| `KXNCAAFPLAYOFF-26-WMU` | Western Michigan | If Western Michigan is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `188df25637afa08cfaa5bcd9046411ed19e8b5340f2bd5c045f567f6fad9fc8c` |
| `KXNCAAFPLAYOFF-26-WIS` | Wisconsin | If Wisconsin is one of the teams to qualify for the College Football Playoffs, then the market resolves to Yes. | `6b98be7ad0bbdbce9bff4ed74144d7180e7c65048340c10449d332ebc6b52fe3` |

### Kalshi: Team is a top-four seed (secondary)

Event `KXNCAAFTOPSEED-27T4`, "College Football Playoff: Top 4 Seeds" (Top 4 (2026-27)). 52 contracts. Captured 2026-11-25 16:54:40 UTC; archived payload SHA-256 `fa7b8a60585a7c1a8dcce3b229fce9392a03259a7ca2ee6f0f51c7780fa71c34`. Rules address for every row: https://kalshi.com/markets/kxncaaftopseed (formed from the venue's series ticker; the rules text below is the `rules_primary` field of the venue's own listing). Settlement sources named by the venue: Kalshi using information originating from the NCAA (https://www.ncaa.com/sports/football/fbs); ESPN (https://www.espn.com). Second rules field, the same for every contract: "Kalshi is not affiliated, associated, authorized, endorsed by, or in any way officially connected with the NCAA. All trademarks, logos, and brand names are the property of their respective owners."

| Contract | Team | Rules text as captured | SHA-256 of the rules text |
|---|---|---|---|
| `KXNCAAFTOPSEED-27T4-ALA` | Alabama | If Alabama is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `2ed1a12be6bce014b1384dd739a78620ce8c9c273ec047a2d64a99e30818f471` |
| `KXNCAAFTOPSEED-27T4-ARIZ` | Arizona | If Arizona is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `1001e10c7ff23039bc413c89c5be719a359a11aed27199910b18284b66527a4c` |
| `KXNCAAFTOPSEED-27T4-ASU` | Arizona State | If Arizona St. is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `9d45aa0febe18b2ba8cbc8425471ba97a68a5fda3eb3fb7eb06c8ce65bc31a61` |
| `KXNCAAFTOPSEED-27T4-ARK` | Arkansas | If Arkansas is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `59025f8f408001b37416685fb9a331c5695eb04df10eb3b3d2a24693455d95ca` |
| `KXNCAAFTOPSEED-27T4-AUB` | Auburn | If Auburn is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `cf5d8d257a2006e4177ff9477c566450d439bf07d9b9b4c8418ed93d222c41b4` |
| `KXNCAAFTOPSEED-27T4-BYU` | BYU | If BYU is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `e27982fafc76d458a85959468102bc8c723b61a685211df0457f2a8a9440a887` |
| `KXNCAAFTOPSEED-27T4-BAY` | Baylor | If Baylor is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `263db03da5fc36eacba74ee546837e4fd3428e16dba737e9a1c3dc5fa30c0711` |
| `KXNCAAFTOPSEED-27T4-CAL` | California | If California is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `8429bfc5bca40afaafb26b65546ee5d75d381e140315178a2cab0a1e673aa1dc` |
| `KXNCAAFTOPSEED-27T4-CLEM` | Clemson | If Clemson is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `b8ac1b02d73be4ffe2b350f65ecaba8494b726842cc1a3b3320d4dbc415ce5bd` |
| `KXNCAAFTOPSEED-27T4-FLA` | Florida | If Florida is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `4c5ea9e3392f550efc4f2b9d1c5a94511aefd097f5113596fcbcf4b3a6d84770` |
| `KXNCAAFTOPSEED-27T4-FSU` | Florida State | If Florida St. is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `004aef8f86edf5e3308e61da4061d99ff287689db2ba8bcd59554348bf74a329` |
| `KXNCAAFTOPSEED-27T4-UGA` | Georgia | If Georgia is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `abd4d8d9eafb178301e5e6cb2ac8330d43d2f905a30dcef8db7efe3ce2e83f8d` |
| `KXNCAAFTOPSEED-27T4-GT` | Georgia Tech | If Georgia Tech is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `0fa4040692d6f5d7b867ff8de1bf058e0e77f531ce8ece601e965eb03e163e87` |
| `KXNCAAFTOPSEED-27T4-HOU` | Houston | If Houston is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `2c82a8d49b91e4a0c951acf86bed9a7dd9102421f31c6ad6758d2c15619e114e` |
| `KXNCAAFTOPSEED-27T4-ILL` | Illinois | If Illinois is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `1686c6160539d1a7d8f24464c177bb306b132ef57eca38d47533b8118e314a40` |
| `KXNCAAFTOPSEED-27T4-IND` | Indiana | If Indiana is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `a530c50bca8b10f02e6237a21ba65c4bb9df99f1f894e510240a1f0e9a4133d3` |
| `KXNCAAFTOPSEED-27T4-IOWA` | Iowa | If Iowa is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `3e19a525c40009a656ae441b92f5451589e3b12710b05ea53f8df3d7022bf9bc` |
| `KXNCAAFTOPSEED-27T4-JMU` | James Madison | If James Madison is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `1e79f54229f9aa75614f66de9b1b1896cb0341cd5974de23126866e38739ab3b` |
| `KXNCAAFTOPSEED-27T4-KSU` | Kansas State | If Kansas St. is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `7619df625b34347259856f46b209d99f21f78a2d5de393a79c4d7f55d2d960dc` |
| `KXNCAAFTOPSEED-27T4-UK` | Kentucky | If Kentucky is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `a75d649674fae3f6ca95f26dfc84526a4402bf4c32854d21c1ad8e54e91b039d` |
| `KXNCAAFTOPSEED-27T4-LSU` | LSU | If LSU is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `716bcfbfe6749bd30f251bef91ec89be1bba2b2f25e54e13b0136056a607e4f6` |
| `KXNCAAFTOPSEED-27T4-LOU` | Louisville | If Louisville is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `1879a974108142de4d1540d90e5036cb4bcf2ee1e0dd5d54e18d254cdf41fac5` |
| `KXNCAAFTOPSEED-27T4-MIA` | Miami | If Miami (FL) is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `8db489731e9d90469af06d77a9a15e31fb489f730b5a3976fb9a077d92330da6` |
| `KXNCAAFTOPSEED-27T4-MOH` | Miami (OH) | If Miami (OH) is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `37e462ee0895058101690139beacd45ebdbdb7e84d90609b9ab0d639d1d2aa7f` |
| `KXNCAAFTOPSEED-27T4-MICH` | Michigan | If Michigan is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `ac4d251c8e797b9daa832fbe6ddf3af0b9f4b501443726042aa3f994581a3a59` |
| `KXNCAAFTOPSEED-27T4-MIZZ` | Missouri | If Missouri is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `2e6b2b9c9fe2b50c357b75ac7562612b78b8c6d63f748953f97109892230f9f7` |
| `KXNCAAFTOPSEED-27T4-NCST` | NC State | If North Carolina St. is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `b56bdd37815c0757a435520c8b29fe3740ac83d5a8c787a79ced3628bed72442` |
| `KXNCAAFTOPSEED-27T4-UNT` | North Texas | If North Texas is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `f0b05c13a7e416cbe34c334b309d101ed8fc3d5f71d8e1d681f85b5cbe6e64c8` |
| `KXNCAAFTOPSEED-27T4-ND` | Notre Dame | If Notre Dame is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `0777d1b4b59d30d0e9832e86d796fea47cc41dea40ad7006072765f3125c4e42` |
| `KXNCAAFTOPSEED-27T4-OSU` | Ohio State | If Ohio St. is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `a1423051fa97e058e83d60e1f51b3c28762aad0d17a80836f37d956eb1f926fb` |
| `KXNCAAFTOPSEED-27T4-OKLA` | Oklahoma | If Oklahoma is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `3e6947599e9bc17319e2ce55427aa18cd9919b9d96215a6a6f65665883769fd1` |
| `KXNCAAFTOPSEED-27T4-OKST` | Oklahoma State | If Oklahoma St. is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `f923783e937fa70c0165b31a4a5b00840886ddc07f8d6b9260d7645b2fcecd93` |
| `KXNCAAFTOPSEED-27T4-MISS` | Ole Miss | If Ole Miss is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `b5e9bc44170ab0556c5f85ef1725cd450e3b3e041e4fe885f61f6fa73ddf6935` |
| `KXNCAAFTOPSEED-27T4-ORE` | Oregon | If Oregon is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `976f4e4e5110d0476aacbcd705c534396a9d573f3d681728a92a216c3db860bc` |
| `KXNCAAFTOPSEED-27T4-PSU` | Penn State | If Penn St. is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `bdb2794feaa94e137c4d799d4709e6db33ce015aae009efe11c1dc275715a335` |
| `KXNCAAFTOPSEED-27T4-PITT` | Pittsburgh | If Pittsburgh is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `31396de86605ee9419c89a2367fd61e81617c343433c1df2e2147eea4d6f984b` |
| `KXNCAAFTOPSEED-27T4-SMU` | SMU | If SMU is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `15589db340d69276cece736142800dc73752133c2ab6bdac89f97a6c4a3daa86` |
| `KXNCAAFTOPSEED-27T4-SCAR` | South Carolina | If South Carolina is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `865cd31f483c3b30d65b954fc4db02110847afc337db84c8277dd3ada0a40ee5` |
| `KXNCAAFTOPSEED-27T4-TCU` | TCU | If TCU is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `5e93d7753ef7c470cbb2407b7d15df96cb61c156fc26a64b7bc9b1531b6b12ee` |
| `KXNCAAFTOPSEED-27T4-TENN` | Tennessee | If Tennessee is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `94b3bfff4e2872cb90863db44fbd20af627235c88a7755f4ac43661a63980bde` |
| `KXNCAAFTOPSEED-27T4-TEX` | Texas | If Texas is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `b0251cdb572fbefb7a6a402a7757b7f8acc7a66011d0a1750f854c54aae4337a` |
| `KXNCAAFTOPSEED-27T4-TXAM` | Texas A&M | If Texas A&M is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `3f74a26d6769abb647c02e3a4e86c803a8e1b5b9727c3f5bb7e043ec851b8f03` |
| `KXNCAAFTOPSEED-27T4-TTU` | Texas Tech | If Texas Tech is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `052d73549d4cc76850fe3f77aed308bb832a886836acbba2f092ad51a142b10f` |
| `KXNCAAFTOPSEED-27T4-TULN` | Tulane | If Tulane is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `6b372f7fa4619aad38f58b26d2cae225b6c27f38a0c3e158bd27144ec2bf78d4` |
| `KXNCAAFTOPSEED-27T4-UCLA` | UCLA | If UCLA is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `da1a887aa8e6cd855d1f0ebccf88fa8a2806fbb3f8e08ea69187b6eb8aff262b` |
| `KXNCAAFTOPSEED-27T4-USC` | USC | If USC is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `c7455c48cd5380f8380fb10d3ecbc68dd5990d70bea977513473cdba152973f4` |
| `KXNCAAFTOPSEED-27T4-UTAH` | Utah | If Utah is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `44c619a63ee516f6e2737c2f4065b80c8354f8a0c9272dd55c3ebc3d821d909c` |
| `KXNCAAFTOPSEED-27T4-VAN` | Vanderbilt | If Vanderbilt is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `dc3cf1a21f095492ffe6679354861a79560fca9e98ffed5cd779d54eb081a36f` |
| `KXNCAAFTOPSEED-27T4-UVA` | Virginia | If Virginia is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `6f37e14bd5cabdacbd5ac97c6cd831b585b039fa55e4d96ca304831637a4817a` |
| `KXNCAAFTOPSEED-27T4-VT` | Virginia Tech | If Virginia Tech is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `8fedd8a6769de8affc10a02f74f308148320fe58393104a69339cec440df82d4` |
| `KXNCAAFTOPSEED-27T4-WAKE` | Wake Forest | If Wake Forest is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `ea347e5b8d0ea94f0dc7a6f49c5b05e7bb34c1bf275054052fbe25154f9132ab` |
| `KXNCAAFTOPSEED-27T4-WASH` | Washington | If Washington is selected as a top 4 seed in the 2026-27 College Football Playoff, then the market resolves to Yes. | `323998fa9e93bcf19216aef73f8deb17d1ac42379873e4e71582092b3cd166a8` |

### Polymarket: Team makes the 12-team field (primary)

Event `948140`, "NCAA Football: Team to make College Football Playoffs". 50 contracts. Captured 2026-11-25 16:54:50 UTC; archived payload SHA-256 `ee26364641b51fdcf268ab487a0a667ae5157b338dc103fe81cc9bbf19ca2034`. Rules address for every row: https://polymarket.com/event/ncaa-football-team-to-make-college-football-playoffs-20260803190433067 (formed from the venue's event slug; the rules text is the `description` field of the venue's own listing). Resolution source field of the listing: https://collegefootballplayoff.com. The rules text is identical for every contract in this event; its SHA-256 is `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece`. As captured:

> This market will resolve "Yes" if the listed team is selected to participate in the 2026 College Football Playoff. Otherwise, this market will resolve "No".
>
> If the selected team does not participate in the College Football Playoffs for any reason, this market will resolve "No".
>
> If the College Football Playoff for the 2026 season is canceled or the participating teams cannot be determined by December 20, 2026 11:59 PM ET, this market will resolve "No".
>
> The primary resolution source will be official information from the College Football Playoff (https://collegefootballplayoff.com); however, a consensus of credible reporting may also be used.

| Contract (market slug) | Team | SHA-256 of the rules text |
|---|---|---|
| `will-alabama-make-the-2026-27-cfb-playoffs-20260803190340040` | Alabama | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-arizona-make-the-2026-27-cfb-playoffs-20260803190340073` | Arizona | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-arizona-stpt-make-the-2026-27-cfb-playoffs-20260803190340071` | Arizona State | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-arkansas-make-the-2026-27-cfb-playoffs-20260803190340077` | Arkansas | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-auburn-make-the-2026-27-cfb-playoffs-20260803190340058` | Auburn | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-byu-make-the-2026-27-cfb-playoffs-20260803190340046` | BYU | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-baylor-make-the-2026-27-cfb-playoffs-20260803190340079` | Baylor | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-california-make-the-2026-27-cfb-playoffs-20260803190340061` | California | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-clemson-make-the-2026-27-cfb-playoffs-20260803190340056` | Clemson | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-florida-make-the-2026-27-cfb-playoffs-20260803190340049` | Florida | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-florida-stpt-make-the-2026-27-cfb-playoffs-20260803190340080` | Florida State | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-georgia-make-the-2026-27-cfb-playoffs-20260803190340037` | Georgia | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-georgia-tech-make-the-2026-27-cfb-playoffs-20260803190340074` | Georgia Tech | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-houston-make-the-2026-27-cfb-playoffs-20260803190340063` | Houston | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-illinois-make-the-2026-27-cfb-playoffs-20260803190340069` | Illinois | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-indiana-make-the-2026-27-cfb-playoffs-20260803190340036` | Indiana | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-iowa-make-the-2026-27-cfb-playoffs-20260803190340059` | Iowa | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-james-madison-make-the-2026-27-cfb-playoffs-20260803190340052` | James Madison | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-kansas-stpt-make-the-2026-27-cfb-playoffs-20260803190340062` | Kansas State | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-kentucky-make-the-2026-27-cfb-playoffs-20260803190340075` | Kentucky | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-lsu-make-the-2026-27-cfb-playoffs-20260803190340041` | LSU | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-louisville-make-the-2026-27-cfb-playoffs-20260803190340057` | Louisville | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-miami-fl-make-the-2026-27-cfb-playoffs-20260803190340035` | Miami | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-miami-oh-make-the-2026-27-cfb-playoffs-20260803190340066` | Miami (OH) | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-michigan-make-the-2026-27-cfb-playoffs-20260803190340051` | Michigan | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-missouri-make-the-2026-27-cfb-playoffs-20260803190340055` | Missouri | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-north-carolina-stpt-make-the-2026-27-cfb-playoffs-20260803190340072` | NC State | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-north-texas-make-the-2026-27-cfb-playoffs-20260803190340081` | North Texas | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-notre-dame-make-the-2026-27-cfb-playoffs-20260803190340032` | Notre Dame | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-ohio-stpt-make-the-2026-27-cfb-playoffs-20260803190340033` | Ohio State | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-oklahoma-make-the-2026-27-cfb-playoffs-20260803190340043` | Oklahoma | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-oklahoma-stpt-make-the-2026-27-cfb-playoffs-20260803190340064` | Oklahoma State | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-ole-miss-make-the-2026-27-cfb-playoffs-20260803190340042` | Ole Miss | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-oregon-make-the-2026-27-cfb-playoffs-20260803190340034` | Oregon | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-penn-stpt-make-the-2026-27-cfb-playoffs-20260803190340047` | Penn State | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-pittsburgh-make-the-2026-27-cfb-playoffs-20260803190340070` | Pittsburgh | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-smu-make-the-2026-27-cfb-playoffs-20260803190340050` | SMU | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-south-carolina-make-the-2026-27-cfb-playoffs-20260803190340060` | South Carolina | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-tcu-make-the-2026-27-cfb-playoffs-20260803190340067` | TCU | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-tennessee-make-the-2026-27-cfb-playoffs-20260803190340048` | Tennessee | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-texas-make-the-2026-27-cfb-playoffs-20260803190340039` | Texas | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-texas-am-make-the-2026-27-cfb-playoffs-20260803190340044` | Texas A&M | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-texas-tech-make-the-2026-27-cfb-playoffs-20260803190340038` | Texas Tech | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-tulane-make-the-2026-27-cfb-playoffs-20260803190340078` | Tulane | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-usc-make-the-2026-27-cfb-playoffs-20260803190340045` | USC | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-utah-make-the-2026-27-cfb-playoffs-20260803190340053` | Utah | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-vanderbilt-make-the-2026-27-cfb-playoffs-20260803190340076` | Vanderbilt | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-virginia-make-the-2026-27-cfb-playoffs-20260803190340068` | Virginia | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-virginia-tech-make-the-2026-27-cfb-playoffs-20260803190340065` | Virginia Tech | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |
| `will-washington-make-the-2026-27-cfb-playoffs-20260803190340054` | Washington | `0f3a954e9bf3b5ba52c6c7e5bd9aac526d5c995b5e26977301c50c88009c7ece` |

### Polymarket: Team is a top-four seed (secondary)

Event `801843`, "NCAA Football: CFB Playoff Top 4 Seeds". 50 contracts. Captured 2026-11-25 16:55:01 UTC; archived payload SHA-256 `4fd911b7d33d03c34c1d589732cde2100c1bbaccfa6e5e54b7338e34568ab2c7`. Rules address for every row: https://polymarket.com/event/ncaa-football-cfb-playoff-top-4-seeds-20260803203916647 (formed from the venue's event slug; the rules text is the `description` field of the venue's own listing). Resolution source field of the listing: empty (the rules text names the source). The rules text is identical for every contract in this event; its SHA-256 is `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940`. As captured:

> This market will resolve to "Yes" if the above team is seeded No. 1, No. 2, No. 3, or No. 4 in the 2026-27 College Football Playoff bracket, and "No" otherwise.
>
> If the 2026-27 College Football Playoff is canceled, or an official bracket is not released by December 20, 2026, 11:59 PM ET, all outcomes in this market will resolve to "No."
>
> The resolution source for this market will be official information from the College Football Playoff (collegefootballplayoff.com); however, a consensus of credible reporting may also be used.

| Contract (market slug) | Team | SHA-256 of the rules text |
|---|---|---|
| `will-alabama-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017349` | Alabama | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-arizona-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017350` | Arizona | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-arizona-stpt-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017352` | Arizona State | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-arkansas-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017351` | Arkansas | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-auburn-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017353` | Auburn | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-byu-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017355` | BYU | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-baylor-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017354` | Baylor | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-california-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017356` | California | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-clemson-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017357` | Clemson | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-florida-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017358` | Florida | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-florida-stpt-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017359` | Florida State | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-georgia-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017345` | Georgia | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-georgia-tech-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017360` | Georgia Tech | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-houston-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017361` | Houston | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-illinois-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017362` | Illinois | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-indiana-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017346` | Indiana | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-iowa-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017363` | Iowa | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-james-madison-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017364` | James Madison | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-kansas-stpt-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017365` | Kansas State | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-kentucky-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017387` | Kentucky | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-lsu-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017367` | LSU | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-louisville-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017366` | Louisville | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-miami-fl-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017368` | Miami | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-miami-oh-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017371` | Miami (OH) | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-michigan-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017369` | Michigan | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-missouri-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017370` | Missouri | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-north-carolina-stpt-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017372` | NC State | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-north-texas-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017388` | North Texas | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-notre-dame-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017373` | Notre Dame | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-ohio-stpt-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017377` | Ohio State | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-oklahoma-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017374` | Oklahoma | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-oklahoma-stpt-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017375` | Oklahoma State | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-ole-miss-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017348` | Ole Miss | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-oregon-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017376` | Oregon | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-penn-stpt-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017379` | Penn State | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-pittsburgh-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017378` | Pittsburgh | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-smu-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017381` | SMU | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-south-carolina-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017380` | South Carolina | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-tcu-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017382` | TCU | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-tennessee-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017383` | Tennessee | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-texas-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017347` | Texas | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-texas-am-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017386` | Texas A&M | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-texas-tech-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017384` | Texas Tech | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-tulane-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017385` | Tulane | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-usc-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017389` | USC | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-utah-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017390` | Utah | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-vanderbilt-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017392` | Vanderbilt | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-virginia-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017391` | Virginia | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-virginia-tech-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017393` | Virginia Tech | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
| `will-washington-be-a-top-4-seed-in-the-2027-college-football-playoffs-20260803204017394` | Washington | `39f0d90befbb8d54066ba4c15880ab5c81c43157aca645b51ee3243b5a58b940` |
