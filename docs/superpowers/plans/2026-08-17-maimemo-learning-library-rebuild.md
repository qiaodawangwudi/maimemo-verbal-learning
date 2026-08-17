# Maimemo Learning Library Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the complete 730-card Maimemo vocabulary library into a source-grounded, layered learning system that improves logical-fill-in comprehension, discrimination, and transfer to unseen questions.

**Architecture:** A new isolated `maimemo_learning_rebuild` package reads immutable snapshots and source transcripts, validates a master semantic registry, builds a global comparison graph, renders layered Markji cards, produces a frozen action plan, and permits API writes only through a hash-bound guard. Existing sync scripts remain historical references and are never imported by the new writer.

**Tech Stack:** Python 3.10+ standard library, `unittest`, JSON and Markdown artifacts, Markji grammar version 3, Maimemo Open API.

## Global Constraints

- The learning outcome is the top-level acceptance criterion: understand meaning, identify the distinguishing feature, analyze useful dimensions, and choose accurately in new contexts.
- Audit all 730 current cards: 605 base cards and 125 comparison cards.
- Treat the existing 360-word registry as a term/evidence index, not an accepted semantic source.
- Treat existing cards, old manifests, and DeepSeek outputs as historical references only.
- Preserve teacher transcript wording as evidence while rewriting incomplete spoken fragments into accurate learner-facing explanations.
- Mark unsupported or conflicting judgments as `pending` or `conflict`; never fill gaps by inference.
- Use layered cards: concise recall layer first, deeper discrimination and transfer layer second.
- Do not call a Maimemo write endpoint without explicit user authorization, a zero-error frozen plan, and an unchanged plan hash.
- Read tokens only from `MAIMEMO_TOKEN`; never store tokens in files, cards, logs, or reports.
- Do not run `sync_four_poems_maimemo.py` or any earlier sync script.
- Use `git commit --only` so unrelated staged or untracked work remains untouched.

---

### Task 1: Create the validated domain model

**Files:**
- Create: `maimemo_learning_rebuild/__init__.py`
- Create: `maimemo_learning_rebuild/models.py`
- Create: `tests/maimemo_learning_rebuild/test_models.py`

**Interfaces:**
- Consumes: JSON dictionaries from snapshots, source catalogs, semantic registries, group registries, and action plans.
- Produces: `validate_semantic_record(record) -> list[str]`, `validate_group_record(group, terms) -> list[str]`, and `validate_action_record(action) -> list[str]`.

- [ ] **Step 1: Write failing semantic-record tests**

```python
import unittest
from maimemo_learning_rebuild.models import validate_semantic_record


class SemanticRecordTests(unittest.TestCase):
    def test_ready_record_requires_learning_fields_and_evidence(self):
        record = {
            "term": "因噎废食",
            "sense_id": "因噎废食::课程义::001",
            "status": "ready",
            "source_kind": "teacher_transcript",
            "meaning": "因害怕出问题而停止本应继续的行动。",
            "distinctive_feature": "由问题或风险恐惧触发，并导致必要行动被放弃。",
            "dimensions": [{"axis": "触发条件", "judgment": "已经出过问题或担心出问题。"}],
            "comparison_edges": [{"other_term": "投鼠忌器", "minimum_difference": "因噎废食怕问题；投鼠忌器怕牵连。"}],
            "misuse_boundary": "没有停止必要行动时不宜使用。",
            "evidence": [{"source": "lesson.txt", "location": "P001", "quote": "原话"}],
        }
        self.assertEqual([], validate_semantic_record(record))

    def test_ready_record_rejects_repeated_meaning_and_feature(self):
        record = self.valid_record()
        record["distinctive_feature"] = record["meaning"]
        self.assertIn("meaning equals distinctive_feature", validate_semantic_record(record))
```

- [ ] **Step 2: Run the model tests and confirm import failure**

Run: `python -m unittest tests.maimemo_learning_rebuild.test_models -v`  
Expected: `ModuleNotFoundError: No module named 'maimemo_learning_rebuild'`.

- [ ] **Step 3: Implement strict record validators**

Implement allowed statuses `pending`, `ready`, `conflict`, `retired`; require all learner-facing fields for `ready`; reject repeated meaning/feature/boundary text; require evidence for `teacher_transcript`; allow empty evidence only for explicitly labelled `user_directed_supplement`; reject ambiguous references and unknown action values.

- [ ] **Step 4: Run the model test module**

Run: `python -m unittest tests.maimemo_learning_rebuild.test_models -v`  
Expected: all tests pass.

- [ ] **Step 5: Commit only Task 1 files**

