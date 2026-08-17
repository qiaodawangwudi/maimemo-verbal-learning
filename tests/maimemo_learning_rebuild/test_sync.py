import unittest
import urllib.error
from email.message import Message
from unittest.mock import patch

from maimemo_learning_rebuild.api import (
    AmbiguousMutationError,
    MaimemoClient,
    PermanentApiError,
    RateLimitError,
    UrllibTransport,
)
from maimemo_learning_rebuild.guard import GuardResult
from maimemo_learning_rebuild.planning import content_hash
from maimemo_learning_rebuild.sync import apply_plan, apply_plan_to_chapters


class FakeTransport:
    def __init__(self, responses=None, error=None):
        self.calls = []
        self.responses = list(responses or [])
        self.error = error

    def request(self, method, url, headers, payload=None):
        self.calls.append((method, url, headers, payload))
        if self.error:
            if isinstance(self.error, Exception):
                raise self.error
            raise RuntimeError(self.error)
        return self.responses.pop(0) if self.responses else {"data": {}}


class ApiIsolationTests(unittest.TestCase):
    def test_urllib_transport_classifies_retry_after_and_ambiguous_timeout(self):
        headers = Message()
        headers["Retry-After"] = "7"
        rate_limit = urllib.error.HTTPError(
            "https://example.invalid", 429, "limited", headers, None
        )
        with patch("urllib.request.urlopen", side_effect=rate_limit):
            with self.assertRaises(RateLimitError) as caught:
                UrllibTransport().request("POST", "https://example.invalid", {})
        self.assertEqual(7, caught.exception.retry_after_seconds)

        for method, expected in (
            ("POST", AmbiguousMutationError),
            ("GET", PermanentApiError),
        ):
            with self.subTest(method=method):
                with patch("urllib.request.urlopen", side_effect=TimeoutError()):
                    with self.assertRaises(expected):
                        UrllibTransport().request(
                            method, "https://example.invalid", {}
                        )

    def test_routed_sync_rejects_bare_comparison_root_id(self):
        content = "[P#H1#近义辨析｜甲、乙]\n---\n辨析"
        live = {
            "data": {
                "chapters": [
                    {"id": "comparison", "card_ids": ["g1"]},
                    {"id": "base", "card_ids": []},
                    {"id": "application", "card_ids": []},
                ],
                "cards": [{"id": "g1", "root_id": "mkjr_", "content": content}],
            }
        }
        client = MaimemoClient(
            FakeTransport([live, live]), token="secret", deck_id="deck"
        )
        guard = GuardResult(True, (), "hash", "learning-review-hash")
        plan = {
            "actions": [
                {
                    "title": "近义辨析｜甲、乙",
                    "action": "create",
                    "content_hash": content_hash(content),
                }
            ]
        }
        cards = [
            {
                "title": "近义辨析｜甲、乙",
                "card_type": "comparison",
                "content": content,
            }
        ]

        with self.assertRaisesRegex(RuntimeError, "invalid comparison root_id"):
            apply_plan_to_chapters(
                client,
                guard,
                plan,
                cards,
                {
                    "comparison": "comparison",
                    "base": "base",
                    "application": "application",
                },
                pause=lambda: None,
            )

    def test_client_has_no_generic_environment_constructor(self):
        self.assertFalse(hasattr(MaimemoClient, "from_environment"))

    def test_api_preserves_safe_exception_types_and_redacts_token(self):
        cases = (
            (AmbiguousMutationError("timeout secret-token"), AmbiguousMutationError),
            (RateLimitError(9, "rate secret-token"), RateLimitError),
            (PermanentApiError("bad secret-token"), PermanentApiError),
        )
        for error, expected_type in cases:
            with self.subTest(expected_type=expected_type):
                transport = FakeTransport(error=error)
                client = MaimemoClient(
                    transport, token="secret-token", deck_id="deck"
                )
                with self.assertRaises(expected_type) as caught:
                    client.create_card(
                        "chapter",
                        "content",
                        GuardResult(True, (), "hash", "learning-review-hash"),
                    )
                self.assertNotIn("secret-token", str(caught.exception))
                if expected_type is RateLimitError:
                    self.assertEqual(9, caught.exception.retry_after_seconds)

    def test_legacy_guard_without_learning_review_hash_cannot_call_write_api(self):
        transport = FakeTransport()
        client = MaimemoClient(transport, token="secret", deck_id="deck")
        legacy_guard = GuardResult(True, (), "legacy-plan-hash")

        for operation in (
            lambda: client.update_card("c1", "content", legacy_guard),
            lambda: client.create_card("chapter", "content", legacy_guard),
        ):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(RuntimeError, "learning review"):
                    operation()

        self.assertEqual([], transport.calls)

    def test_legacy_guard_without_learning_review_hash_cannot_apply_plan(self):
        transport = FakeTransport()
        client = MaimemoClient(transport, token="secret", deck_id="deck")

        with self.assertRaisesRegex(RuntimeError, "learning review"):
            apply_plan(
                client,
                GuardResult(True, (), "legacy-plan-hash"),
                {"chapter_id": "chapter", "actions": []},
                [],
                "chapter",
                pause=lambda: None,
            )

        self.assertEqual([], transport.calls)

    def test_legacy_guard_without_learning_review_hash_cannot_apply_routed_plan(self):
        transport = FakeTransport()
        client = MaimemoClient(transport, token="secret", deck_id="deck")

        with self.assertRaisesRegex(RuntimeError, "learning review"):
            apply_plan_to_chapters(
                client,
                GuardResult(True, (), "legacy-plan-hash"),
                {"actions": []},
                [],
                {
                    "comparison": "comparison",
                    "base": "base",
                    "application": "application",
                },
                pause=lambda: None,
            )

        self.assertEqual([], transport.calls)

    def test_routed_sync_resumes_matching_creates_without_duplicates(self):
        group_content = "[P#H1#近义辨析｜甲、乙]\n---\n辨析"
        base_template = (
            "[P#H1#基础词义｜甲]\n---\n"
            "[Card#ID/{{root:近义辨析｜甲、乙}}#近义辨析｜甲、乙]"
        )
        resolved_base = base_template.replace(
            "{{root:近义辨析｜甲、乙}}", "mkjr_existing"
        )
        app_content = "[P#H1#语境应用｜甲、乙｜差别]\n---\n应用"
        live_data = {
            "data": {
                "chapters": [
                    {"id": "comparison", "card_ids": ["g1"]},
                    {"id": "base", "card_ids": ["b1"]},
                    {"id": "application", "card_ids": []},
                ],
                "cards": [
                    {
                        "id": "g1",
                        "root_id": "mkjr_existing",
                        "content": group_content,
                    },
                    {"id": "b1", "content": resolved_base},
                ],
            }
        }
        transport = FakeTransport([live_data, live_data, {"data": {"id": "a1"}}])
        client = MaimemoClient(transport, token="secret", deck_id="deck")
        guard = GuardResult(True, (), "hash", "learning-review-hash")
        plan = {
            "actions": [
                {"title": "近义辨析｜甲、乙", "action": "create", "content_hash": content_hash(group_content)},
                {"title": "基础词义｜甲", "action": "create", "content_hash": content_hash(base_template)},
                {"title": "语境应用｜甲、乙｜差别", "action": "create", "content_hash": content_hash(app_content)},
            ]
        }
        cards = [
            {"title": "近义辨析｜甲、乙", "card_type": "comparison", "content": group_content},
            {"title": "基础词义｜甲", "card_type": "base", "content": base_template},
            {"title": "语境应用｜甲、乙｜差别", "card_type": "application", "content": app_content},
        ]

        counts = apply_plan_to_chapters(
            client,
            guard,
            plan,
            cards,
            {"comparison": "comparison", "base": "base", "application": "application"},
            pause=lambda: None,
        )

        self.assertEqual(["GET", "GET", "POST"], [call[0] for call in transport.calls])
        self.assertIn("/chapters/application/cards", transport.calls[2][1])
        self.assertEqual(2, counts["already_present"])
        self.assertEqual(1, counts["create"])

    def test_sync_routes_each_card_type_to_its_approved_chapter(self):
        group_content = "[P#H1#近义辨析｜甲、乙]\n---\n辨析"
        base_template = (
            "[P#H1#基础词义｜甲]\n---\n"
            "[Card#ID/{{root:近义辨析｜甲、乙}}#近义辨析｜甲、乙]"
        )
        app_content = "[P#H1#语境应用｜甲、乙｜差别]\n---\n应用"
        transport = FakeTransport(
            [
                {
                    "data": {
                        "chapters": [
                            {"id": "comparison", "card_ids": []},
                            {"id": "base", "card_ids": []},
                            {"id": "application", "card_ids": []},
                        ],
                        "cards": [],
                    }
                },
                {"data": {"id": "g1"}},
                {
                    "data": {
                        "chapters": [
                            {"id": "comparison", "card_ids": ["g1"]},
                            {"id": "base", "card_ids": []},
                            {"id": "application", "card_ids": []},
                        ],
                        "cards": [
                            {"id": "g1", "root_id": "mkjr_new", "content": group_content}
                        ],
                    }
                },
                {"data": {"id": "b1"}},
                {"data": {"id": "a1"}},
            ]
        )
        client = MaimemoClient(transport, token="secret", deck_id="deck")
        guard = GuardResult(True, (), "hash", "learning-review-hash")
        plan = {
            "actions": [
                {"title": "近义辨析｜甲、乙", "action": "create", "content_hash": content_hash(group_content)},
                {"title": "基础词义｜甲", "action": "create", "content_hash": content_hash(base_template)},
                {"title": "语境应用｜甲、乙｜差别", "action": "create", "content_hash": content_hash(app_content)},
            ]
        }
        cards = [
            {"title": "近义辨析｜甲、乙", "card_type": "comparison", "content": group_content},
            {"title": "基础词义｜甲", "card_type": "base", "content": base_template},
            {"title": "语境应用｜甲、乙｜差别", "card_type": "application", "content": app_content},
        ]

        counts = apply_plan_to_chapters(
            client,
            guard,
            plan,
            cards,
            {"comparison": "comparison", "base": "base", "application": "application"},
            pause=lambda: None,
        )

        self.assertIn("/chapters/comparison/cards", transport.calls[1][1])
        self.assertIn("/chapters/base/cards", transport.calls[3][1])
        self.assertIn("/chapters/application/cards", transport.calls[4][1])
        self.assertIn("mkjr_new", transport.calls[3][3]["card"]["content"])
        self.assertEqual(3, counts["create"])

    def test_new_deck_resolves_created_comparison_root_before_base_write(self):
        group_content = "[P#H1#近义辨析｜甲、乙]\n\n问题\n\n---\n\n辨析"
        base_template = (
            "[P#H1#基础词义｜甲]\n\n问题\n\n---\n\n"
            "[Card#ID/{{root:近义辨析｜甲、乙}}#近义辨析｜甲、乙]"
        )
        transport = FakeTransport(
            [
                {"data": {"id": "g1"}},
                {
                    "data": {
                        "chapters": [{"id": "chapter", "card_ids": ["g1"]}],
                        "cards": [
                            {
                                "id": "g1",
                                "root_id": "mkjr_new_group",
                                "content": group_content,
                            }
                        ],
                    }
                },
                {"data": {"id": "b1"}},
            ]
        )
        client = MaimemoClient(transport, token="secret", deck_id="deck")
        guard = GuardResult(True, (), "hash", "learning-review-hash")
        plan = {
            "chapter_id": "chapter",
            "actions": [
                {
                    "title": "近义辨析｜甲、乙",
                    "action": "create",
                    "content_hash": content_hash(group_content),
                },
                {
                    "title": "基础词义｜甲",
                    "action": "create",
                    "content_hash": content_hash(base_template),
                },
            ],
        }
        cards = [
            {"title": "基础词义｜甲", "card_type": "base", "content": base_template},
            {
                "title": "近义辨析｜甲、乙",
                "card_type": "comparison",
                "content": group_content,
            },
        ]

        apply_plan(client, guard, plan, cards, "chapter", pause=lambda: None)

        written_base = transport.calls[2][3]["card"]["content"]
        self.assertIn("[Card#ID/mkjr_new_group#近义辨析｜甲、乙]", written_base)
        self.assertNotIn("{{root:", written_base)

    def test_read_call_cannot_mutate_and_write_requires_guard(self):
        transport = FakeTransport([{"data": {"chapters": [], "cards": []}}])
        client = MaimemoClient(transport, token="secret", deck_id="deck")

        client.read_deck()

        self.assertEqual("GET", transport.calls[0][0])
        with self.assertRaisesRegex(RuntimeError, "approved guard"):
            client.update_card("c1", "content", GuardResult(False, ("blocked",), "hash"))
        self.assertEqual(1, len(transport.calls))

    def test_token_is_redacted_from_transport_errors(self):
        transport = FakeTransport(error="request failed with secret-token")
        client = MaimemoClient(transport, token="secret-token", deck_id="deck")

        with self.assertRaises(RuntimeError) as caught:
            client.read_deck()

        self.assertNotIn("secret-token", str(caught.exception))
        self.assertIn("[REDACTED]", str(caught.exception))

    def test_sync_applies_comparisons_before_bases_and_blocks_unplanned_create(self):
        transport = FakeTransport(
            [
                {"data": {"id": "g1"}},
                {
                    "data": {
                        "chapters": [{"id": "chapter", "card_ids": ["g1"]}],
                        "cards": [{"id": "g1", "root_id": "mkjr_group", "content": "group"}],
                    }
                },
                {"data": {"id": "b1"}},
                {"data": {"id": "a1"}},
            ]
        )
        client = MaimemoClient(transport, token="secret", deck_id="deck")
        guard = GuardResult(True, (), "hash", "learning-review-hash")
        plan = {
            "chapter_id": "chapter",
            "actions": [
                {"title": "近义辨析｜甲、乙", "card_id": "g1", "action": "update"},
                {"title": "基础词义｜甲", "card_id": "b1", "action": "update"},
                {"title": "语境应用｜甲、乙｜差别", "action": "create"},
            ],
        }
        cards = [
            {"title": "基础词义｜甲", "card_type": "base", "content": "base"},
            {"title": "近义辨析｜甲、乙", "card_type": "comparison", "content": "group"},
            {"title": "语境应用｜甲、乙｜差别", "card_type": "application", "content": "app"},
        ]

        apply_plan(client, guard, plan, cards, "chapter", pause=lambda: None)

        methods_and_urls = [(call[0], call[1]) for call in transport.calls]
        self.assertIn("/cards/g1", methods_and_urls[0][1])
        self.assertEqual("GET", methods_and_urls[1][0])
        self.assertIn("/cards/b1", methods_and_urls[2][1])
        self.assertIn("/chapters/chapter/cards", methods_and_urls[3][1])

        bad_plan = {"chapter_id": "chapter", "actions": []}
        bad_cards = [{"title": "基础词义｜丙", "card_type": "base", "content": "new"}]
        with self.assertRaisesRegex(RuntimeError, "card missing from approved plan"):
            apply_plan(client, guard, bad_plan, bad_cards, "chapter", pause=lambda: None)


if __name__ == "__main__":
    unittest.main()
