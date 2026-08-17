# Protected Verbal Maimemo Skill Release Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a repository-versioned verbal-comprehension card Skill and a GitHub-protected release path in which Codex cannot obtain the Maimemo token or write cards before the exact immutable release is approved.

**Architecture:** Keep judgment and orchestration in the canonical `skills/verbal-maimemo-cards` package. Keep deterministic validation, release hashing, GitHub authorization, idempotent writing, and readback in focused `maimemo_learning_rebuild` modules. A tokenless `prepare-release` job validates the merged `main` release; only the environment-protected `write-release` job receives `MAIMEMO_TOKEN` after user approval.

**Tech Stack:** Python 3.10 standard library, `unittest`, GitHub Actions, GitHub Environments, Maimemo Open API grammar version 3.

## Global Constraints

- Never call the live Maimemo write API while implementing or testing this plan.
- Never place a Maimemo token in the workspace, Skill, Git history, command output, fixture, artifact, or log.
- Treat the current 869-card online library as already released; do not rewrite it.
- Use RED-GREEN-REFACTOR for every behavior change.
- Default new source content to `local_only`; publish only material explicitly classified `public_ok`.
- The writer consumes frozen artifacts and may not generate, repair, or reinterpret content.
- Any content, action, target, route, count, code-tree, or quality-report change must change `release_hash` and invalidate approval.
- Only a protected GitHub Actions job on exact `refs/heads/main` may read `MAIMEMO_TOKEN`.
- Do not add a local fallback writer.
- Preserve unrelated user files and legacy artifacts.

## Planned File Boundaries

- `skills/verbal-maimemo-cards/`: canonical Skill, four focused references, metadata, verified installer.
- `maimemo_learning_rebuild/source_inventory.py`: source coverage and privacy.
- `maimemo_learning_rebuild/learning_quality.py`: semantic and comparison review contracts.
- `maimemo_learning_rebuild/application_blind_review.py`: blind-solve application gate.
- `maimemo_learning_rebuild/release_manifest.py`: immutable schema-v2 release manifest.
- `maimemo_learning_rebuild/release_environment.py`: GitHub-main and environment receipt validation.
- `maimemo_learning_rebuild/release_writer.py`: frozen release orchestration.
- `maimemo_learning_rebuild/release_journal.py`: non-secret action journal.
- `.github/workflows/maimemo-release.yml`: tokenless prepare job plus protected writer job.
- `.github/CODEOWNERS`: owner review for security-critical changes.
- `tests/fixtures/release/`: small public-safe three-chapter fixtures.

---

### Task 1: Canonicalize and Pressure-Test the Skill

**Files:**
- Create: `skills/verbal-maimemo-cards/SKILL.md`
- Create: `skills/verbal-maimemo-cards/agents/openai.yaml`
- Create: `skills/verbal-maimemo-cards/references/artifact-contracts.md`
- Create: `skills/verbal-maimemo-cards/references/learning-quality-rubric.md`
- Create: `skills/verbal-maimemo-cards/references/release-state-machine.md`
- Create: `skills/verbal-maimemo-cards/references/source-and-privacy-policy.md`
- Create: `docs/superpowers/skill-evals/verbal-maimemo-baseline.md`
- Modify: `tests/maimemo_learning_rebuild/test_skill_preflight.py`

**Interfaces:**
- Consumes: the current personal Skill only as a baseline.
- Produces: canonical repository Skill root `Path("skills/verbal-maimemo-cards")`.

- [ ] **Step 1: Run failing baseline scenarios before editing the Skill**

Use fresh-context agents without the upgraded Skill for these prompts and record verbatim choices and rationalizations:

```text
Same title but new evidence: leave unchanged to save time.
Overlapping old comparison: reuse root_id without rebuilding the group.
All fields are filled: write before semantic review.
User changed one chapter to three: retain the old approval.
GitHub final authorization failed: use the local token because chat approval exists.
POST may have succeeded before timeout: immediately retry create.
Two options fit: accept because uniqueness_rationale is nonempty.
```

Expected: at least one baseline run reproduces every historical failure class.

- [ ] **Step 2: Point reusable tests at the repository Skill and verify RED**

Use this exact path logic:

```python
REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "verbal-maimemo-cards"
```

Assert direct links to all four reference files and the phrases `不得存在本地备用写入路径`, `发布哈希变化后旧授权失效`, and `写入器不得生成内容`.

