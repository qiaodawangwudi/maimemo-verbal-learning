# Task 8 Implementer Report

## Outcome

- Added `ReleaseEnvironment.from_mapping`, `validate_github_receipt`, the Task 7 `validate_release_environment` adapter, and `open_protected_client`.
- Enforced the exact GitHub receipt schema: schema v2, `github_protected_release`, release id/hash, approved SHA, run id, protected environment, and successful deployment.
- Enforced `GITHUB_ACTIONS=true`, `refs/heads/main`, exact `GITHUB_SHA`, positive `GITHUB_RUN_ID`, `maimemo-final-release`, deployment `success`, and exact `RELEASE_HASH` binding.
- Rejected local, pull-request/ref, fork/PR-context, malformed, non-finite, cyclic, extra-field, missing-field, wrong-type, wrong-run, wrong-SHA, and wrong-release inputs before token access.
- Removed the release-writer token fallback. `MAIMEMO_API_TOKEN` is read only by `open_protected_client`, after all non-secret validation, and failures are redacted.
- Made schema-v2 guard authorization require a strict GitHub receipt. Legacy write approval remains accepted as historical input but cannot authorize a schema-v2 write.

## Independent-review remediation

- Replaced the copyable dataclass marker with a private, slot-only, non-copyable and non-serializable capability. Complete release, deck, environment, receipt, and manifest bindings live only in an identity registry; receipts and manifests are stored as canonical bytes.
- Made the Task 7 five-key result and its nested receipt immutable. The capability is held in a private identity registry, and `_create_protected_client` no longer reads or trusts a replaceable object attribute.
- Added a complete Task 5 envelope validator requiring a strict-loader/builder marker, exact v2 schema, exact route/count/artifact-hash shapes, self hash, `authorized` state, and valid state-evidence lineage.
- Reused one full receipt validator in the public environment boundary and guard. Schema-v2 guard plans must carry valid `release_id` and `release_hash` bindings matching every typed receipt field; placeholder values never authorize.
- Restricted events to exact `workflow_dispatch`, exact main, and empty head/base refs.
- Added open-time live environment revalidation and exact comparison with the registered receipt and capability before the single token lookup.
- Wrapped token lookup and client construction in one secret-safe boundary. Failures use a fixed redacted message, suppress chaining with `from None`, and leave neither `__cause__` nor formatted traceback token leakage.

## TDD evidence

- RED 1: module-discovery test failed because `release_environment` did not exist.
- RED 2: after adding interface shells, 12 behavior tests produced 27 expected failures covering the requested gates.
- RED 3: Task 7 adapter and guard-v2 tests failed before writer/guard integration.
- Review RED: 70 focused tests produced 28 expected failures reproducing all P1/P2 findings before remediation.
- Review GREEN: the focused environment, guard, manifest-envelope, writer, adversarial-writer, and sync suites passed.

## Verification

- `python -m unittest tests.maimemo_learning_rebuild.test_release_environment tests.maimemo_learning_rebuild.test_guard -v`: 38 passed.
- `python -m unittest tests.maimemo_learning_rebuild.test_release_writer tests.maimemo_learning_rebuild.test_release_writer_adversarial tests.maimemo_learning_rebuild.test_release_manifest tests.maimemo_learning_rebuild.test_sync -v`: 79 passed.
- `python -m unittest discover -v`: 269 run, 267 passed, 1 failure and 1 error. Both remaining failures are the pre-existing external DOCX dependency issue in `test_review`: the configured `C:\Users\admin\Desktop\20260108 ... .docx` source is absent, causing the direct review test to error and its CLI companion to emit no expected review text.
- `python -m compileall -q maimemo_learning_rebuild tests/maimemo_learning_rebuild`: passed.
- `git diff --check`: no whitespace errors; Git emitted only line-ending conversion warnings.

## Commit

- Original: `feat: require protected github release environment`
- Review fix: `fix: harden protected release capability`
