import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from maimemo_learning_rebuild.application_blind_review import (
    blind_review_hash,
    evaluate_blind_reviews,
)
from maimemo_learning_rebuild.application_quality_gate import (
    application_review_hash,
    evaluate_application_gate,
)


TITLE = "语境应用｜甲、乙｜行动取舍"


def final_cards(*, title=TITLE, answer="甲", distractor="乙", card_id=""):
    return {
        "cards": [
            {
                "title": title,
                "card_id": card_id,
                "card_type": "application",
                "application": {
                    "prompt": "面对可能出现的小问题，负责人索性停止了本来必须继续推进的工作。",
                    "options": [answer, distractor],
                    "answer": answer,
                },
            }
        ]
    }


def review_entry(
    *,
    title=TITLE,
    selected_answer="甲",
    viable_options=None,
    decisive_clues=None,
    distractor_rejections=None,
    status="pass",
    reviewer_context_isolated=True,
    expected_answer_seen=False,
):
    return {
        "card_title": title,
        "status": status,
        "selected_answer": selected_answer,
        "viable_options": ["甲"] if viable_options is None else viable_options,
        "decisive_clues": (
            ["担心出现问题后停止本应继续的工作"]
            if decisive_clues is None
            else decisive_clues
        ),
        "distractor_rejections": (
            {"乙": "乙要求顾忌会伤及关联对象，题干没有出现这种关联对象。"}
            if distractor_rejections is None
            else distractor_rejections
        ),
        "reviewer_context_isolated": reviewer_context_isolated,
        "expected_answer_seen": expected_answer_seen,
    }


def blind_review(**entry_overrides):
    return {
        "complete": True,
        "reviews": [review_entry(**entry_overrides)],
    }


