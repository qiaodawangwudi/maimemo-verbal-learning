# Task 7 Implementer Report

## Baseline and scope

- Baseline: `f59d9a7b61db838c48ca82b76f2b4da49272b569`
- Commit subject: `feat: add drift-safe resumable release writer`
- Scope was limited to `task-7-brief.md`.

## Delivered behavior

- Added `release_journal.py` with an append-only JSONL journal, a strict field allowlist, durable flushes, and an OS-owned nonblocking lock. A crashed process releases the OS lock even when the lock file remains, while a live concurrent writer is rejected.
- Added `execute_release(...)` with the exact phase order `precheck`, `comparisons`, `root_readback`, `bases`, `applications`, `final_readback`.
- Every mutation is preceded by a fresh live read. Snapshot drift, card-ID drift, stable-title content drift, duplicate live titles, wrong routes, and same-title/different-content creates fail closed before a POST.
- A same-title/exact-content card is resumed without mutation. An ambiguous mutation response is accepted only after an exact live readback and is never blindly retried.
- A definitive 429 uses the server's `Retry-After`, checks cancellation, reads before retrying, and has a bounded retry budget.
- Comparison root IDs are read after the comparison phase and must match `mkjr_\S+`; base root placeholders are resolved only from that readback. Final verification checks route IDs/names/counts, deck identity, exact content, grammar version, root IDs, and root-reference targets.
- Removed `MaimemoClient.from_environment`. Added `AmbiguousMutationError`, `RateLimitError(retry_after_seconds)`, and `PermanentApiError`, preserving type after authorization-value redaction.
- Added the protected CLI with only `--release-dir`, `--approval-receipt`, and `--journal`. It strictly loads and hash-validates all frozen artifacts, passes the untouched manifest through `release_environment` receipt validation before client construction, and returns nonzero unless the final route-aware readback is successful.
- `release_environment.py` is not present at this baseline, so the CLI imports it only at the protected boundary and fails closed before constructing a client until that module is supplied by its owning task.

## TDD evidence

- RED: missing writer/API interfaces failed imports and behavior tests.
- GREEN: exception isolation and all writer branches passed.
- RED/GREEN regression cycles were also completed for bare `mkjr_`, stale lock recovery, untouched receipt manifest, and post-base comparison-root drift.

## Verification

- `git diff --check`: passed (only Git's existing LF-to-CRLF notices).
- `python -m compileall -q maimemo_learning_rebuild tests\maimemo_learning_rebuild`: passed.
- `python -m unittest tests.maimemo_learning_rebuild.test_release_writer tests.maimemo_learning_rebuild.test_sync -v`: 28/28 Task 7 target tests passed.
- `python -m unittest discover -v`: 225 tests ran; 223 passed. The only failures are the two pre-existing external-DOCX-dependent review tests listed below (1 error, 1 failure).

## Known external failures

1. `test_real_registry_covers_all_current_and_missing_terms_as_reviewed` errors because `C:\Users\admin\Desktop\20260108 选词刷题5_文稿.docx` is absent.
2. `test_review_cli_without_independent_review_exits_nonzero` then fails because the same missing DOCX prevents the CLI from reaching and printing the expected independent-review diagnostic.

No production Maimemo mutation or live API write was executed during this task.
