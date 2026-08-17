import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from maimemo_learning_rebuild.application_blind_review import blind_review_hash
from maimemo_learning_rebuild.application_quality_gate import (
    application_review_hash,
    evaluate_application_gate,
)
from maimemo_learning_rebuild.learning_quality import evaluate_learning_quality
from maimemo_learning_rebuild.release_manifest import (
    release_hash,
    validate_release_manifest,
)
from maimemo_learning_rebuild.release_writer import (
    _create_protected_client,
    _load_frozen_release,
    execute_release,
)
from tests.maimemo_learning_rebuild.test_learning_quality import (
    empty_review,
    ready_group,
    ready_record,
)
from tests.maimemo_learning_rebuild.test_release_manifest import (
    artifacts as release_artifacts,
    complete_manifest,
)
from tests.maimemo_learning_rebuild.test_release_writer import (
    FROZEN_FILENAMES,
    FakeClient,
    MemoryJournal,
    card,
    live_card,
    live_deck,
    manifest as writer_manifest,
    no_wait,
)


def _raised_error(operation):
    try:
        operation()
    except (RuntimeError, TypeError, ValueError) as error:
        return [str(error)]
    return []


def _write_release(release_dir: Path) -> None:
    current_artifacts = release_artifacts()
    (release_dir / "release_manifest.json").write_text(
        json.dumps(complete_manifest(), ensure_ascii=False), encoding="utf-8"
    )
    for key, raw in current_artifacts.items():
        (release_dir / FROZEN_FILENAMES[key]).write_bytes(raw)


def _frozen_byte_mutation(artifact: str) -> list[str]:
    with tempfile.TemporaryDirectory() as temporary:
        release_dir = Path(temporary)
        _write_release(release_dir)
        path = release_dir / FROZEN_FILENAMES[artifact]
        raw = path.read_bytes()
        if artifact == "final_cards":
            changed = raw.replace(
                b'"content": "comparison"',
                b'"content": "comparisoN"',
                1,
            )
            if changed == raw:
                raise AssertionError("final-cards fixture lacks the mutation target")
            path.write_bytes(changed)
        else:
            path.write_bytes(raw + b"x")
        return _raised_error(lambda: _load_frozen_release(release_dir))


def _missing_application_decision() -> list[str]:
    registry = {
        "records": [
            {"term": "甲", "sense_id": "甲::课程义::001", "status": "ready"}
        ]
    }
    review = {"complete": True, "decisions": []}
    blind = {"complete": True, "reviews": []}
    plan = {
        "application_review_hash": application_review_hash(review),
        "blind_review_hash": blind_review_hash(blind),
        "actions": [],
    }
    return evaluate_application_gate(
        registry, {"groups": []}, review, {"cards": []}, plan, blind
    )


def _duplicate_base() -> list[str]:
    current_artifacts = release_artifacts()
    payload = json.loads(current_artifacts["final_cards"].decode("utf-8"))
    base = next(card for card in payload["cards"] if card["card_type"] == "base")
    payload["cards"].append(copy.deepcopy(base))
    current_artifacts["final_cards"] = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    current = complete_manifest()
    current["artifact_hashes"]["final_cards"] = hashlib.sha256(
        current_artifacts["final_cards"]
    ).hexdigest()
    current["release_hash"] = release_hash(current)
    return validate_release_manifest(current, current_artifacts)


def _comparison_quality(text: str) -> list[str]:
    left = ready_record(
        term="因噎废食",
        meaning="因害怕出问题而停止本来应该继续的行动。",
        distinctive_feature="结果是把必要行动整体停止。",
    )
    right = ready_record(
        term="投鼠忌器",
        meaning="因顾忌伤及关联对象而不敢采取行动。",
        distinctive_feature="顾忌点落在行动可能牵连的对象。",
    )
    group = ready_group()
    group["minimum_differences"][0]["text"] = text
    return evaluate_learning_quality([left, right], [group], empty_review())


def _copied_minimum_difference() -> list[str]:
    return _comparison_quality("因害怕出问题而停止本来应该继续的行动。")


def _manifest_mutation(mutator) -> list[str]:
    current = complete_manifest()
    mutator(current)
    current["release_hash"] = release_hash(current)
    return validate_release_manifest(current, release_artifacts())


