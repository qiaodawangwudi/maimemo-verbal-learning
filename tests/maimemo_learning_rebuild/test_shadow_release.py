import copy
import hashlib
import json
import unittest
from pathlib import Path

from maimemo_learning_rebuild.release_writer import execute_release
from tests.maimemo_learning_rebuild.test_release_writer import (
    MemoryJournal,
    card,
    manifest,
    no_wait,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "release"


class SimulatedProcessStop(BaseException):
    pass


class ShadowTransport:
    def __init__(self, live, *, stop_after_commit=None):
        self.live = copy.deepcopy(live)
        self.stop_after_commit = stop_after_commit
        self.post_calls = []
        self.next_id = len(self.live["cards"]) + 1

    def read_deck(self):
        return copy.deepcopy(self.live)

    def create_card(self, chapter_id, content, guard):
        self.post_calls.append((chapter_id, content))
        title = content.split("]", 1)[0].removeprefix("[P#H1#")
        route = next(
            route
            for route, prefix in (
                ("comparison", "近义辨析｜"),
                ("base", "基础词义｜"),
                ("application", "语境应用｜"),
            )
            if title.startswith(prefix)
        )
        card_id = f"shadow{self.next_id}"
        self.next_id += 1
        self.live["cards"].append(
            {
                "id": card_id,
                "root_id": f"mkjr_{card_id}",
                "grammar_version": 3,
                "content": content,
            }
        )
        chapter = next(
            chapter for chapter in self.live["chapters"] if chapter["id"] == chapter_id
        )
        chapter["card_ids"].append(card_id)
        if len(self.post_calls) == self.stop_after_commit:
            raise SimulatedProcessStop("server committed; response was lost")
        return {"id": card_id}

    def update_card(self, card_id, content, guard):
        raise AssertionError("shadow release contains only create actions")


def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _cards():
    return [
        card(
            "近义辨析｜甲、乙",
            "comparison",
            "[P#H1#近义辨析｜甲、乙]\n---\n甲与乙的差异",
        ),
        card(
            "近义辨析｜丙、丁",
            "comparison",
            "[P#H1#近义辨析｜丙、丁]\n---\n丙与丁的差异",
        ),
        card(
            "基础词义｜甲",
            "base",
            (
                "[P#H1#基础词义｜甲]\n---\n"
                "[Card#ID/{{root:近义辨析｜甲、乙}}#近义辨析｜甲、乙]"
            ),
        ),
        card(
            "基础词义｜丙",
            "base",
            (
                "[P#H1#基础词义｜丙]\n---\n"
                "[Card#ID/{{root:近义辨析｜丙、丁}}#近义辨析｜丙、丁]"
            ),
        ),
        card(
            "语境应用｜甲、乙｜动作结果",
            "application",
            "[P#H1#语境应用｜甲、乙｜动作结果]\n---\n应用练习",
        ),
    ]


class ShadowReleaseTests(unittest.TestCase):
    def test_interrupted_release_restarts_without_duplicate_posts(self):
        empty = _fixture("live_deck_empty.json")
        frozen_cards = _cards()
        frozen_manifest = manifest(empty, frozen_cards)
        expected_manifest = copy.deepcopy(frozen_manifest)
        expected_cards = copy.deepcopy(frozen_cards)
        self.assertEqual(
            {
                "comparison": ("chapter-comparison", "comparison"),
                "base": ("chapter-base", "base"),
                "application": ("chapter-application", "application"),
            },
            {
                route: (binding["id"], binding["name"])
                for route, binding in frozen_manifest["chapter_routes"].items()
            },
        )
        first = ShadowTransport(empty, stop_after_commit=3)

        with self.assertRaises(SimulatedProcessStop):
            execute_release(
                first,
                frozen_manifest,
                frozen_cards,
                MemoryJournal(),
                no_wait,
            )

        self.assertEqual(3, len(first.post_calls))
        self.assertEqual(
            ["chapter-comparison", "chapter-comparison", "chapter-base"],
            [chapter_id for chapter_id, _content in first.post_calls],
        )
        self.assertEqual(_fixture("live_deck_partial.json"), first.live)
        self.assertEqual(expected_manifest, frozen_manifest)
        self.assertEqual(expected_cards, frozen_cards)

        restarted = ShadowTransport(_fixture("live_deck_partial.json"))
        restart_journal = MemoryJournal()
        result = execute_release(
            restarted,
            frozen_manifest,
            copy.deepcopy(frozen_cards),
            restart_journal,
            no_wait,
        )

        self.assertEqual(2, len(restarted.post_calls))
        self.assertEqual(
            ["chapter-base", "chapter-application"],
            [chapter_id for chapter_id, _content in restarted.post_calls],
        )
        self.assertEqual(5, len(first.post_calls) + len(restarted.post_calls))
        self.assertEqual(3, result["already_present"])
        self.assertEqual(2, result["create"])
        recovered = [
            entry
            for entry in restart_journal.entries
            if entry.get("outcome") == "already_present"
        ]
        identity_fields = (
            "stable_card_key",
            "title",
            "card_type",
            "chapter_id",
            "chapter_name",
            "card_id",
            "root_id",
            "content_hash",
            "outcome",
        )
        recovered_identities = [
            {field: entry.get(field) for field in identity_fields}
            for entry in recovered
        ]
        partial_by_id = {
            card["id"]: card for card in _fixture("live_deck_partial.json")["cards"]
        }
        self.assertEqual(
            [
                {
                    "stable_card_key": "comparison:甲、乙",
                    "title": "近义辨析｜甲、乙",
                    "card_type": "comparison",
                    "chapter_id": "chapter-comparison",
                    "chapter_name": "comparison",
                    "card_id": "shadow1",
                    "root_id": "mkjr_shadow1",
                    "content_hash": hashlib.sha256(
                        partial_by_id["shadow1"]["content"].encode("utf-8")
                    ).hexdigest(),
                    "outcome": "already_present",
                },
                {
                    "stable_card_key": "comparison:丙、丁",
                    "title": "近义辨析｜丙、丁",
                    "card_type": "comparison",
                    "chapter_id": "chapter-comparison",
                    "chapter_name": "comparison",
                    "card_id": "shadow2",
                    "root_id": "mkjr_shadow2",
                    "content_hash": hashlib.sha256(
                        partial_by_id["shadow2"]["content"].encode("utf-8")
                    ).hexdigest(),
                    "outcome": "already_present",
                },
                {
                    "stable_card_key": "base:甲",
                    "title": "基础词义｜甲",
                    "card_type": "base",
                    "chapter_id": "chapter-base",
                    "chapter_name": "base",
                    "card_id": "shadow3",
                    "root_id": "mkjr_shadow3",
                    "content_hash": hashlib.sha256(
                        partial_by_id["shadow3"]["content"].encode("utf-8")
                    ).hexdigest(),
                    "outcome": "already_present",
                },
            ],
            recovered_identities,
        )
        self.assertEqual(
            3,
            sum(
                entry.get("outcome") == "already_present"
                for entry in restart_journal.entries
            ),
        )
        self.assertEqual(
            [
                ("comparison:甲、乙", "already_present"),
                ("comparison:丙、丁", "already_present"),
                ("base:甲", "already_present"),
                ("base:丙", "create"),
                ("application:甲、乙:动作结果", "create"),
            ],
            [
                (entry["stable_card_key"], entry["outcome"])
                for entry in restart_journal.entries
                if entry.get("stable_card_key")
            ],
        )
        self.assertTrue(result["final_readback"]["ok"], result["final_readback"])
        self.assertEqual(
            {"comparison": 2, "base": 2, "application": 1},
            result["final_readback"]["route_totals"],
        )
        titles = [card["content"].split("]", 1)[0] for card in restarted.live["cards"]]
        self.assertEqual(len(titles), len(set(titles)))
        self.assertEqual(5, len(restarted.live["cards"]))
        self.assertEqual(expected_manifest, frozen_manifest)
        self.assertEqual(expected_cards, frozen_cards)


if __name__ == "__main__":
    unittest.main()
