# Huasheng Vocabulary Content Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the rejected mechanical preview with evidence-bound, learning-useful basic, comparison, and application previews.

**Architecture:** Four immutable authoring/review artifacts feed a renderer that never invents semantic content. Validators fail closed on malformed cores, incomplete comparison teaching, core-repeating dimensions, templated definition prompts, and non-unique applications.

**Tech Stack:** Python 3.10, JSON, unittest, existing `verbal-maimemo-cards` runtime and GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-19-huasheng-content-rebuild-design.md`

## Global Constraints

- Preview only; never call a Maimemo write API.
- Fields and counts do not prove semantic quality.
- Only reviewed immutable artifacts may be rendered.
- Private course text and card content remain local; GitHub verifies contracts and public statistics only.

---

### Task 1: Reject the old artifact and add adversarial acceptance tests

**Files:**
- Modify: `work/huasheng1000/test_build_three_previews.py`
- Create: `tests/maimemo_learning_rebuild/test_content_acceptance_v2.py`
- Create: `skills/verbal-maimemo-cards/scripts/runtime/maimemo_learning_rebuild/content_acceptance_v2.py`

**Interfaces:**
- Produces: `validate_semantic_review`, `validate_comparison_review`, `validate_application_authoring`, `validate_preview_bundle`.

- [ ] Add tests rejecting the five old application skeletons, direct core-slot quotation, malformed keyword slots, missing comparison meanings/selection rules, core-repeating dimensions, and self-declared pass reports.
- [ ] Run the focused tests and observe failures caused by missing v2 validators.
- [ ] Implement the smallest fail-closed validators.
- [ ] Run focused tests to green and commit.

### Task 2: Rebuild semantic records

**Files:**
- Create: `work/huasheng1000/reviewed/semantic_review_v2.json`
- Create: `work/huasheng1000/build_semantic_review_v2.py`
- Test: `work/huasheng1000/test_semantic_review_v2.py`

**Interfaces:**
- Consumes: the 974 source-bound candidate records and teacher evidence.
- Produces: exact per-term `approved|pending` records with `meaning`, `core_slots`, cues, boundary, and evidence.

- [ ] Add failing tests for punctuation fragments, broken parentheses, generic slots, missing evidence, and unreviewed auto records.
- [ ] Re-review records in stable source order; correct approved records and leave unresolved records pending.
- [ ] Validate exact coverage of all 974 terms and commit only public validator changes.

### Task 3: Rebuild comparison groups and dimension decisions

**Files:**
- Create: `work/huasheng1000/reviewed/comparison_review_v2.json`
- Create: `work/huasheng1000/reviewed/dimension_review_v2.json`
- Create: `work/huasheng1000/test_comparison_review_v2.py`

**Interfaces:**
- Consumes: approved semantic records and teacher grouping evidence.
- Produces: reviewed groups with member profiles, pairwise one-glance edges, selection rules, and separate dimension dispositions.

- [ ] Add failing tests proving course proximity and broad group keys cannot create a formal synonym group.
- [ ] Reconstruct genuine groups and bind every edge to named members and source observations.
- [ ] Reject dimensions that paraphrase any member core; approve only two or more independent choice-changing axes.
- [ ] Validate group coverage and commit public contract changes.

### Task 4: Author and review real application scenarios

**Files:**
- Create: `work/huasheng1000/reviewed/application_authoring_v2.json`
- Create: `work/huasheng1000/test_application_authoring_v2.py`

**Interfaces:**
- Consumes: approved semantic records and comparison rules.
- Produces: natural scenarios, four options, answer, clue observations, and exact distractor rejections.

- [ ] Add failing tests for meta-language, core quotation, low skeleton diversity, absent event structure, and ambiguous options.
- [ ] Author or accurately adapt one concrete scenario for every approved term.
- [ ] Review answer uniqueness independently of the authoring fields and block unresolved questions.

### Task 5: Render, verify, and publish the code gate

**Files:**
- Replace: `work/huasheng1000/build_three_previews.py`
- Update: `docs/reviews/huasheng1000-preview-audit.json`
- Update: `skills/verbal-maimemo-cards/SKILL.md` only if the implementation reveals a missing reusable rule.

**Interfaces:**
- Consumes: the four v2 artifacts.
- Produces: three local previews and `preview_acceptance_v2.json`.

- [ ] Add a failing end-to-end test requiring hash-bound artifacts and zero acceptance errors.
- [ ] Render only approved content without semantic synthesis in the renderer.
- [ ] Run focused tests, the full repository suite, installed Skill self-check, and local output audits.
- [ ] Commit and push public code/tests; confirm GitHub checks while accurately describing their private-content boundary.
