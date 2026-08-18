import copy
import unittest

from maimemo_learning_rebuild.reconciliation import (
    build_library_reconciliation,
    reconciliation_hash,
    validate_library_reconciliation,
)


def card(card_id, title):
    return {
        "id": card_id,
        "root_id": f"mkjr_{card_id}",
        "grammar_version": 3,
        "content": f"[P#H1#{title}]\n\n问题\n\n---\n\n内容",
    }


def complete_snapshot(cards):
    return {
        "snapshot_scope": "full_library",
        "pagination_complete": True,
        "reported_total": len(cards),
        "cards": cards,
    }


def semantic(term, sense="课程义::001"):
    return {
        "term": term,
        "sense_id": f"{term}::{sense}",
        "status": "ready",
    }


class LibraryReconciliationTests(unittest.TestCase):
    def test_single_same_term_card_requires_same_sense_confirmation_before_reuse(self):
        snapshot = complete_snapshot([card("c1", "基础词义｜甲")])
        blocked = build_library_reconciliation(snapshot, [semantic("甲")])
        report = build_library_reconciliation(
            snapshot,
            [semantic("甲")],
            resolutions={
                "甲::课程义::001": {
                    "decision": "reuse_existing",
                    "canonical_card_id": "c1",
                    "retire_card_ids": [],
                    "reason": "已核对旧卡词义与当前课程义项相同，复用并更新主卡。",
                }
            },
        )

        self.assertEqual("blocked", blocked["status"])
        self.assertEqual("manual_review", blocked["entries"][0]["decision"])
        self.assertEqual("passed", report["status"])
        self.assertEqual("reuse_existing", report["entries"][0]["decision"])
        self.assertEqual("c1", report["entries"][0]["canonical_card_id"])

    def test_reviewed_alias_can_find_an_existing_variant_card(self):
        snapshot = complete_snapshot([card("c1", "基础词义｜执著")])
        record = semantic("执着")
        record["aliases"] = ["执著"]
        report = build_library_reconciliation(snapshot, [record])

        self.assertEqual(["c1"], report["entries"][0]["candidate_card_ids"])
        self.assertEqual("manual_review", report["entries"][0]["decision"])
        self.assertIn("执著", report["entries"][0]["match_terms"])

    def test_absent_term_gets_create_only_after_full_snapshot_no_match(self):
        snapshot = complete_snapshot([card("c1", "基础词义｜甲")])
        report = build_library_reconciliation(snapshot, [semantic("乙")])

        self.assertEqual("passed", report["status"])
        self.assertEqual("create_new", report["entries"][0]["decision"])
        self.assertEqual([], report["entries"][0]["candidate_card_ids"])
        self.assertEqual(report["snapshot_hash"], report["entries"][0]["proof_snapshot_hash"])

    def test_normalized_variant_title_is_reused(self):
        snapshot = complete_snapshot([card("c1", "基础词义｜ Ａ 词 ")])
        report = build_library_reconciliation(snapshot, [semantic("A词")])

        self.assertEqual("manual_review", report["entries"][0]["decision"])
        self.assertEqual(["c1"], report["entries"][0]["candidate_card_ids"])

    def test_multiple_existing_cards_block_until_canonical_merge_is_chosen(self):
        snapshot = complete_snapshot(
            [
                card("c1", "基础词义｜甲"),
                card("c2", "基础词义｜ 甲 "),
            ]
        )
        blocked = build_library_reconciliation(snapshot, [semantic("甲")])
        resolved = build_library_reconciliation(
            snapshot,
            [semantic("甲")],
            resolutions={
                "甲::课程义::001": {
                    "decision": "merge_existing",
                    "canonical_card_id": "c1",
                    "retire_card_ids": ["c2"],
                    "reason": "c1保留完整学习内容；c2内容并入后迁移引用并待停用。",
                }
            },
        )

        self.assertEqual("blocked", blocked["status"])
        self.assertEqual("manual_review", blocked["entries"][0]["decision"])
        self.assertEqual("passed", resolved["status"])
        self.assertEqual("merge_existing", resolved["entries"][0]["decision"])
        self.assertEqual(["c2"], resolved["entries"][0]["retire_card_ids"])

    def test_same_term_different_senses_block_instead_of_overwriting(self):
        snapshot = complete_snapshot([card("c1", "基础词义｜甲")])
        report = build_library_reconciliation(
            snapshot,
            [semantic("甲", "义项一"), semantic("甲", "义项二")],
        )

        self.assertEqual("blocked", report["status"])
        self.assertTrue(
            all(entry["decision"] == "manual_review" for entry in report["entries"])
        )
        self.assertIn("同词存在多个义项", report["errors"][0])

    def test_invalid_merge_that_omits_a_duplicate_is_rejected(self):
        snapshot = complete_snapshot(
            [
                card("c1", "基础词义｜甲"),
                card("c2", "基础词义｜甲 "),
                card("c3", "基础词义｜ 甲"),
            ]
        )
        report = build_library_reconciliation(
            snapshot,
            [semantic("甲")],
            resolutions={
                "甲::课程义::001": {
                    "decision": "merge_existing",
                    "canonical_card_id": "c1",
                    "retire_card_ids": ["c2"],
                    "reason": "错误地遗漏一张重复卡。",
                }
            },
        )

        self.assertEqual("blocked", report["status"])
        self.assertIn("merge must account for every duplicate candidate", report["errors"])

    def test_snapshot_or_registry_drift_invalidates_reconciliation(self):
        snapshot = complete_snapshot([])
        records = [semantic("甲")]
        report = build_library_reconciliation(snapshot, records)
        changed_snapshot = complete_snapshot([card("c1", "基础词义｜乙")])
        changed_records = [semantic("乙")]

        self.assertIn(
            "reconciliation snapshot hash mismatch",
            validate_library_reconciliation(report, changed_snapshot, records),
        )
        self.assertIn(
            "reconciliation semantic registry hash mismatch",
            validate_library_reconciliation(report, snapshot, changed_records),
        )

        tampered = copy.deepcopy(report)
        tampered["entries"][0]["decision"] = "manual_review"
        self.assertNotEqual(reconciliation_hash(tampered), tampered["reconciliation_hash"])
        self.assertIn(
            "reconciliation hash mismatch",
            validate_library_reconciliation(tampered, snapshot, records),
        )

    def test_rehashing_false_no_candidate_proof_does_not_allow_create(self):
        snapshot = complete_snapshot([card("c1", "基础词义｜甲")])
        records = [semantic("甲")]
        report = build_library_reconciliation(snapshot, records)
        entry = report["entries"][0]
        entry["candidate_card_ids"] = []
        entry["candidate_titles"] = []
        entry["decision"] = "create_new"
        entry["canonical_card_id"] = ""
        report["reconciliation_hash"] = reconciliation_hash(report)

        errors = validate_library_reconciliation(report, snapshot, records)

        self.assertIn("reconciliation candidates differ from full snapshot: 甲::课程义::001", errors)
        self.assertIn("create_new has a reusable same-term card: 甲::课程义::001", errors)

    def test_duplicate_snapshot_card_ids_fail_closed(self):
        snapshot = complete_snapshot(
            [
                card("same", "基础词义｜甲"),
                card("same", "基础词义｜乙"),
            ]
        )

        with self.assertRaisesRegex(ValueError, "duplicate snapshot card_id"):
            build_library_reconciliation(snapshot, [semantic("甲")])

    def test_rehashed_multiple_senses_cannot_turn_into_two_creates(self):
        snapshot = complete_snapshot([])
        records = [semantic("甲", "义项一"), semantic("甲", "义项二")]
        report = build_library_reconciliation(snapshot, records)
        for entry in report["entries"]:
            entry["decision"] = "create_new"
        report["status"] = "passed"
        report["errors"] = []
        report["reconciliation_hash"] = reconciliation_hash(report)

        errors = validate_library_reconciliation(report, snapshot, records)

        self.assertIn("multiple senses require one shared layer_senses decision: 甲", errors)

    def test_one_existing_card_cannot_belong_to_two_semantic_identities(self):
        snapshot = complete_snapshot([card("c1", "基础词义｜甲")])
        first = semantic("甲")
        second = semantic("乙")
        second["aliases"] = ["甲"]
        report = build_library_reconciliation(
            snapshot,
            [first, second],
            resolutions={
                first["sense_id"]: {
                    "decision": "reuse_existing",
                    "canonical_card_id": "c1",
                    "retire_card_ids": [],
                    "reason": "确认甲义项。",
                },
                second["sense_id"]: {
                    "decision": "reuse_existing",
                    "canonical_card_id": "c1",
                    "retire_card_ids": [],
                    "reason": "错误地把同一旧卡也分给乙。",
                },
            },
        )

        self.assertEqual("blocked", report["status"])
        self.assertIn("card_id assigned to multiple semantic identities: c1", report["errors"])


if __name__ == "__main__":
    unittest.main()
