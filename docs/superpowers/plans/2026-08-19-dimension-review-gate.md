# Vocabulary Dimension Review Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent fixed-axis templates and blanket dimension deletion by requiring every comparison group to carry an independently reviewable dimension disposition before rendering.

**Architecture:** Add a strict `dimension_review` artifact with one disposition per comparison group. Rendering consumes only approved dimensions; it never derives axes from cues or boundaries. A batch-level audit rejects missing dispositions, unjustified all-empty output, repeated judgment skeletons, and a dominant fixed axis pair, while allowing legitimately repeated axis names when their evidence and judgments differ.

**Tech Stack:** Python 3.10, JSON artifacts, `unittest`, Markdown Skill documentation, GitHub Actions.

**Spec:** User-approved mechanism in this task: reviewed dimensions or a reviewed insufficient-evidence disposition; no renderer synthesis; homogeneity checks are rejection gates rather than diversity targets.

## Global Constraints

- Preview only; do not call the Maimemo write API.
- Each displayed dimension must be evidence-bound, selection-changing, and independent of the core and other axes.
- Fewer than two approved dimensions means the block is omitted, but the group must still have an explicit reviewed disposition.
- Reusing an axis name is allowed; fixed axis-pair plus repeated sentence skeleton and derivation provenance is not.
- Raw course text and card content remain local; GitHub receives only code, tests, counts, and hashes.

---

### Task 1: Strict dimension-review contract

**Files:**
- Create: `skills/verbal-maimemo-cards/scripts/runtime/maimemo_learning_rebuild/dimension_review.py`
- Create: `tests/maimemo_learning_rebuild/test_dimension_review.py`

**Interfaces:**
- Consumes: comparison groups, semantic records, dimension-review JSON.
- Produces: `validate_dimension_review(groups, records, review) -> list[str]` and `dimension_review_hash(review) -> str`.

- [ ] Write tests that reject missing group dispositions, fixed two-axis templates, repeated judgment skeletons, fake axis renaming, copied core text, missing evidence anchors, and blanket `insufficient_dimensions`.
- [ ] Run the tests and confirm the intended failures.
- [ ] Implement the strict validator and canonical hash.
- [ ] Run the focused tests to green.

### Task 2: Batch-specific reviewed dimension artifact

**Files:**
- Create: `C:/Users/admin/Documents/New project/work/huasheng1000/reviewed/dimension_review.json`
- Modify: `C:/Users/admin/Documents/New project/work/huasheng1000/build_three_previews.py`
- Modify: `C:/Users/admin/Documents/New project/work/huasheng1000/test_build_three_previews.py`

**Interfaces:**
- Consumes: reviewed semantic registry, comparison groups, reviewed dimension dispositions.
- Produces: three previews whose dimension blocks come only from `approved_dimensions`.

- [ ] Add failing tests proving the old `常见搭配 + 语境排除` batch and all-empty deletion are rejected.
- [ ] Build dispositions from group-specific evidence and explicitly mark groups with fewer than two supported axes.
- [ ] Remove renderer-side `reviewed_pair_dimensions` synthesis.
- [ ] Regenerate previews and run all 16 local tests plus answer-hidden application review.

### Task 3: Skill and repository enforcement

**Files:**
- Modify: `skills/verbal-maimemo-cards/SKILL.md`
- Modify: `skills/verbal-maimemo-cards/references/learning-quality-rubric.md`
- Modify: `tests/maimemo_learning_rebuild/test_skill_preflight.py`
- Modify: `docs/reviews/huasheng1000-preview-audit.json`
- Modify: `tests/test_huasheng1000_preview_audit.py`

**Interfaces:**
- Consumes: validated local quality counts and hashes.
- Produces: a reusable Skill contract and privacy-safe GitHub audit.

- [ ] Add failing Skill and audit tests for explicit dispositions and anti-homogeneity enforcement.
- [ ] Update the Skill, rubric, audit counts, and artifact hashes.
- [ ] Run focused and full repository tests.
- [ ] Install and verify the canonical Skill, push the PR, and confirm GitHub Actions succeeds.
