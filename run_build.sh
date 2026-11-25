#!/bin/sh
D=/private/tmp/claude-501/-Users-johntaylor-Desktop-CFBRankingsProjects/6d4f6c93-3e14-4a2a-891e-5f5b98c8cba6/scratchpad/review-ref
cd /Users/johntaylor/Desktop/CFBRankingsProjects
for v in full noop s2026; do
  uv run python $D/build.py $v $D/ex_$v.pkl > $D/build_$v.log 2>&1 &
done
wait