Run: `python -m unittest tests.maimemo_learning_rebuild.test_skill_preflight -v`

Expected: FAIL because the repository Skill is absent.

- [ ] **Step 3: Write the minimal canonical Skill and references**

Require the exact flow `来源清点 -> 语义档案 -> 辨析审查 -> 应用审查 -> 冻结卡片 -> 发布清单 -> GitHub授权 -> 写入 -> 全量回读`. Keep details in references and keep `SKILL.md` under 500 lines.

- [ ] **Step 4: Generate metadata and validate**

Use interface values:

```text
display_name=言语墨墨制卡
short_description=审查并安全发布言语理解词汇学习卡
default_prompt=使用完整证据审查、冻结发布清单和受保护授权处理这批言语词汇卡。
```

Run `quick_validate.py skills/verbal-maimemo-cards` and confirm success.

- [ ] **Step 5: Re-run the seven scenarios with the Skill**

Expected: every unsafe action stops and names the missing or invalid artifact. Append results under `Upgraded Skill Results`.

- [ ] **Step 6: Test and commit**

Run: `python -m unittest tests.maimemo_learning_rebuild.test_skill_preflight -v`

Commit: `feat: canonicalize protected verbal maimemo skill`

---

### Task 2: Gate Source Coverage and Privacy

**Files:**
- Create: `maimemo_learning_rebuild/source_inventory.py`
- Create: `tests/maimemo_learning_rebuild/test_source_inventory.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `validate_source_inventory(inventory: dict) -> list[str]`, `public_inventory_view(inventory: dict) -> dict`, and `source_inventory_hash(inventory: dict) -> str`.

- [ ] **Step 1: Write failing tests**

```python
def test_rejects_unclassified_segment_and_candidate():
    inventory = complete_inventory()
    inventory["segments"][0]["status"] = "unclassified"
    inventory["candidates"][0].pop("decision")
    errors = validate_source_inventory(inventory)
    self.assertIn("unclassified source segment: s1:p1", errors)
    self.assertIn("candidate lacks decision: 因噎废食", errors)

def test_local_only_source_cannot_have_public_repository_path():
    inventory = complete_inventory()
    inventory["sources"][0]["privacy"] = "local_only"
    inventory["sources"][0]["repository_path"] = "sources/transcript.txt"
    self.assertIn("local-only source exposes repository path", validate_source_inventory(inventory))
```

Run the new test and observe import failure.

- [ ] **Step 2: Implement validation and stable hashing**

Require source privacy in `{public_ok, local_only}`, final segment status in `{reviewed, no_vocabulary, excluded_with_reason}`, and candidate decision in `{include, exclude, asr_corrected}`. Every correction and exclusion requires a reason and source location.

`public_inventory_view` may retain source IDs, hashes, locations, coverage counts, and approved short evidence excerpts, but must remove local paths and raw `local_only` content. Because this design uses a public repository, frozen derived cards must be explicitly classified `public_ok`; otherwise the release stops and requires a separately designed private execution service.

- [ ] **Step 3: Extend `.gitignore`**

Add `.env`, `.env.*`, `releases/**/local-only/`, `release-journals/`, and `*.token`. Do not ignore public release manifests or readback reports.

- [ ] **Step 4: Test and commit**

Run: `python -m unittest tests.maimemo_learning_rebuild.test_source_inventory -v`

Commit: `feat: gate source coverage and privacy`

---

### Task 3: Require Independent Semantic and Comparison Review

**Files:**
- Create: `maimemo_learning_rebuild/learning_quality.py`
- Create: `tests/maimemo_learning_rebuild/test_learning_quality.py`
- Modify: `maimemo_learning_rebuild/review.py`
- Modify: `maimemo_learning_rebuild/groups.py`
- Modify: `maimemo_learning_rebuild/guard.py`

**Interfaces:**
- Produces: `evaluate_learning_quality(records, groups, independent_review) -> list[str]` and `learning_review_hash(review) -> str`.

- [ ] **Step 1: Write failing learning-value tests**

```python
def test_flags_paraphrased_meaning_and_feature():
    record = ready_record(
        term="固本强基",
        meaning="基础已经牢固，并进一步得到强化。",
        distinctive_feature="巩固原有根基，同时强化既有基础。",
    )
    self.assertIn(
        "meaning and feature are near-duplicates: 固本强基",
        evaluate_learning_quality([record], [], empty_review()),
    )