def _swapped_chapter_ids() -> list[str]:
    def mutate(current):
        comparison = current["chapter_routes"]["comparison"]
        base = current["chapter_routes"]["base"]
        comparison["id"], base["id"] = base["id"], comparison["id"]

    return _manifest_mutation(mutate)


def _changed_expected_count() -> list[str]:
    def mutate(current):
        current["chapter_routes"]["application"]["counts"]["after"] += 1

    return _manifest_mutation(mutate)


def _stale_snapshot() -> list[str]:
    title = "基础词义｜甲"
    frozen_content = "[P#H1#基础词义｜甲]\n---\n冻结内容"
    changed_content = "[P#H1#基础词义｜甲]\n---\n外部改动"
    frozen_card = card(
        title,
        "base",
        frozen_content,
        action="unchanged",
        card_id="base-1",
    )
    snapshot = live_deck([live_card("base-1", title, "base", frozen_content)])
    live = live_deck([live_card("base-1", title, "base", changed_content)])
    return _raised_error(
        lambda: execute_release(
            FakeClient(live),
            writer_manifest(snapshot, [frozen_card]),
            [frozen_card],
            MemoryJournal(),
            no_wait,
        )
    )


def _forged_local_approval() -> list[str]:
    forged = {
        "ok": True,
        "receipt": {"source": "local"},
        "release_id": "release-2026-08-17-001",
        "release_hash": "a" * 64,
        "github_run_id": "local",
    }
    with patch.dict(os.environ, {}, clear=True):
        return _raised_error(lambda: _create_protected_client(complete_manifest(), forged))


class ReleaseMutationTests(unittest.TestCase):
    def test_copied_definition_wrappers_and_concatenations_fail_without_blocking_real_contrast(self):
        copied_error = (
            "minimum difference copies definition: g-risk 因噎废食 投鼠忌器"
        )
        copied_cases = (
            (
                "concatenated meanings",
                "因害怕出问题而停止本来应该继续的行动。"
                "因顾忌伤及关联对象而不敢采取行动。",
            ),
            (
                "difference wrapper",
                "二者差异在于：因害怕出问题而停止本来应该继续的行动。",
            ),
            (
                "paraphrase wrapper",
                "也就是说，因害怕出问题而停止本来应该继续的行动。",
            ),
            (
                "near copy with short rewrite",
                "二者差异在于：因害怕问题而停止本来应该继续的行动。",
            ),
            (
                "concatenated features",
                "结果是把必要行动整体停止；顾忌点落在行动可能牵连的对象。",
            ),
        )
        for label, text in copied_cases:
            with self.subTest(copied_form=label):
                errors = _comparison_quality(text)
                self.assertIn(copied_error, errors, errors)

        genuine = _comparison_quality(
            "因噎废食的决定性结果是放弃必要行动；"
            "投鼠忌器的决定性顾虑是行动会牵连特定对象。"
        )
        self.assertNotIn(copied_error, genuine, genuine)

    def test_every_protected_mutation_has_a_named_gate_failure(self):
        cases = (
            (
                "one-character content change",
                lambda: _frozen_byte_mutation("final_cards"),
                "artifact byte hash mismatch: final_cards",
            ),
            (
                "missing application decision",
                _missing_application_decision,
                "application review missing semantic decisions: 1",
            ),
            (
                "duplicate base",
                _duplicate_base,
                "duplicate frozen card stable_card_key: base:甲",
            ),
            (
                "copied minimum difference",
                _copied_minimum_difference,
                "minimum difference copies definition: g-risk 因噎废食 投鼠忌器",
            ),
            (
                "swapped chapter ids",
                _swapped_chapter_ids,
                "chapter route id mismatch: comparison",
            ),
            (
                "changed expected count",
                _changed_expected_count,
                "chapter route count mismatch: application.after",
            ),
            (
                "stale snapshot",
                _stale_snapshot,
                "release target snapshot is stale: 基础词义｜甲",
            ),
            (
                "changed engine tree",
                lambda: _frozen_byte_mutation("engine_tree"),
                "artifact byte hash mismatch: engine_tree",
            ),
            (
                "forged local approval",
                _forged_local_approval,
                "GitHub release environment receipt is not approved",
            ),
        )
        for label, operation, expected in cases:
            with self.subTest(mutation=label):
                errors = operation()
                self.assertTrue(
                    any(expected in error for error in errors),
                    errors,
                )


if __name__ == "__main__":
    unittest.main()