Run: `git add -- maimemo_learning_rebuild/__init__.py maimemo_learning_rebuild/models.py tests/maimemo_learning_rebuild/test_models.py && git commit --only -m "feat: add maimemo rebuild domain validators" -- maimemo_learning_rebuild/__init__.py maimemo_learning_rebuild/models.py tests/maimemo_learning_rebuild/test_models.py`

### Task 2: Parse and audit the immutable live snapshot

**Files:**
- Create: `maimemo_learning_rebuild/markji.py`
- Create: `maimemo_learning_rebuild/snapshot.py`
- Create: `tests/maimemo_learning_rebuild/test_markji.py`
- Create: `tests/maimemo_learning_rebuild/test_snapshot.py`
- Preserve: `maimemo_four_poems/audit_readonly/current_library_snapshot_2026-08-17.json`

**Interfaces:**
- Consumes: Maimemo card dictionaries and the frozen 730-card snapshot.
- Produces: `parse_card(card) -> ParsedCard`, `audit_snapshot(snapshot) -> dict`, and a read-only snapshot CLI that never exposes a write method.

- [ ] **Step 1: Write failing parser tests**

Test extraction of title, card type, base term, comparison members, `mkjr_` references, grammar version, card ID, and root ID from representative cards. Test rejection of malformed headings and `mkjc_` references.

- [ ] **Step 2: Run parser tests and confirm failure**

Run: `python -m unittest tests.maimemo_learning_rebuild.test_markji -v`  
Expected: import failure for `maimemo_learning_rebuild.markji`.

- [ ] **Step 3: Implement deterministic Markji parsing**

Use anchored regular expressions for `[P#H1#...]`, `[Card#ID/...#...]`, base title prefix `基础词义｜`, and comparison prefix `近义辨析｜`. Preserve member order while also producing a `frozenset` for overlap analysis.

- [ ] **Step 4: Write and implement snapshot audit tests**

Assert the frozen snapshot reports exactly 730 cards, 605 base cards, 125 comparison cards, zero other cards, zero non-version-3 cards, and zero missing root IDs. Test reference-target validation and duplicate title detection with synthetic fixtures.

- [ ] **Step 5: Run Task 2 tests**

Run: `python -m unittest tests.maimemo_learning_rebuild.test_markji tests.maimemo_learning_rebuild.test_snapshot -v`  
Expected: all tests pass and the real snapshot fixture reports the verified baseline.

- [ ] **Step 6: Commit only Task 2 files**

Run: `git add -- maimemo_learning_rebuild/markji.py maimemo_learning_rebuild/snapshot.py tests/maimemo_learning_rebuild/test_markji.py tests/maimemo_learning_rebuild/test_snapshot.py && git commit --only -m "feat: parse and audit maimemo snapshots" -- maimemo_learning_rebuild/markji.py maimemo_learning_rebuild/snapshot.py tests/maimemo_learning_rebuild/test_markji.py tests/maimemo_learning_rebuild/test_snapshot.py`

### Task 3: Build the full source and provenance catalog

**Files:**
- Create: `maimemo_learning_rebuild/sources.py`
- Create: `maimemo_learning_rebuild/artifacts/source_catalog.json`
- Create: `maimemo_learning_rebuild/artifacts/card_provenance.json`
- Create: `tests/maimemo_learning_rebuild/test_sources.py`

**Interfaces:**
- Consumes: all confirmed transcripts, reviewed course documents, historical registries, manifests, and the 730-card snapshot.
- Produces: `load_source_catalog(path)`, `verify_evidence(catalog, evidence)`, and a per-card provenance classification.

- [ ] **Step 1: Write failing source-catalog tests**

Test that a teacher evidence item requires an existing source file, exact paragraph location, and exact quote. Test that a user supplement cannot claim `teacher_transcript`. Test that one course's DOCX/TXT/JSON derivatives share one source-group ID.

- [ ] **Step 2: Run source tests and confirm failure**

Run: `python -m unittest tests.maimemo_learning_rebuild.test_sources -v`  
Expected: import failure for `maimemo_learning_rebuild.sources`.

- [ ] **Step 3: Implement source loading and evidence verification**

Support the tab-separated `P####\ttext` transcript format and exact quote comparison. Record SHA-256, source group, batch, carrier type, and learner-facing trust role without editing source material.

- [ ] **Step 4: Create the source catalog**

Include the three `four_poems_transcripts` files, the 20260107 and 20260108 course materials that exist locally, reviewed course guides as secondary references, and historical machine outputs as `historical_only`. Do not label a derived guide as independent teacher evidence.