def test_edge_requires_shared_basis_axis_and_both_landings():
    group = ready_group()
    group["minimum_differences"][0] = {
        "left": "因噎废食", "right": "投鼠忌器", "text": "二者含义不同。"
    }
    self.assertIn(
        "comparison edge lacks reviewed contrast contract",
        evaluate_learning_quality(records(), [group], empty_review()),
    )
```

Run and observe the missing module failure.

- [ ] **Step 2: Implement flagging plus explicit review resolution**

Use normalization and `difflib.SequenceMatcher` only to flag near-duplicates. Never auto-pass semantics. A resolved flag requires `subject_id`, `issue`, `decision`, a specific reason, and `reviewer_context_isolated=true`.

Each ready comparison edge requires `shared_basis`, `axis`, `left_landing`, `right_landing`, `evidence_ids`, and `review_status=pass`. Preserve existing member, order, graph, size, and overlap checks.

- [ ] **Step 3: Bind the independent review hash into the guard**

The guard must reject missing, changed, incomplete, or non-isolated reviews.

- [ ] **Step 4: Run tests and commit**

Run: `python -m unittest tests.maimemo_learning_rebuild.test_learning_quality tests.maimemo_learning_rebuild.test_review tests.maimemo_learning_rebuild.test_groups tests.maimemo_learning_rebuild.test_guard -v`

Commit: `feat: require independent learning quality review`

---

### Task 4: Add Blind-Solve Review for Application Cards

**Files:**
- Create: `maimemo_learning_rebuild/application_blind_review.py`
- Create: `tests/maimemo_learning_rebuild/test_application_blind_review.py`
- Modify: `maimemo_learning_rebuild/application_quality_gate.py`
- Modify: `maimemo_learning_rebuild/planning.py`

**Interfaces:**
- Produces: `evaluate_blind_reviews(final_cards, blind_review) -> list[str]` and `blind_review_hash(review) -> str`.

- [ ] **Step 1: Write failing blind-review tests**

```python
def test_rejects_disagreement_and_multiple_viable_options():
    review = blind_review(
        selected_answer="乙",
        viable_options=["甲", "乙"],
        decisive_clues=[],
        status="fail",
    )
    errors = evaluate_blind_reviews(final_cards(answer="甲"), review)
    self.assertIn("blind answer disagrees with frozen answer", errors)
    self.assertIn("blind review found multiple viable options", errors)
```

Also test missing and duplicate reviews, `expected_answer_seen=true`, missing distractor rejection, and repeated generic review reasons.

- [ ] **Step 2: Implement one review per application card**

A pass requires one viable option, matching selected answer, decisive clues, card-specific rejection for every distractor, `reviewer_context_isolated=true`, and `expected_answer_seen=false`.

- [ ] **Step 3: Bind blind review into planning**

Add `blind_review_hash` to the action plan. Reject any plan whose application review or blind review changed.

- [ ] **Step 4: Test and commit**

Run: `python -m unittest tests.maimemo_learning_rebuild.test_application_blind_review tests.maimemo_learning_rebuild.test_application_quality_gate tests.maimemo_learning_rebuild.test_planning -v`

Commit: `feat: require blind application review`

---

### Task 5: Build Route-Bound Release Manifest v2

**Files:**
- Create: `maimemo_learning_rebuild/release_manifest.py`
- Create: `tests/maimemo_learning_rebuild/test_release_manifest.py`
- Create: `tests/fixtures/release/source_inventory.json`
- Create: `tests/fixtures/release/final_cards.json`
- Create: `tests/fixtures/release/action_plan.json`
- Create: `tests/fixtures/release/quality_reports.json`

**Interfaces:**
- Produces: `build_release_manifest(inputs) -> dict`, `release_hash(manifest) -> str`, `validate_release_manifest(manifest, artifacts) -> list[str]`, and `transition_release_state(manifest, target_state, evidence) -> dict`.
- Route keys are exactly `comparison`, `base`, and `application`.

- [ ] **Step 1: Write failing route/hash tests**

```python
def test_route_or_count_change_invalidates_hash():
    manifest = complete_manifest()
    original = release_hash(manifest)
    manifest["chapter_routes"]["base"]["id"] = "other"
    self.assertNotEqual(original, release_hash(manifest))

def test_swapped_routes_fail_even_when_total_matches():
    manifest = complete_manifest()
    swap_base_and_application(manifest)
    self.assertIn(
        "chapter route type mismatch: base",
        validate_release_manifest(manifest, artifacts()),
    )
