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

## Independent review fixes

- Added a frozen-release learning-quality gate. `quality_reports.json` now has one exact v2 schema whose independent review binds the exact semantic-registry and group-registry bytes plus its own canonical review hash. The gate first uses the shared frozen loader to validate manifest hashes, then recomputes semantic-record, comparison-group, independent-review, near-duplicate, and reviewed-edge checks from the selected release.
- Added integration negatives where semantic/group/quality artifacts and manifest hashes are rebuilt consistently: near-duplicate meanings, unreviewed comparison edges, changed review content, a missing review, and a non-isolated review all remain release-blocking.
- Hardened the shared loader against symbolic links and Windows reparse points in every release path component, the manifest, and every artifact candidate. All files must resolve beneath the canonical non-linked release directory; the workflow now calls this same validator before both prepare and write phases.
- Moved non-secret result initialization to the first `write-release` step, before checkout. A final `if: always()` synthesis step guarantees fixed journal/readback status files for pre-writer failures, and result upload now treats either missing file as an error.
- Local Windows verification includes deterministic reparse-boundary coverage. Real root-symlink and artifact-escape tests remain enabled and run where the operating system grants symlink creation; this machine reports them as explicit skips rather than passes.
- Review-fix verification: 31 focused release workflow/quality/writer tests passed with 3 operating-system symlink skips; the full 287-test suite passed with 4 explicit skips (the same 3 symlink-capability skips plus the private-source local integration audit). Python compilation, PyYAML semantic validation, all 12 embedded Bash syntax checks, diff checking, and the single-secret-reference audit passed.