- [ ] **Step 5: Map all 730 cards to provenance states**

Assign each card one of `teacher_source_found`, `user_supplement`, `historical_only`, `mixed_sources`, or `unresolved`. Preserve unresolved cards instead of assigning a guessed batch.

- [ ] **Step 6: Validate and commit Task 3**

Run: `python -m unittest tests.maimemo_learning_rebuild.test_sources -v` and `python -m maimemo_learning_rebuild.sources --validate maimemo_learning_rebuild/artifacts/source_catalog.json maimemo_learning_rebuild/artifacts/card_provenance.json`  
Expected: zero broken evidence pointers and totals equal 730 cards.

### Task 4: Render the unified layered learning cards

**Files:**
- Create: `maimemo_learning_rebuild/render.py`
- Create: `tests/maimemo_learning_rebuild/test_render.py`
- Create: `maimemo_learning_rebuild/examples/approved_learning_examples.json`

**Interfaces:**
- Consumes: validated semantic records and validated comparison groups.
- Produces: `render_base_card(record, group_refs) -> str` and `render_comparison_card(group, records) -> str`.

- [ ] **Step 1: Write failing layered base-card tests**

Use `因噎废食` to assert the card contains one concise meaning, a non-duplicated `特别之处`, a direct `因噎废食 × 投鼠忌器` contrast, only evidence-supported dimensions, a real misuse boundary, one answer separator, and no ambiguous pronouns.

- [ ] **Step 2: Write failing comparison-card tests**

Use `根深蒂固、积重难返、冰冻三尺` to assert each member has a meaning and distinctive feature; assert minimum differences do not equal definitions; assert process, state, and negative-direction dimensions appear only where useful.

- [ ] **Step 3: Run render tests and confirm failure**

Run: `python -m unittest tests.maimemo_learning_rebuild.test_render -v`  
Expected: import failure for `maimemo_learning_rebuild.render`.

- [ ] **Step 4: Implement the layered renderer**

Render the first layer in the order `词义 → 特别之处 → 做题识别点 → 一眼辨析`; render the second layer as optional `多维判断 → 易错边界 → 典型语境`; place full comparison references last. Omit empty sections rather than inserting generic text.

- [ ] **Step 5: Freeze three approved example groups**

Create evidence-grounded example records for `因噎废食、投鼠忌器`, `走马观花、浮光掠影`, and `根深蒂固、积重难返、冰冻三尺`. Store expected rendered content so future changes cannot silently weaken the learning structure.

- [ ] **Step 6: Run and commit Task 4**

Run: `python -m unittest tests.maimemo_learning_rebuild.test_render -v`  
Expected: all tests pass.

### Task 5: Rebuild and validate the global comparison graph

**Files:**
- Create: `maimemo_learning_rebuild/groups.py`
- Create: `tests/maimemo_learning_rebuild/test_groups.py`
- Create: `maimemo_learning_rebuild/artifacts/group_registry.json`

**Interfaces:**
- Consumes: all validated semantic records and current comparison cards.
- Produces: `audit_group_overlaps(groups)`, `validate_group_semantics(group, records)`, and stable ordered group records.

- [ ] **Step 1: Write failing graph tests**

Cover equal member sets with different order, subset overlap, partial overlap, a term in multiple independently justified groups, missing reciprocal edges, unstable member order, and a course-chapter mega-group whose members lack direct comparison evidence.

- [ ] **Step 2: Run graph tests and confirm failure**

Run: `python -m unittest tests.maimemo_learning_rebuild.test_groups -v`  
Expected: import failure for `maimemo_learning_rebuild.groups`.

- [ ] **Step 3: Implement structural graph validators**

Detect exact, subset, and partial overlaps; require an explicit `overlap_reason` for retained overlaps; require each member to have a definition and at least one meaningful comparison connection; preserve master-registry order.

- [ ] **Step 4: Reconstruct the 125-card comparison universe**

Review every current group against source evidence and learning value. Record `keep`, `split`, `merge`, `retire_content`, or `repurpose` decisions with reasons. Do not auto-decide based only on group size or overlap.

- [ ] **Step 5: Validate and commit Task 5**

Run: `python -m unittest tests.maimemo_learning_rebuild.test_groups -v` and `python -m maimemo_learning_rebuild.groups --validate maimemo_learning_rebuild/artifacts/group_registry.json`  
Expected: no unexplained overlap, unknown member, or unstable order.

### Task 6: Rebuild the complete semantic registry