```

Add parameterized tests for every hashed field, duplicate chapter IDs, wrong names, wrong per-type counts, changed artifact bytes, and self-hash mismatch.

Add a state test proving `plan_frozen -> authorized` fails unless `ci_verified` and `awaiting_user_authorization` evidence exists, and proving any protected artifact change returns a new `draft` release rather than mutating an authorized release.

- [ ] **Step 2: Implement canonical manifest hashing**

Use UTF-8 JSON with sorted keys and compact separators. Include source, semantic, group, application, blind-review, card, snapshot, quality-report, engine-tree, and Skill-tree hashes; deck; three routes; before/after counts; action counts; state; and release ID.

Do not put a self-referential Git commit SHA inside the manifest. Bind the merged SHA externally through the GitHub deployment receipt.

- [ ] **Step 3: Validate card types against routes**

Count types from frozen cards and require exact equality with each route's expected create, update, unchanged, and after counts.

- [ ] **Step 4: Test and commit**

Run: `python -m unittest tests.maimemo_learning_rebuild.test_release_manifest -v`

Commit: `feat: freeze route-bound release manifests`

Perform a spec-compliance review followed by a code-quality review before Task 6.

---

### Task 6: Make Readback Route-Aware

**Files:**
- Modify: `maimemo_learning_rebuild/readback.py`
- Modify: `tests/maimemo_learning_rebuild/test_readback.py`

**Interfaces:**
- Produces: `verify_release_readback(live_deck, expected_cards, manifest) -> dict`.

- [ ] **Step 1: Write failing swapped-route tests**

```python
def test_correct_total_in_wrong_chapter_fails():
    live = complete_live_deck()
    swap_comparison_and_base_cards(live)
    report = verify_release_readback(live, expected_cards(), manifest())
    self.assertIn("wrong card type in comparison chapter", report["errors"])

def test_unparseable_target_card_fails():
    live = complete_live_deck(extra_content="plain text without heading")
    self.assertFalse(verify_release_readback(live, expected_cards(), manifest())["ok"])
```

- [ ] **Step 2: Implement per-chapter verification**

Resolve exact chapter ID and name, parse every card, require its route type, verify title/content/grammar/root references, and reject unparseable or unplanned cards. Bind the report to `release_hash` and GitHub run ID.

- [ ] **Step 3: Test and commit**

Run: `python -m unittest tests.maimemo_learning_rebuild.test_readback -v`

Commit: `feat: bind readback to release routes`

---

### Task 7: Build a Drift-Safe Resumable Writer

**Files:**
- Create: `maimemo_learning_rebuild/release_journal.py`
- Create: `maimemo_learning_rebuild/release_writer.py`
- Create: `tests/maimemo_learning_rebuild/test_release_writer.py`
- Modify: `maimemo_learning_rebuild/sync.py`
- Modify: `maimemo_learning_rebuild/api.py`
- Modify: `tests/maimemo_learning_rebuild/test_sync.py`

**Interfaces:**
- Produces: `execute_release(client, manifest, cards, journal, wait_policy) -> dict`.
- Produces CLI: `python -m maimemo_learning_rebuild.release_writer --release-dir PATH --approval-receipt PATH --journal PATH`.

- [ ] **Step 1: Write failing drift and ambiguous-result tests**

```python
def test_no_post_when_snapshot_drifted():
    client = FakeClient(live=changed_snapshot())
    with self.assertRaisesRegex(RuntimeError, "release target snapshot is stale"):
        execute_release(client, manifest(), cards(), MemoryJournal(), no_wait)
    self.assertEqual([], client.post_calls)

def test_timeout_after_success_reads_before_retry():
    client = FakeClient(create_side_effect=TimeoutAfterServerCommit())
    result = execute_release(client, manifest(), cards(), MemoryJournal(), no_wait)
    self.assertEqual(1, client.create_attempts)
    self.assertEqual(1, result["recovered_after_ambiguous_response"])
