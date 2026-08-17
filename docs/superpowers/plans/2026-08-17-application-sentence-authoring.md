# Application Sentence Authoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace raw spoken-transcript prompts with independently authored or deeply adapted application sentences and enforce the distinction in GitHub.

**Architecture:** Raw evidence remains in a quarantined source-material queue. Formal application records carry structured construction provenance and are validated before rendering, planning, or release.

**Tech Stack:** Python 3.10, `unittest`, JSON artifacts, GitHub Actions, Markji rendering.

## Global Constraints

- Teacher transcripts are evidence, never direct formal prompts.
- Formal modes are exactly `authored` and `adapted`.
- Every prompt must be natural written Chinese with one defensible answer.
- No Maimemo write occurs before the new frozen plan receives exact user approval.

---

### Task 1: Construction provenance and language gate

**Files:**
- Modify: `maimemo_learning_rebuild/application_quality_gate.py`
- Modify: `tests/maimemo_learning_rebuild/test_application_quality_gate.py`

**Interfaces:**
- Consumes: structured `application` dictionaries.
- Produces: validation errors for unsupported provenance, raw speech, copied evidence, and answer leakage.

- [ ] Add a failing test with `construction.mode="raw_transcript"` and a prompt containing “同学们”。
- [ ] Run `python -m unittest -v tests.maimemo_learning_rebuild.test_application_quality_gate` and confirm the new test fails.
- [ ] Add `authored`/`adapted` validation, oral-marker rejection and source-copy rejection.
- [ ] Rerun the test module and confirm it passes.
- [ ] Commit the gate change.

### Task 2: Render transparent exercise provenance

**Files:**
- Modify: `maimemo_learning_rebuild/render.py`
- Modify: `tests/maimemo_learning_rebuild/test_render.py`

**Interfaces:**
- Consumes: `application["construction"]`.
- Produces: a compact back-side label stating “自主创作” or “原题改编”。

- [ ] Add a failing renderer test requiring `【题目性质】` on the back only.
- [ ] Run the focused test and confirm failure.
- [ ] Render the provenance label after the transfer rule.
- [ ] Rerun renderer tests and confirm success.
- [ ] Commit the renderer change.

### Task 3: Reclassify raw extraction as source material

**Files:**
- Modify: `maimemo_learning_rebuild/application_candidates.py`
- Modify: `tests/maimemo_learning_rebuild/test_application_candidates.py`
- Regenerate: `maimemo_learning_rebuild/artifacts/application_candidate_queue.json`

**Interfaces:**
- Consumes: transcript evidence.
- Produces: `source_material_only=true`, `formal_prompt_eligible=false` pending material.

- [ ] Add a failing test proving extracted material is never formally eligible.
- [ ] Run the focused test and confirm failure.
- [ ] Add immutable quarantine flags and rename user-facing warning text.
- [ ] Regenerate the queue and verify every item remains pending.
- [ ] Commit the queue change.

### Task 4: Curate, rebuild, and verify formal application cards

**Files:**
- Create: `maimemo_learning_rebuild/artifacts/application_review.json`
- Regenerate: `maimemo_learning_rebuild/artifacts/action_plan.json`
- Regenerate: `maimemo_learning_rebuild/artifacts/final_cards.json`
- Regenerate: `maimemo_learning_rebuild/artifacts/learning_preview.md`
- Modify: `maimemo_learning_rebuild/artifacts/final_acceptance_report.md`

**Interfaces:**
- Consumes: semantic registry, group registry and quarantined material.
- Produces: complete review decisions, formal application cards and a new plan hash.

- [ ] Review every ready semantic record and comparison group exactly once.
- [ ] Author or deeply adapt each approved exercise with explicit clues and distractor exclusions.
- [ ] Run both public and application quality gates; require only the final write-approval guard to remain blocked.
- [ ] Run the complete repository-portable test suite.
- [ ] Commit and push the rebuilt artifacts; verify GitHub checks before requesting final write approval.

