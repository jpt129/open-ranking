# Proofs

- `PREREGISTRATION_2026.tsr`: RFC 3161 timestamp token over the SHA-256 of `docs/PREREGISTRATION_2026.md`,
  `6ff0dafbcde6dd571124b30f195a6858e5a00c2d567851330bcefe83971ae412`, issued by https://freetsa.org/tsr. The same hash is carried by the signed tag
  `prereg/2026-market`. Check the file with `shasum -a 256 docs/PREREGISTRATION_2026.md` and the token with
  `openssl ts -reply -in docs/proofs/PREREGISTRATION_2026.tsr -text`.