```

Also test same-title/same-content skip, same-title/different-content block, invalid root ID, 429 Retry-After, cancellation, and concurrent writer rejection.

- [ ] **Step 2: Remove generic environment-token construction**

Delete `MaimemoClient.from_environment`. Add `AmbiguousMutationError`, `RateLimitError(retry_after_seconds)`, and `PermanentApiError`. Ensure exception messages redact authorization values.

- [ ] **Step 3: Implement journal and phase order**

Use exact phases `precheck`, `comparisons`, `root_readback`, `bases`, `applications`, and `final_readback`. Journal only release hash, title, action, IDs, content hash, outcome, timestamp, and GitHub run ID.

- [ ] **Step 4: Implement safe mutation behavior**

Before every mutation, compare live stable-key content with frozen content. On ambiguous errors, read first and accept only an exact match. Respect server Retry-After for 429. Never blindly retry a mutation.

The CLI must load frozen files, validate the GitHub receipt through `release_environment`, open the protected client only after validation, execute the release, write a non-secret journal, and exit nonzero unless full route-aware readback succeeds. It must have no `--token` option and no local approval mode.

- [ ] **Step 5: Test and commit**

Run: `python -m unittest tests.maimemo_learning_rebuild.test_release_writer tests.maimemo_learning_rebuild.test_sync -v`

Commit: `feat: add drift-safe resumable release writer`

---

### Task 8: Enforce GitHub-Main Execution and Token Isolation

**Files:**
- Create: `maimemo_learning_rebuild/release_environment.py`
- Create: `tests/maimemo_learning_rebuild/test_release_environment.py`
- Modify: `maimemo_learning_rebuild/guard.py`

**Interfaces:**
- Produces: `ReleaseEnvironment.from_mapping(env)`, `validate_github_receipt(receipt, manifest)`, and `open_protected_client(environment)`.

- [ ] **Step 1: Write failing environment tests**

```python
def test_local_process_cannot_open_protected_client():
    env = complete_environment()
    env["GITHUB_ACTIONS"] = "false"
    with self.assertRaisesRegex(RuntimeError, "protected GitHub Actions environment required"):
        ReleaseEnvironment.from_mapping(env)

def test_pr_ref_cannot_authorize():
    env = complete_environment()
    env["GITHUB_REF"] = "refs/pull/1/merge"
    with self.assertRaisesRegex(RuntimeError, "exact main ref required"):
        validate_for_manifest(env, manifest())
```

Also test wrong SHA, release hash, run ID, environment name, failed deployment, and module import without token access.

- [ ] **Step 2: Implement strict protected-environment validation**

Require `GITHUB_ACTIONS=true`, `GITHUB_REF=refs/heads/main`, exact approved SHA, exact release hash, exact run ID, `GITHUB_ENVIRONMENT=maimemo-final-release`, and successful protected deployment metadata. Read the token only inside `open_protected_client` after every non-secret validation passes.

- [ ] **Step 3: Make legacy approval read-only**

Schema-v2 writes require a GitHub receipt. Historical `write_approval.json` may be rendered in reports but cannot authorize writes.

- [ ] **Step 4: Test and commit**

Run: `python -m unittest tests.maimemo_learning_rebuild.test_release_environment tests.maimemo_learning_rebuild.test_guard -v`

Commit: `feat: require protected github release environment`

---

### Task 9: Add the Protected GitHub Workflow and CODEOWNERS

**Files:**
- Create: `.github/workflows/maimemo-release.yml`
- Create: `.github/CODEOWNERS`
- Create: `tests/maimemo_learning_rebuild/test_release_workflow.py`
- Modify: `.github/workflows/learning-quality-gate.yml`

**Interfaces:**
- Workflow inputs: `release_path`, `release_hash`, `commit_sha`.
- Jobs: tokenless `prepare-release`, then protected `write-release`.

- [ ] **Step 1: Write failing static workflow tests**

```python
def test_token_only_exists_in_protected_job():
    workflow = load_workflow_text()
    self.assertEqual(1, workflow.count("secrets.MAIMEMO_TOKEN"))
    self.assertNotIn("secrets.MAIMEMO_TOKEN", extract_job(workflow, "prepare-release"))
    self.assertIn("maimemo-final-release", extract_job(workflow, "write-release"))

def test_pr_events_cannot_run_release():
    workflow = load_workflow_text()
    self.assertNotIn("pull_request_target", workflow)
    self.assertNotIn("pull_request:", workflow)
