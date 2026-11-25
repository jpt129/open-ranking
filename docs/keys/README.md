# Verifying an issue tag

Each forecast issue is published as a signed git tag `issue/<edition_id>` whose message carries the SHA-256
of the edition. Tags are signed with the issuer key in `allowed_signers` (an SSH signing key used only by
the scheduled issue job).

    git config gpg.ssh.allowedSignersFile docs/keys/allowed_signers
    git tag -v issue/<edition_id>

Each edition also has an RFC 3161 timestamp token over the same hash (`timestamp.tsr`), which can be checked
with `openssl ts -verify -digest <sha256> -in timestamp.tsr -CAfile <authority chain>`.
