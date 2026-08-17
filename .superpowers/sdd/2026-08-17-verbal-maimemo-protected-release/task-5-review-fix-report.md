# Task 5 Review-Fix Report

## Review addressed

Base reviewed commit: `7571e8b277004b42e11c95ef119bcd47aeda0e68`.

Implemented all requested C1-C3 and I1-I3 corrections from `task-5-review.md`.

## C1: state evidence lineage

- State transitions are now adjacent only. Skips, backward moves, and unknown states are rejected.
- Entering every state requires its own strict receipt in addition to all receipts already frozen in `state_evidence`.
- Receipt fields are exact and bind:
  - receipt type and `verified: true` marker;
  - release ID;
  - protected-payload hash;
  - immediate prior state;
  - immediate prior release hash.
- `validate_release_manifest` reconstructs every prior state hash and validates the complete receipt lineage required by the current state.
- A forged `authorized` state with a recomputed self-hash but no complete lineage is rejected by both validation and transition.

## C2: external frozen baseline trust boundary

- The release self-hash is used only as a canonical integrity digest, not as an authorization or anti-forgery credential.
- Entering `plan_frozen` requires an explicitly marked verified frozen-baseline receipt.
- Every later transition must receive the same manifest-external baseline again and match it against the baseline frozen in state evidence.
- The external baseline binds release ID, protected-payload hash, draft state, and draft release hash.
- If a protected payload changes after freeze, even when the attacker recomputes the public self-hash, comparison with the unchanged external baseline returns a new `draft` release and does not mutate the protected input.
- Trust claim is intentionally narrow: this module does not authenticate or cryptographically verify a receipt issuer. It trusts only a caller-supplied receipt that the caller explicitly marks as externally verified, then validates its exact structure, bindings, continuity, and reuse. Signature or deployment-system authenticity remains outside Task 5.

## C3 and I1: independent route plan and bidirectional card binding

- Each action now freezes:
  - `stable_card_key`;
  - title;
  - card type;
  - route ID and name;
  - action;
  - card ID, required for update/unchanged and empty for create.
- Final cards also carry the stable key.
- Plan actions and final cards must form a bidirectional one-to-one set with no duplicate or orphan stable keys.
- Unknown actions and malformed action field sets are blocking errors.
- Declared action counts are recomputed from the action list.
- Per-route before/create/update/unchanged/after counts are frozen independently in `action_plan.route_counts` and validated against both the action list and final cards.
- Manifest route counts come from the independent frozen plan. Equal-count comparison/application swaps therefore fail per-card route binding.

## I2: exact schema and Git receipt exclusion

- Manifest top-level fields are exact; unknown fields are rejected.
- Deck, chapter-route, route-count, card-count, action-count, artifact-hash, state-evidence, and receipt structures are checked against exact field sets.
- Recursive inspection rejects commit fields and any `*_sha` field, including nested `commit_sha`, `merged_sha`, and commit receipts.
- Git merged SHA remains external to the release manifest.

## I3: strict release-manifest input

- Added `load_release_manifest_bytes(raw)` and `load_release_manifest_file(path)`.
- Both preserve the raw UTF-8 boundary and reject duplicate keys, NaN/Infinity, malformed JSON, invalid UTF-8, and non-object roots.
- Builder and strict loaders return a marked manifest object.
- Validator and transition accept only builder/strict-loader manifests, raw bytes, or a file path where supported; ordinary pre-parsed dicts are not silently treated as file-safe manifests.
- Raw manifest bytes are exercised end to end through validation.

## TDD evidence

- Review probes were added before production changes.
- Full review RED: 26 tests produced 39 expected assertion failures and 0 test errors.
- C3/I1 focused GREEN: 6 probes passed.
- I2/I3 focused GREEN: 3 probes passed.
- C1/C2 focused GREEN: 6 probes passed.
- A final malformed protected-manifest probe first reproduced a thrown `ValueError`, was converted to assertion-form RED, and then passed after fail-closed handling was added.

## Final verification

- `python -m unittest tests.maimemo_learning_rebuild.test_release_manifest -v`
  - 27 passed, 0 failures, 0 errors.
- `python -m py_compile maimemo_learning_rebuild\release_manifest.py tests\maimemo_learning_rebuild\test_release_manifest.py`
  - Exit code 0.
- `python -m unittest discover -v`
  - 188 run: 186 passed, 1 failure, 1 error.
  - The remaining two are the unchanged `RegistryReviewTests` failures caused by the missing external desktop DOCX path. No external source file or source-path test was changed.
- `git diff --check`
  - Exit code 0; only Git's existing LF-to-CRLF checkout warnings were emitted.

## Files changed

- `maimemo_learning_rebuild/release_manifest.py`
- `tests/maimemo_learning_rebuild/test_release_manifest.py`
- `tests/fixtures/release/action_plan.json`
- `tests/fixtures/release/final_cards.json`
- `.superpowers/sdd/2026-08-17-verbal-maimemo-protected-release/task-5-review-fix-report.md`

Planned commit message: `fix: harden release manifest trust boundaries`