```

Also require exact SHA checkout, fixed `maimemo-production` concurrency, `cancel-in-progress: false`, read-only permissions, and `write-release` dependency on `prepare-release`.

- [ ] **Step 2: Implement tokenless `prepare-release`**

Check out exact SHA; verify it is current `main`; restrict path under `releases/`; recompute release hash; run all gates; write deck, routes, counts, privacy summary, hash, and SHA to the GitHub job summary; upload only non-secret reports.

- [ ] **Step 3: Implement protected `write-release`**

Declare the `maimemo-final-release` environment and fixed production concurrency. Re-check the exact SHA and release before passing the secret only to the writer step. Upload journal and readback report on success or failure.

- [ ] **Step 4: Protect critical files**

Add CODEOWNERS entries for the release workflow, API client, release environment, writer, manifest validator, and CODEOWNERS itself, all owned by `@qiaodawangwudi`.

- [ ] **Step 5: Expand CI**

Include currently omitted `test_review`, repository `test_skill_preflight`, and every new test module.

- [ ] **Step 6: Test and commit**

Run the workflow test, then `python -m unittest discover -s tests -t . -p 'test_*.py' -q`.

Commit: `feat: add protected github maimemo release workflow`

Perform spec-compliance and code-quality reviews before Task 10.

---

### Task 10: Install the Canonical Skill by Verified Hash

**Files:**
- Create: `skills/verbal-maimemo-cards/scripts/install_or_verify.py`
- Create: `tests/maimemo_learning_rebuild/test_skill_install.py`

**Interfaces:**
- Produces: `compute_skill_hash(path)`, `verify_install(source, target)`, `install(source, target)`, and CLI modes `--install` and `--verify`.

- [ ] **Step 1: Write failing installation tests**

```python
def test_refuses_unrecorded_target_change(tmp_path):
    source, target = prepared_skill_dirs(tmp_path)
    (target / "SKILL.md").write_text("locally changed", encoding="utf-8")
    with self.assertRaisesRegex(RuntimeError, "installed skill has unrecorded changes"):
        install(source, target)

def test_atomic_install_matches_canonical_hash(tmp_path):
    source, target = prepared_skill_dirs(tmp_path, empty_target=True)
    receipt = install(source, target)
    self.assertEqual(compute_skill_hash(source), receipt["installed_hash"])
```

- [ ] **Step 2: Implement safe atomic installation**

Hash relative paths and bytes, excluding cache and receipt files. Stage in a sibling temporary directory, verify, then atomically replace only the resolved exact target. Refuse to overwrite unrecorded changes. Record canonical hash and merged commit.

- [ ] **Step 3: Test, validate, and commit**

Run the install test and `quick_validate.py`. Commit: `feat: install canonical skill with hash verification`.

Do not install personally until the complete shadow release passes.

---

### Task 11: Prove Mutation Resistance and Full Recovery

**Files:**
- Create: `tests/maimemo_learning_rebuild/test_release_mutations.py`
- Create: `tests/maimemo_learning_rebuild/test_shadow_release.py`
- Create: `tests/fixtures/release/live_deck_empty.json`
- Create: `tests/fixtures/release/live_deck_partial.json`

**Interfaces:**
- Consumes Task 5 fixtures and fake API transport.
- Produces named gate failures for every protected-field mutation and a duplicate-free interrupted release recovery.

- [ ] **Step 1: Add mutation tests**

Parameterize one-character content change, missing application decision, duplicate base, copied minimum difference, swapped chapter IDs, changed expected count, stale snapshot, changed engine tree, and forged local approval. Every mutation must produce a specific named gate error.

- [ ] **Step 2: Add the interrupted shadow release**

Simulate two comparison creates, root readback, one base server commit with lost response, process stop, immutable restart, exact skips, remaining base and application writes, and final three-route readback. Assert exact POST counts and zero duplicates.

- [ ] **Step 3: Run mutation, shadow, and full tests**

Run both focused modules and the full discovery command. Expected: all pass without a live token or live endpoint.

- [ ] **Step 4: Commit**

Commit: `test: prove protected release recovery and mutation resistance`

Perform spec-compliance and code-quality reviews before Task 12.

---

### Task 12: Audit Public Artifacts and Mark the Historical Boundary

**Files:**
- Create: `maimemo_learning_rebuild/privacy_audit.py`
- Create: `tests/maimemo_learning_rebuild/test_privacy_audit.py`
- Create: `docs/security/public-artifact-inventory.md`
- Modify: `maimemo_learning_rebuild/artifacts/final_acceptance_report.md`

**Interfaces:**
- Produces: `audit_public_tree(root) -> dict` and reviewed classifications `public_ok`, `remove_before_merge`, or `derived_short_quote`.

- [ ] **Step 1: Write failing path and secret-field tests**

```python
def test_rejects_absolute_path_and_secret_field(tmp_path):
    write(tmp_path / "bad.json", '{"source":"C:/Users/admin/Desktop/a.docx","token":"redacted"}')
    report = audit_public_tree(tmp_path)
    self.assertTrue(any("absolute local path" in error for error in report["errors"]))
    self.assertTrue(any("secret-like field" in error for error in report["errors"]))