**Files:**
- Create: `maimemo_learning_rebuild/artifacts/master_semantic_registry.json`
- Create: `maimemo_learning_rebuild/artifacts/semantic_review_log.jsonl`
- Create: `maimemo_learning_rebuild/review.py`
- Create: `tests/maimemo_learning_rebuild/test_review.py`

**Interfaces:**
- Consumes: source catalog, provenance map, current 605 base terms, the 16 missing three-lesson terms, and the validated group registry.
- Produces: the single authoritative semantic registry and review log.

- [ ] **Step 1: Write failing registry-wide tests**

Assert unique `term + sense_id`, allowed statuses, verified evidence, non-repeated learner fields, known comparison members, no generic warning phrases, and complete decision logs. Assert teacher fragments such as `如火如荼 = 一些军队` and `述而不作 = 是什么意思啊` are rejected.

- [ ] **Step 2: Implement batch validation and review reports**

Implement `review_registry(records, catalog, groups) -> dict` with exact counts for ready, pending, conflict, retired, missing evidence, broken edges, repeated fields, and suspicious spoken fragments.

- [ ] **Step 3: Rebuild records source-group by source-group**

Process in this fixed order: 20260107 material, 20260108 material, historical 215-card sources, three four-poems transcripts, user supplements, unresolved historical cards. For every record, restore meaning, distinctive feature, useful dimensions, comparison edges, misuse boundary, and evidence.

- [ ] **Step 4: Perform full semantic self-review**

For each ready record, answer four questions in the review log: what the term means, what makes it distinctive, which dimensions decide use, and how it transfers to a new context. Downgrade any record that cannot answer all four without unsupported invention.

- [ ] **Step 5: Validate and commit Task 6**

Run: `python -m unittest tests.maimemo_learning_rebuild.test_review -v` and `python -m maimemo_learning_rebuild.review --registry maimemo_learning_rebuild/artifacts/master_semantic_registry.json --sources maimemo_learning_rebuild/artifacts/source_catalog.json --groups maimemo_learning_rebuild/artifacts/group_registry.json`  
Expected: zero hard errors; pending and conflict counts are explicitly reported rather than hidden.

### Task 7: Generate the offline final library and action plan

**Files:**
- Create: `maimemo_learning_rebuild/planning.py`
- Create: `tests/maimemo_learning_rebuild/test_planning.py`
- Create: `maimemo_learning_rebuild/artifacts/final_cards.json`
- Create: `maimemo_learning_rebuild/artifacts/action_plan.json`
- Create: `maimemo_learning_rebuild/artifacts/learning_preview.md`

**Interfaces:**
- Consumes: frozen snapshot, master semantic registry, group registry, and layered renderer.
- Produces: deterministic final cards, per-card actions, expected final count, and a readable learning preview.

- [ ] **Step 1: Write failing action-plan tests**

Test `unchanged`, `update`, `manual-review`, `create`, and `repurpose`; require exact card IDs for update/repurpose; reject create when an equivalent base or group exists; require count equation `before + create = expected_after`; reject actions for pending/conflict records.

- [ ] **Step 2: Implement deterministic planning**

Match base cards by normalized term and sense; match comparison cards by member set and semantic purpose; prefer update, then repurpose, and use create only when no safe existing card can serve. Include content hashes and reasons for every non-unchanged action.

- [ ] **Step 3: Render the full offline library**

Generate every ready base and comparison card in stable order, then create a Markdown preview grouped by semantic field. The preview must expose concise layer, deep layer, comparison links, provenance state, and planned action without embedding tokens.

- [ ] **Step 4: Validate and commit Task 7**

Run: `python -m unittest tests.maimemo_learning_rebuild.test_planning -v` and `python -m maimemo_learning_rebuild.planning --snapshot maimemo_four_poems/audit_readonly/current_library_snapshot_2026-08-17.json --registry maimemo_learning_rebuild/artifacts/master_semantic_registry.json --groups maimemo_learning_rebuild/artifacts/group_registry.json`  
Expected: deterministic hashes across two consecutive runs and a self-consistent expected final count.

### Task 8: Add the machine-enforced write guard

**Files:**
- Create: `maimemo_learning_rebuild/guard.py`
- Create: `tests/maimemo_learning_rebuild/test_guard.py`
- Modify: `<CODEX_HOME>/skills/verbal-maimemo-cards/scripts/preflight.py`
- Modify: `<CODEX_HOME>/skills/verbal-maimemo-cards/SKILL.md`

**Interfaces:**
- Consumes: frozen snapshot hash, registry, groups, final cards, action plan, and approval marker.
- Produces: `GuardResult(ok, errors, plan_hash)` and a nonzero exit status on any unsafe state.

- [ ] **Step 1: Write failing guard tests**

