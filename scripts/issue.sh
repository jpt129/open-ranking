#!/bin/sh
# Run the forecast issue that is due now, if any. Meant to be started well before the cutoff (up to three
# hours); safe to start more than once.
#
#   LAKE=<lake dir> scripts/issue.sh              the issue due now
#   REHEARSAL=1 LAKE=<lake dir> scripts/issue.sh  full run in replay mode against a temporary copy of the lake
#
# Before the cutoff it refreshes inputs: committee releases, AP poll and votes, game results (again 30, 12 and
# 4 minutes before the cutoff, so late finals are in the store in time) and a market capture. After the cutoff
# it builds, writes, timestamps and tags the edition and pushes the tag. What the edition may read is decided
# by the store at the cutoff, not by when this script runs: anything ingested after the cutoff is invisible.
set -u
cd "$(dirname "$0")/.." || exit 1
SEASON=${SEASON:-2026}
LAKE=${LAKE:-lake}
RUN="${UV:-uv} run cfp"

say() { echo "$(date -u +%FT%TZ) $*"; }
try() { "$@" || say "WARNING: failed: $*"; }

results() {
    try $RUN --lake "$LAKE" ingest cfbd --season "$SEASON" --what games --stage "issue-$(date -u +%m%dT%H%M)"
}
other_inputs() {
    try $RUN --lake "$LAKE" ingest releases --season "$SEASON"
    try $RUN --lake "$LAKE" ingest cfbd --season "$SEASON" --what rankings --stage "polls-$(date -u +%m%dT%H%M)"
    try $RUN --lake "$LAKE" ingest ap-others --season "$SEASON" --current
}
capture() {
    try $RUN --lake "$LAKE" markets snapshot
    if [ -n "${ODDS_API_KEY:-}" ]; then try $RUN --lake "$LAKE" ingest odds; fi
}

if [ "${REHEARSAL:-}" = "1" ]; then
    say "REHEARSAL: refreshing inputs in $LAKE, then issuing in replay mode from a temporary copy"
    other_inputs
    results
    copy=$(mktemp -d)
    cp -R "$LAKE/normalized" "$copy/normalized"
    $RUN --lake "$copy" forecast issue --season "$SEASON" --issue sun0200 --reveal 2026-11-24 --mode replay --push
    code=$?
    say "REHEARSAL finished, status=$code (edition in $copy/editions)"
    exit $code
fi

# shellcheck disable=SC2046
set -- $($RUN --lake "$LAKE" forecast due --season "$SEASON")
if [ $# -ne 3 ]; then
    say "no issue is due"
    exit 0
fi
ISSUE=$1
REVEAL=$2
CUTOFF=$3
say "due: $ISSUE for the $REVEAL reveal; cutoff in $((CUTOFF - $(date +%s))) seconds"
if [ "$(date +%s)" -ge "$CUTOFF" ]; then
    say "WARNING: LATE START. Anything ingested now is after the cutoff and will not be in the edition."
fi

other_inputs
results
capture
for lead in 1800 720 240; do
    wait=$((CUTOFF - lead - $(date +%s)))
    if [ "$wait" -gt 0 ]; then
        sleep "$wait"
        results
        if [ "$lead" -eq 720 ]; then capture; fi
    fi
done
wait=$((CUTOFF + 5 - $(date +%s)))
if [ "$wait" -gt 0 ]; then sleep "$wait"; fi

tries=0
extra=""
while :; do
    # shellcheck disable=SC2086
    $RUN --lake "$LAKE" forecast issue --season "$SEASON" --issue "$ISSUE" --reveal "$REVEAL" --push $extra
    code=$?
    tries=$((tries + 1))
    case $code in
        0) break ;;
        17) say "the edition was already issued"; code=0; break ;;
        75) if [ "$tries" -ge 30 ]; then break; fi; sleep 10 ;;
        18)
            if [ -n "$extra" ]; then break; fi
            say "WARNING: results look stale; issuing anyway and listing the unresolved games in the edition"
            extra="--allow-unresolved"
            ;;
        *) break ;;
    esac
done
say "issue finished, status=$code"
exit "$code"
