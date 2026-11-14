# Contributing

Fork → `morrowdock validate` → PR → CI → maintainer review → merge. An advisory AI pre-screen and app-catalog delivery are planned; neither is in place yet. For code-only repositories run the documented focused tests in place of course validation. This is an early preview; focused issues and pull requests are welcome.

Sign every commit with `git commit -s`, certifying the [Developer Certificate of Origin 1.1](DCO) ([source](https://developercertificate.org/)). CI rejects pull-request commits without a `Signed-off-by:` line. Sign-off must match the contributor; do not sign on another person's behalf. Inbound equals outbound: Apache-2.0 code, CC BY-SA 4.0 course content. No CLA or assignment. A DCO is an origin attestation, not blanket relicensing permission.

Use synthetic tests only. No keys, private URLs, owner configuration, instructor originals, textbook banks, Canvas exports, personal documents or learner records. Include per-asset sources, hashes, licenses, rights holder and change attribution; attest redistribution rights and employer/university permissions. Identify generated content. Attribution alone is not permission.

Dependencies require exact version/source/hash/license and transitive distribution review. No GPL/AGPL/LGPL/MPL/custom-license runtimes; Pyodide and CheerpJ are excluded. CPython/PSF is a future permissive Python option subject to binary review. Preserve vendor notices. Never auto-merge or auto-publish. AI does not verify rights, award quality labels or merge.

## Changelogs and releases

Every merged user-facing change adds an entry to the relevant CHANGELOG.md (root, website/, or the public repo). Releases (TestFlight, site deploy, tags) fail without one. Batch site deploys into releases.

The Changelog PR check requires a new nonempty entry under `## [Unreleased]` and a standard category, compared with the base branch. A dated-section addition does not satisfy the PR check. Existing entry text must be preserved; moving or editing an old entry is not a new entry. Documentation in docs/, tests, CI files and contribution policy are excluded; mixed product changes still require an entry. A maintainer can set `no-changelog` for changes with no user-facing effect. This label is not a release waiver.
