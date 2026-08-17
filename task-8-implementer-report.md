# Task 8 Implementer Report

## Outcome

- Added `ReleaseEnvironment.from_mapping`, `validate_github_receipt`, the Task 7 `validate_release_environment` adapter, and `open_protected_client`.
- Enforced the exact GitHub receipt schema: schema v2, `github_protected_release`, release id/hash, approved SHA, run id, protected environment, and successful deployment.
- Enforced `GITHUB_ACTIONS=true`, `refs/heads/main`, exact `GITHUB_SHA`, positive `GITHUB_RUN_ID`, `maimemo-final-release`, deployment `success`, and exact `RELEASE_HASH` binding.
- Rejected local, pull-request/ref, fork/PR-context, malformed, non-finite, cyclic, extra-field, missing-field, wrong-type, wrong-run, wrong-SHA, and wrong-release inputs before token access.
- Removed the release-writer token fallback. `MAIMEMO_API_TOKEN` is read only by `open_protected_client`, after all non-secret validation, and failures are redacted.
- Made schema-v2 guard authorization require a strict GitHub receipt. Legacy write approval remains accepted as historical input but cannot authorize a schema-v2 write.

## TDD evidence

- RED 1: module-discovery test failed because `release_environment` did not exist.
- RED 2: after adding interface shells, 12 behavior tests produced 27 expected failures covering the requested gates.
- RED 3: Task 7 adapter and guard-v2 tests failed before writer/guard integration.
- GREEN: the requested Task 8 and guard command passed 29/29 tests.
- GREEN: release-writer and adversarial integration passed 34/34 tests.

## Verification

- `python -m unittest tests.maimemo_learning_rebuild.test_release_environment tests.maimemo_learning_rebuild.test_guard -v`: 29 passed.
- `python -m unittest tests.maimemo_learning_rebuild.test_release_writer tests.maimemo_learning_rebuild.test_release_writer_adversarial -v`: 34 passed.
- `python -m unittest discover -v`: 259 run, 257 passed, 1 failure and 1 error. Both remaining failures are the pre-existing external DOCX dependency issue in `test_review`: the configured `C:\Users\admin\Desktop\20260108 ... .docx` source is absent, causing the direct review test to error and its CLI companion to emit no expected review text.
- `git diff --check`: no whitespace errors; Git emitted only line-ending conversion warnings.

## Commit

- `feat: require protected github release environment`