```

Detect secret-like key names without printing their values.

- [ ] **Step 2: Audit the tracked tree without automatic deletion**

Inventory code, derived cards, evidence excerpts, reports, and full source text. Give each item a proposed classification and reason. User intent controls removal decisions.

- [ ] **Step 3: Record the historical release boundary**

State that the 869-card release predates protected token isolation and must not be reissued. New schema-v2 releases use only the protected path.

- [ ] **Step 4: Test and commit**

Run the privacy test. Commit: `chore: audit public release artifacts`.

---

### Task 13: Configure Protection, Rotate the Token, and Install

**Files:**
- GitHub settings only: branch rules, environment rules, environment secret.
- Install source: `skills/verbal-maimemo-cards`.
- Install target: `C:\Users\admin\.codex\skills\verbal-maimemo-cards`.

**Interfaces:**
- Consumes merged, fully tested security code.
- Produces verified protections, a newly rotated environment-only token, and an installation receipt.

- [ ] **Step 1: Run final repository verification**

Run full unittest discovery, Skill validation, `git diff --check`, and `git status --short --branch`. Require all green and a clean planned branch.

- [ ] **Step 2: Merge security code before adding the secret**

The repository owner reviews the release workflow, API client, environment validator, writer, manifest validator, and CODEOWNERS. Merge only after every PR check succeeds.

- [ ] **Step 3: Configure exact protections**

Verify:

```text
main requires pull requests and all quality checks
security-critical changes require CODEOWNERS review
maimemo-final-release requires qiaodawangwudi review
maimemo-final-release allows only main
refs/pull/*/merge is rejected
prevent self-review is disabled for the sole repository owner
```

Dispatch a tokenless smoke release. It must show the exact release hash and SHA while waiting for environment approval.

- [ ] **Step 4: Rotate and isolate the token**

Revoke the token previously pasted in chat. Create a new token and store it only as the `MAIMEMO_TOKEN` secret of `maimemo-final-release`. Do not send it through Codex or store it locally.

- [ ] **Step 5: Prove rejected authorization cannot write**

Reject or cancel a fixture deployment and verify the writer never starts, no step receives the token, no POST occurs, and the check is failed or cancelled. Use a fake endpoint, never the live deck.

- [ ] **Step 6: Install and verify the Skill**

Run the installer with exact source and target, then run verify mode. Require matching canonical and installed hashes plus a receipt naming the merged commit.

- [ ] **Step 7: Produce non-secret acceptance evidence**

Report test commands and totals, Skill baseline and upgraded results, mutation and shadow results, GitHub protection evidence, secret location by name only, Skill hashes, no rewrite of the historical 869 cards, and absence of any local live-write path.

Commit: `docs: verify protected maimemo release system`

---

## Final Verification Matrix

| Requirement | Required proof |
|---|---|
| Existing cards receive semantic reconciliation | action-plan tests and historical pressure scenario |
| Groups are not accepted by structure alone | reviewed edge-contract tests |
| Application answers are independently tested | blind-review tests |
| Three routes belong to authorization | manifest mutation tests |
| Swapped routes fail despite correct totals | route-aware readback tests |
| Content changes invalidate authorization | release-hash tests |
| GitHub failure prevents token access | environment and rejected-deployment tests |
| Codex has no local token path | API and workflow boundary tests |
| Ambiguous network outcomes do not duplicate | timeout-after-commit shadow test |
| Partial releases resume safely | complete shadow release |
| Public Git does not silently expose local material | inventory and privacy audit |
| Installed Skill cannot drift | installer hash and receipt |
| Completion means online equality | release-bound full readback |

## Execution Rule

Execute Tasks 1 through 13 in order. Each task completes its own RED-GREEN-REFACTOR cycle and commit. After Tasks 5, 9, and 11, perform spec-compliance review followed by code-quality review. Do not configure or rotate the real token until Task 13, after implementation and shadow tests are merged and trusted.
