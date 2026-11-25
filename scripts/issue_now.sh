#!/bin/sh
# Start the forecast issue that is due, now, from this machine. It hand-triggers the `issue` workflow in the
# data repository and prints the run it started. The workflow waits for the cutoff itself and refuses to
# write an edition that already exists, so running this twice is harmless.
#   scripts/issue_now.sh              start the issue that is due
#   scripts/issue_now.sh rehearsal    full run in replay mode on a temporary copy (writes no edition)
set -eu
REPO=jpt129/open-ranking-data
if [ "${1:-}" = "rehearsal" ]; then
    gh workflow run issue --repo "$REPO" -f rehearsal=true
else
    gh workflow run issue --repo "$REPO"
fi
sleep 6
gh run list --repo "$REPO" --workflow issue --limit 1 \
    --json databaseId,status,createdAt,url -q '.[] | "started: \(.url)  (\(.status), \(.createdAt))"'
echo "watch it with: gh run watch --repo $REPO \$(gh run list --repo $REPO --workflow issue --limit 1 --json databaseId -q '.[0].databaseId')"
