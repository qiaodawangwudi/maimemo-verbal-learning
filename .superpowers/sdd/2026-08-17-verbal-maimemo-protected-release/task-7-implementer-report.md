# Task 7 Implementer Report

## Baseline and scope

- Baseline: `f59d9a7b61db838c48ca82b76f2b4da49272b569`
- Commit subject: `feat: add drift-safe resumable release writer`
- Scope was limited to `task-7-brief.md`, followed by every P1/P2 item in
  `task-7-review.md`.

## Delivered behavior

- Added `release_journal.py` with an append-only JSONL journal, a strict field allowlist, durable flushes, and an OS-owned nonblocking lock. A crashed process releases the OS lock even when the lock file remains, while a live concurrent writer is rejected.
- Added `execute_release(...)` with the exact phase order `precheck`, `comparisons`, `root_readback`, `bases`, `applications`, `final_readback`.
- Every mutation is preceded by a fresh live read. Snapshot drift, card-ID drift, stable-title content drift, duplicate live titles, wrong routes, and same-title/different-content creates fail closed before a POST.
- A same-title/exact-content card is resumed without mutation. An ambiguous mutation response is accepted only after an exact live readback and is never blindly retried.
- A definitive 429 uses the server's `Retry-After`, checks cancellation, reads before retrying, and has a bounded retry budget.
- Comparison root IDs are read after the comparison phase and must match the
  Card-syntax-safe canonical grammar `mkjr_[A-Za-z0-9_.-]+`; base root
  placeholders are resolved only from that readback. Final verification checks
  route IDs/names/counts, deck identity, exact content, grammar version, root
  IDs, and root-reference targets.
- Removed `MaimemoClient.from_environment`. Added `AmbiguousMutationError`, `RateLimitError(retry_after_seconds)`, and `PermanentApiError`, preserving type after authorization-value redaction.
- Added the protected CLI with only `--release-dir`, `--approval-receipt`, and `--journal`. It strictly loads and hash-validates all frozen artifacts, passes the untouched manifest through `release_environment` receipt validation before client construction, and returns nonzero unless the final route-aware readback is successful.
- `release_environment.py` is not present at this baseline, so the CLI imports it only at the protected boundary and fails closed before constructing a client until that module is supplied by its owning task.

## Review remediation

- Every POST is now preceded by a release-wide live-state gate. It checks exact
  deck and route identity, every planned card's route/id/root/content/grammar,
  completed outcomes, and (after root readback) the complete comparison
  title-to-root map.
- Resume and final verification require exact frozen `card_id` for `update` and
  `unchanged`, even when content is identical. Duplicate card, chapter, route,
  and root IDs fail closed.
- Frozen cards are fully parsed before the journal lock is acquired: title,
  content H1, card type, stable key, action/card ID, placeholder position and
  target, resolved reference syntax, and manifest route counts must agree.
  Resolved base references are checked against the exact comparison title/root
  map before POST.
- Public `execute_release` requires a strict snapshot and rejects cyclic,
  non-finite, structurally malformed manifest/card/snapshot/live values before
  mutation. Live and frozen deck identities and route structures are required.
- The protected environment boundary accepts only one exact strict success
  object whose receipt, release ID/hash, GitHub run ID, and environment run ID
  all bind. Every scalar/list/null/cyclic/non-finite/extra-field alternative
  fails before protected client construction.
- API JSON responses now reject duplicate keys, non-finite values, non-object
  roots, and invalid UTF-8. `Retry-After` must be finite and between 0 and 3600
  seconds; cancellation remains checked after the bounded wait and before a
  retry.
- The independent re-review's remaining three P1 paths are closed. Existing
  update/unchanged resume and update readback preserve the snapshot's immutable
  route/id/root/grammar identity; create resume can adopt server identity only
  after an exact routed snapshot proves the stable title absent. Every snapshot
  contains exactly the three manifest route IDs/names, including empty
  all-create releases, and every snapshot card belongs to its exact route.
- Live roots, frozen resolved references, post-placeholder content, and final
  readback share one canonical root/reference parser. Any delimiter-bearing
  root, unresolved placeholder, or residual unparseable `[Card#ID/` fails
  before a dependent POST.

## TDD evidence

- RED: missing writer/API interfaces failed imports and behavior tests.
- GREEN: exception isolation and all writer branches passed.
- RED/GREEN regression cycles were also completed for bare `mkjr_`, stale lock recovery, untouched receipt manifest, and post-base comparison-root drift.
- Review RED reproduced all requested fail-open cases (30 failures and 4
  errors initially). Incremental GREEN cycles covered strict receipts,
  duplicate/non-finite JSON, release-wide drift, exact IDs/routes/root maps,
  malformed frozen structures, bounded retry cancellation, and resolved-root
  mapping before POST.
- Independent re-review RED reproduced nine failures across immutable-root
  resume, orphan create-resume, missing snapshot routes, and delimiter-bearing
  root IDs. Each root cause was made GREEN separately, including a mutation
  readback probe where the server changes an update's root identity.

## Verification

- `git diff --check`: passed (only Git's existing LF-to-CRLF notices).
- `python -m compileall -q maimemo_learning_rebuild tests\maimemo_learning_rebuild`: passed.
- `python -m unittest tests.maimemo_learning_rebuild.test_release_writer tests.maimemo_learning_rebuild.test_release_writer_adversarial tests.maimemo_learning_rebuild.test_sync -v`: 47/47 Task 7 target and adversarial tests passed.
- `python -m unittest discover -v`: 244 tests ran; 242 passed. The only failures are the two pre-existing external-DOCX-dependent review tests listed below (1 error, 1 failure).

## Known external failures

1. `test_real_registry_covers_all_current_and_missing_terms_as_reviewed` errors because `C:\Users\admin\Desktop\20260108 选词刷题5_文稿.docx` is absent.
2. `test_review_cli_without_independent_review_exits_nonzero` then fails because the same missing DOCX prevents the CLI from reaching and printing the expected independent-review diagnostic.

No production Maimemo mutation or live API write was executed during this task.