Test rejection for repeated learner fields, copied minimum differences, generic warnings, unexplained group overlap, missing root references, pending records, inconsistent counts, changed plan hash, unauthorized create, missing approval, and any write attempt against the wrong chapter.

- [ ] **Step 2: Run guard tests and confirm failure**

Run: `python -m unittest tests.maimemo_learning_rebuild.test_guard -v`  
Expected: import failure for `maimemo_learning_rebuild.guard`.

- [ ] **Step 3: Implement defense-in-depth validation**

The guard must call the model, snapshot, group, registry, renderer, and planning validators; recompute all hashes; require zero hard errors and zero unresolved actions; require a user-authorized approval file containing the exact plan hash; reject all other states.

- [ ] **Step 4: Upgrade the reusable skill and preflight**

Document the learning-first acceptance standard, full-library audit requirement, layered card structure, semantic-registry authority, action-plan hash, and explicit write authorization. Extend preflight so old scripts cannot bypass content and plan checks.

- [ ] **Step 5: Run all tests and commit Task 8**

Run: `python -m unittest discover -s tests -t . -p 'test_*.py' -v`  
Expected: all old and new tests pass.

### Task 9: Implement guarded sync and readback verification

**Files:**
- Create: `maimemo_learning_rebuild/api.py`
- Create: `maimemo_learning_rebuild/sync.py`
- Create: `maimemo_learning_rebuild/readback.py`
- Create: `tests/maimemo_learning_rebuild/test_sync.py`
- Create: `tests/maimemo_learning_rebuild/test_readback.py`

**Interfaces:**
- Consumes: an approved action plan, guarded final cards, `MAIMEMO_TOKEN`, and the fixed deck/chapter configuration.
- Produces: rate-limited updates, returned root IDs, and a complete readback report.

- [ ] **Step 1: Write failing API-isolation tests**

Use a fake transport to prove read calls cannot mutate state; write calls require a passed guard result; tokens never appear in exceptions; create is blocked unless explicitly present in the approved plan.

- [ ] **Step 2: Implement the API client and sync order**

Support only documented GET and POST capabilities. Apply comparison updates first, read back root IDs, rebuild dependent base references, verify the hash-bound content again, then apply base updates. Stop on the first count, ID, title, content, or HTTP anomaly.

- [ ] **Step 3: Implement full readback verification**

Compare live total, title uniqueness, content hashes, grammar version, root references, group coverage, and unplanned additions against the approved plan. Produce an explicit failure report instead of continuing after any mismatch.

- [ ] **Step 4: Run sync tests without network writes**

Run: `python -m unittest tests.maimemo_learning_rebuild.test_sync tests.maimemo_learning_rebuild.test_readback -v`  
Expected: all fake-transport tests pass; no live endpoint is contacted.

- [ ] **Step 5: Commit Task 9 files**

Commit only the new API, sync, readback, and test files.

### Task 10: Final offline acceptance and authorized execution

**Files:**
- Create: `maimemo_learning_rebuild/artifacts/final_acceptance_report.md`
- Create only after user authorization: `maimemo_learning_rebuild/artifacts/write_approval.json`
- Create after live execution: `maimemo_learning_rebuild/artifacts/readback_report.json`

**Interfaces:**
- Consumes: every artifact and validator from Tasks 1-9.
- Produces: the final offline decision, optional write approval marker, and verified live result.

- [ ] **Step 1: Run the full offline acceptance suite**

Run all unit tests, validate every JSON artifact, regenerate final cards twice to verify stable hashes, scan all learner-facing content, and confirm the action count equation.

- [ ] **Step 2: Produce the final acceptance report**

Report total terms, senses, base cards, comparison cards, application cards, unchanged/update/repurpose/create/manual-review counts, ready/pending/conflict counts, expected final total, and every unresolved reason.

- [ ] **Step 3: Stop if any unresolved item remains**

Do not create an approval marker and do not call the API when the report contains a hard error, pending/conflict action, unexplained overlap, or count mismatch.

- [ ] **Step 4: Obtain explicit write authorization for the frozen hash**

After the user authorizes the exact plan hash, create `write_approval.json` containing only the chapter ID, plan hash, authorization time, and approved action totals. Never include a token.

- [ ] **Step 5: Execute guarded sync and verify readback**

Run the guarded sync once, then perform a fresh full readback. Stop immediately if the live result differs from the plan.

- [ ] **Step 6: Deliver the learner-facing entry point**

Provide the final card totals, unresolved count, readback result, and a clear study entry that explains how to use base cards, comparison cards, dimensions, and transfer practice.

