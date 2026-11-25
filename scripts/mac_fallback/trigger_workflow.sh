#!/bin/sh
# Open Ranking fallback: start a workflow in the data repository by hand-trigger, in case GitHub's own
# scheduler does not fire. Safe to run twice: the issue job refuses to write an edition that exists.
# Usage: trigger_workflow.sh <workflow name>      Log: ~/Library/Logs/OpenRanking/trigger.log
WORKFLOW=${1:-issue}
REPO=jpt129/open-ranking-data
GH=/opt/homebrew/bin/gh
LOG="$HOME/Library/Logs/OpenRanking/trigger.log"
stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }
for attempt in 1 2 3 4 5; do
    if out=$("$GH" workflow run "$WORKFLOW" --repo "$REPO" 2>&1); then
        echo "$(stamp) started $WORKFLOW (attempt $attempt)" >> "$LOG"
        exit 0
    fi
    echo "$(stamp) FAILED to start $WORKFLOW (attempt $attempt): $out" >> "$LOG"
    sleep 60
done
exit 1
