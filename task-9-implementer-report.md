# Task 9 Implementer Report

## Scope and baseline

- Baseline: `791c26e2c91954a33491e169a910d192e5b8974c`
- Added the protected manual release workflow and exact CODEOWNERS boundaries.
- Expanded ordinary CI to discover every `test_*.py` module.
- Made `test_review` portable without treating the registry as its own evidence.

## TDD evidence

- Initial Task 9 RED: 6 workflow tests produced 5 errors and 1 failure because the release workflow and CODEOWNERS were absent and CI still listed selected modules.
- First GREEN: all 6 workflow tests passed after the workflow, CODEOWNERS, and discovery-based CI were added.
- Follow-up RED/GREEN cycles covered fixed Python setup, always-present journal output, canonical read-only gate inputs for accepted release artifact aliases, the source coverage/privacy gate, and an exact `refs/heads/main` dispatch context.
- Existing full-suite RED was 270 tests with 1 failure and 1 error, both caused by unavailable private DOCX paths.
- Portable review GREEN uses an independent hand-written repository fixture with a fixed location and quote; the negative case proves an altered quote is rejected. The full private-source audit is now an explicit local integration test gated by `MAIMEMO_RUN_LOCAL_SOURCE_INTEGRATION=1` and source-file presence.

## Release safety contract

- Trigger: `workflow_dispatch` only, with exactly `release_path`, `release_hash`, and `commit_sha`.
- Checkout: exact input SHA, exact main dispatch ref, and equality with freshly fetched `origin/main` in both jobs.
- Release: resolved path must remain below `releases/`; the writer's frozen loader revalidates every bound artifact and the self-hash in both jobs.
- Gates: all repository test modules, public learning quality, application quality, source coverage/privacy, and frozen manifest validation run without the Maimemo token.
- Summary/artifacts: job summary contains deck, routes, counts, privacy counts, release hash, and commit SHA. Only non-secret preparation, journal, and readback reports are uploaded.
- Write boundary: `write-release` needs `prepare-release`, uses environment `maimemo-final-release`, fixed concurrency group `maimemo-production`, and `cancel-in-progress: false`. It rechecks the SHA and release before the only step that receives `MAIMEMO_API_TOKEN: ${{ secrets.MAIMEMO_TOKEN }}`.
- Permissions: workflow-level `contents: read`; CODEOWNERS assigns each critical boundary to exactly `@qiaodawangwudi`.

## Review and verification

- Spec review: all Task 9 brief items mapped to explicit workflow tests and workflow fields; no PR/push release trigger or token reference exists outside the protected writer step.
- Code-quality/security review: untrusted inputs enter scripts through environment variables, release paths are resolved against the allowed root, hashes use strict lowercase digest shapes, temporary gate aliases live outside uploaded reports, and failed writes still produce a redacted readback plus journal artifact.
- Verification commands and final results are recorded in the Task 9 commit handoff.
