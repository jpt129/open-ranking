---
name: ingest-release
description: Ingest and verify a CFP committee release.
---
Fetch the CFP page, store the raw payload with its hash, parse 25 rows, map identities and cross-check against a second source. Fail on any mismatch.