class ApplicationBlindReviewTests(unittest.TestCase):
    def test_rejects_disagreement_and_multiple_viable_options(self):
        review = blind_review(
            selected_answer="乙",
            viable_options=["甲", "乙"],
            decisive_clues=[],
            status="fail",
        )

        errors = evaluate_blind_reviews(final_cards(answer="甲"), review)

        self.assertIn("blind answer disagrees with frozen answer", errors)
        self.assertIn("blind review found multiple viable options", errors)

    def test_requires_exactly_one_review_per_application_card(self):
        missing_errors = evaluate_blind_reviews(
            final_cards(), {"complete": True, "reviews": []}
        )
        duplicate = blind_review()
        duplicate["reviews"].append(copy.deepcopy(duplicate["reviews"][0]))
        duplicate_errors = evaluate_blind_reviews(final_cards(), duplicate)

        self.assertIn(f"missing blind review: {TITLE}", missing_errors)
        self.assertIn(f"duplicate blind review: {TITLE}", duplicate_errors)

    def test_rejects_unknown_review_and_incomplete_root(self):
        review = blind_review(title="语境应用｜未知｜额外记录")
        review["complete"] = 1

        errors = evaluate_blind_reviews(final_cards(), review)

        self.assertIn("blind review is not marked complete", errors)
        self.assertIn("unknown blind review: 语境应用｜未知｜额外记录", errors)

    def test_rejects_review_that_saw_expected_answer_or_is_not_isolated(self):
        review = blind_review(
            expected_answer_seen=True,
            reviewer_context_isolated=False,
        )

        errors = evaluate_blind_reviews(final_cards(), review)

        self.assertIn(f"blind review saw expected answer: {TITLE}", errors)
        self.assertIn(f"blind review is not context-isolated: {TITLE}", errors)

    def test_requires_card_specific_rejection_for_every_distractor(self):
        review = blind_review(distractor_rejections={})

        errors = evaluate_blind_reviews(final_cards(), review)

        self.assertIn(f"blind review lacks distractor rejection: {TITLE}:乙", errors)

    def test_requires_pass_status_selected_viable_answer_and_decisive_clues(self):
        review = blind_review(
            status="fail",
            viable_options=["乙"],
            decisive_clues=[],
        )

        errors = evaluate_blind_reviews(final_cards(), review)

        self.assertIn(f"blind review status is not pass: {TITLE}", errors)
        self.assertIn(f"blind selected answer is not the viable option: {TITLE}", errors)
        self.assertIn(f"blind review lacks decisive clues: {TITLE}", errors)

    def test_rejects_non_json_types_instead_of_coercing_them(self):
        review = blind_review(
            viable_options="甲",
            decisive_clues="担心后停止",
            reviewer_context_isolated=1,
            expected_answer_seen=0,
        )

        errors = evaluate_blind_reviews(final_cards(), review)

        self.assertIn(f"blind review viable_options must be a list: {TITLE}", errors)
        self.assertIn(f"blind review decisive_clues must be a list: {TITLE}", errors)
        self.assertIn(
            f"blind review reviewer_context_isolated must be true: {TITLE}", errors
        )
        self.assertIn(
            f"blind review expected_answer_seen must be false: {TITLE}", errors
        )

    def test_rejects_non_object_review_artifact_without_raising(self):
        self.assertEqual(
            ["blind review must be an object"],
            evaluate_blind_reviews(final_cards(), []),
        )

    def test_application_gate_rejects_non_object_blind_review_without_raising(self):
        application_review = {"complete": True, "decisions": []}
        plan = {
            "application_review_hash": application_review_hash(application_review),
            "actions": [],
        }

        errors = evaluate_application_gate(
            {},
            {},
            application_review,
            {"cards": []},
            plan,
            [],
        )

        self.assertIn("blind review must be an object", errors)
        self.assertIn("action plan is not bound to current blind review", errors)

    def test_rejects_repeated_generic_review_reasons(self):
        cards = final_cards()
        cards["cards"].append(
            final_cards(title="语境应用｜丙、丁｜行动取舍", answer="丙", distractor="丁")[
                "cards"
            ][0]
        )
        generic = "{term}只是不满足这道题的整体判断要求，因此这里不能选。"
        review = {
            "complete": True,
            "reviews": [
                review_entry(distractor_rejections={"乙": generic.format(term="乙")}),
                review_entry(
                    title="语境应用｜丙、丁｜行动取舍",
                    selected_answer="丙",
                    viable_options=["丙"],
                    distractor_rejections={"丁": generic.format(term="丁")},
                ),
            ],
        }

        errors = evaluate_blind_reviews(cards, review)

        self.assertTrue(
            any(error.startswith("blind review repeats generic reason:") for error in errors),
            errors,
        )

    def test_rejects_generic_template_when_answer_distractor_title_and_id_change(self):
        second_title = "语境应用｜丙、丁｜行动取舍"
        cards = final_cards(card_id="card-101")
        cards["cards"].append(
            final_cards(
                title=second_title,
                answer="丙",
                distractor="丁",
                card_id="card-202",
            )["cards"][0]
        )
        review = {
            "complete": True,
            "reviews": [
                review_entry(
                    distractor_rejections={
                        "乙": f"乙只因与甲相比不具备被选中的条件，所以本题应当排除乙。{TITLE}，编号101。"
                    }
                ),
                review_entry(
                    title=second_title,
                    selected_answer="丙",
                    viable_options=["丙"],
                    distractor_rejections={
                        "丁": f"丁只因与丙相比不具备被选中的条件，所以本题应当排除丁。{second_title}，编号202。"
                    },
                ),
            ],
        }

        errors = evaluate_blind_reviews(cards, review)

        self.assertTrue(
            any(error.startswith("blind review repeats generic reason:") for error in errors),
            errors,
        )

    def test_rejects_single_card_reason_made_only_from_variables_and_punctuation(self):
        cards = final_cards(card_id="card-101")
        reasons = (
            f"{TITLE}｜甲｜乙｜card-101｜2026｜乙",
            f"【{TITLE}】（甲）——乙；card-101；2026；乙！！！",
        )

        for reason in reasons:
            with self.subTest(reason=reason):
                review = blind_review(distractor_rejections={"乙": reason})
                errors = evaluate_blind_reviews(cards, review)
                self.assertIn(
                    f"blind review distractor rejection is not card-specific: {TITLE}:乙",
                    errors,
                )

    def test_rejects_duplicate_application_card_identity_itself(self):
        cards = final_cards(card_id="same-card")
        cards["cards"].append(copy.deepcopy(cards["cards"][0]))

        errors = evaluate_blind_reviews(cards, blind_review())

        self.assertIn(f"duplicate application card title: {TITLE}", errors)
        self.assertIn("duplicate application card id: same-card", errors)

    def test_rejects_nan_and_nested_non_json_values_without_raising(self):
        for malformed in (
            {"complete": True, "reviews": [], "score": float("nan")},
            {"complete": True, "reviews": [], "extra": ("tuple",)},
            {"complete": True, "reviews": [], 1: "non-string-key"},
        ):
            with self.subTest(malformed=malformed):
                errors = evaluate_blind_reviews({"cards": []}, malformed)
                self.assertIn("blind review is not strict JSON", errors)

        final_card_errors = evaluate_blind_reviews(
            {"cards": [], "score": float("inf")},
            {"complete": True, "reviews": []},
        )
        self.assertIn("final cards are not strict JSON", final_card_errors)

    def test_application_gate_rejects_scalar_top_level_inputs_without_raising(self):
        valid_review = {"complete": True, "decisions": []}
        valid_blind = {"complete": True, "reviews": []}
        valid_plan = {
            "application_review_hash": application_review_hash(valid_review),
            "blind_review_hash": blind_review_hash(valid_blind),
            "actions": [],
        }
        fixtures = (
            ([], {}, valid_review, {"cards": []}, valid_plan, valid_blind),
            ({}, 1, valid_review, {"cards": []}, valid_plan, valid_blind),
            ({}, {}, "review", {"cards": []}, valid_plan, valid_blind),
            ({}, {}, valid_review, "cards", valid_plan, valid_blind),
            ({}, {}, valid_review, {"cards": []}, [], valid_blind),
            ({}, {}, valid_review, {"cards": []}, valid_plan, float("nan")),
        )

        for args in fixtures:
            with self.subTest(args=args):
                errors = evaluate_application_gate(*args)
                self.assertTrue(errors)

    def test_application_gate_cli_rejects_broken_json_without_traceback(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifact_dir = Path(temporary)
            payloads = {
                "master_semantic_registry.json": {"records": []},
                "group_registry.json": {"groups": []},
                "application_review.json": {"complete": True, "decisions": []},
                "final_cards.json": {"cards": []},
                "action_plan.json": {"actions": []},
            }
            for name, payload in payloads.items():
                (artifact_dir / name).write_text(
                    json.dumps(payload, ensure_ascii=False), encoding="utf-8"
                )
            (artifact_dir / "application_blind_review.json").write_text(
                '{"complete": true, "reviews": [}', encoding="utf-8"
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "maimemo_learning_rebuild.application_quality_gate",
                    "--artifact-dir",
                    str(artifact_dir),
                ],
                cwd=Path(__file__).parents[2],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("invalid strict JSON", result.stdout)

    def test_accepts_complete_card_specific_blind_review(self):
        self.assertEqual([], evaluate_blind_reviews(final_cards(), blind_review()))

    def test_hash_is_canonical_and_excludes_its_own_field(self):
        first = {"complete": True, "reviews": []}
        second = {"reviews": [], "complete": True, "review_hash": "old"}

        self.assertEqual(
            "7546b1f92b35ad4bb47a115601096a5652d49f9d627b6ae44c1a902fa51f4fa9",
            blind_review_hash(first),
        )
        self.assertEqual(blind_review_hash(first), blind_review_hash(second))


if __name__ == "__main__":
    unittest.main()
