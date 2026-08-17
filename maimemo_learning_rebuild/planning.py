"""Build a deterministic offline library and per-card action plan."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from .application_quality_gate import application_review_hash
from .markji import parse_card
from .models import validate_action_record
from .render import render_application_card, render_base_card, render_comparison_card


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _plan_hash(plan: dict) -> str:
    payload = {key: value for key, value in plan.items() if key != "plan_hash"}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return content_hash(canonical)


def snapshot_hash(snapshot: dict) -> str:
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return content_hash(canonical)


def build_action_plan(
    snapshot: dict,
    registry: list[dict],
    groups: list[dict],
    application_review: dict | None = None,
) -> tuple[dict, list[dict]]:
    parsed = [parse_card(card) for card in snapshot.get("cards", [])]
    base_by_term = {card.term: card for card in parsed if card.card_type == "base"}
    comparison_by_id = {
        card.card_id: card for card in parsed if card.card_type == "comparison"
    }
    application_by_title = {
        card.title: card for card in parsed if card.card_type == "application"
    }
    records_by_term = {record["term"]: record for record in registry}
    ready_groups = [group for group in groups if group.get("status") == "ready"]
    ready_group_refs: dict[str, list[dict]] = {}
    for group in ready_groups:
        if group.get("root_id"):
            reference = {
                "title": group.get("title") or group.get("current_title"),
                "root_id": group["root_id"],
            }
            for member in group.get("members", []):
                ready_group_refs.setdefault(member, []).append(reference)

    actions: list[dict] = []
    final_cards: list[dict] = []
    for record in sorted(registry, key=lambda item: (item.get("registry_order", 10**9), item["term"])):
        term = record["term"]
        title = f"基础词义｜{term}"
        existing = base_by_term.get(term)
        if record.get("status") != "ready":
            actions.append(
                {
                    "title": title,
                    "card_id": existing.card_id if existing else "",
                    "action": "manual-review",
                    "content_hash": content_hash(existing.content if existing else ""),
                    "reason": "语义主档案尚未ready，禁止渲染或写入。",
                    "record_status": record.get("status"),
                }
            )
            continue
        content = render_base_card(record, ready_group_refs.get(term, []))
        digest = content_hash(content)
        if existing:
            action_value = "unchanged" if existing.content == content else "update"
            reason = "统一学习模板渲染结果与现卡一致。" if action_value == "unchanged" else "按已验收语义记录改造成分层学习卡。"
            action = {
                "title": title,
                "card_id": existing.card_id,
                "action": action_value,
                "content_hash": digest,
                "reason": reason,
                "record_status": "ready",
            }
        else:
            action = {
                "title": title,
                "action": "create",
                "content_hash": digest,
                "reason": "课程词已通过语义验收且当前不存在同名基础卡。",
                "record_status": "ready",
            }
        actions.append(action)
        final_cards.append(
            {
                "title": title,
                "card_type": "base",
                "term": term,
                "content": content,
                "content_hash": digest,
                "action": action["action"],
                "card_id": action.get("card_id", ""),
            }
        )

    handled_comparison_ids: set[str] = set()
    for group in groups:
        title = str(group.get("title") or group.get("current_title") or group.get("group_id"))
        existing = comparison_by_id.get(str(group.get("source_card_id") or ""))
        if existing:
            handled_comparison_ids.add(existing.card_id)
        if group.get("status") != "ready":
            actions.append(
                {
                    "title": title,
                    "card_id": existing.card_id if existing else "",
                    "action": "manual-review",
                    "content_hash": content_hash(existing.content if existing else ""),
                    "reason": "辨析组尚未通过语义图谱验收，禁止保留旧内容或自动重写。",
                    "record_status": group.get("status"),
                }
            )
            continue
        member_records = [records_by_term[term] for term in group["members"]]
        content = render_comparison_card(group, member_records)
        digest = content_hash(content)
        if existing:
            value = "unchanged" if existing.content == content else "update"
            action = {
                "title": title,
                "card_id": existing.card_id,
                "action": value,
                "content_hash": digest,
                "reason": "按已验收比较图重建辨析卡。" if value == "update" else "辨析卡内容已一致。",
                "record_status": "ready",
            }
        else:
            action = {
                "title": title,
                "action": "create",
                "content_hash": digest,
                "reason": "已验收辨析组没有可复用的现有卡。",
                "record_status": "ready",
            }
        actions.append(action)
        final_cards.append(
            {
                "title": title,
                "card_type": "comparison",
                "members": group["members"],
                "content": content,
                "content_hash": digest,
                "action": action["action"],
                "card_id": action.get("card_id", ""),
            }
        )

    for card in parsed:
        if card.card_type == "comparison" and card.card_id not in handled_comparison_ids:
            actions.append(
                {
                    "title": card.title,
                    "card_id": card.card_id,
                    "action": "manual-review",
                    "content_hash": content_hash(card.content),
                    "reason": "现有辨析卡未进入统一组档案。",
                    "record_status": "unresolved",
                }
            )

    handled_application_titles: set[str] = set()
    for application in (application_review or {}).get("applications", []):
        title = str(application["title"])
        handled_application_titles.add(title)
        existing = application_by_title.get(title)
        content = render_application_card(application)
        digest = content_hash(content)
        if existing:
            value = "unchanged" if existing.content == content else "update"
            action = {
                "title": title,
                "card_id": existing.card_id,
                "action": value,
                "content_hash": digest,
                "reason": "按已验收应用场景重建训练卡。" if value == "update" else "应用场景卡内容已一致。",
                "record_status": "ready",
            }
        else:
            action = {
                "title": title,
                "action": "create",
                "content_hash": digest,
                "reason": "应用价值审查确认该语境具有独立训练价值。",
                "record_status": "ready",
            }
        actions.append(action)
        final_cards.append(
            {
                "title": title,
                "card_type": "application",
                "application": application,
                "content": content,
                "content_hash": digest,
                "action": action["action"],
                "card_id": action.get("card_id", ""),
            }
        )

    for title, card in application_by_title.items():
        if title not in handled_application_titles:
            actions.append(
                {
                    "title": title,
                    "card_id": card.card_id,
                    "action": "manual-review",
                    "content_hash": content_hash(card.content),
                    "reason": "现有应用卡未进入统一应用价值审查档案。",
                    "record_status": "unresolved",
                }
            )

    action_counts = Counter(action["action"] for action in actions)
    create_count = action_counts.get("create", 0)
    plan = {
        "schema_version": 1,
        "deck_id": str(snapshot.get("deck_id") or ""),
        "chapter_id": str(snapshot.get("chapter", {}).get("id") or ""),
        "chapter_name": str(snapshot.get("chapter", {}).get("name") or ""),
        "snapshot_hash": snapshot_hash(snapshot),
        "before": len(parsed),
        "expected_after": len(parsed) + create_count,
        "action_counts": dict(sorted(action_counts.items())),
        "actions": actions,
    }
    if application_review is not None:
        plan["application_review_hash"] = application_review_hash(application_review)
    plan["plan_hash"] = _plan_hash(plan)
    return plan, final_cards


def validate_action_plan(plan: dict, snapshot: dict) -> list[str]:
    errors: list[str] = []
    parsed = [parse_card(card) for card in snapshot.get("cards", [])]
    existing_titles = {card.title for card in parsed}
    existing_ids = {card.card_id for card in parsed}
    actions = plan.get("actions", [])
    for action in actions:
        errors.extend(validate_action_record(action))
        title = str(action.get("title") or "")
        value = action.get("action")
        if value == "create" and title in existing_titles:
            errors.append(f"create duplicates existing title: {title}")
        if value in {"update", "repurpose", "unchanged"} and action.get("card_id") not in existing_ids:
            errors.append(f"action targets unknown card_id: {title}")
        if action.get("record_status") != "ready" and value != "manual-review":
            errors.append(f"pending record has mutating action: {title}")
    create_count = sum(action.get("action") == "create" for action in actions)
    if plan.get("before") + create_count != plan.get("expected_after"):
        errors.append("action count equation mismatch")
    if plan.get("before") != len(parsed):
        errors.append("plan before count differs from snapshot")
    if plan.get("snapshot_hash") and plan.get("snapshot_hash") != snapshot_hash(snapshot):
        errors.append("snapshot hash mismatch")
    if plan.get("plan_hash") and plan.get("plan_hash") != _plan_hash(plan):
        errors.append("plan hash mismatch")
    return errors


def _preview(final_cards: list[dict], plan: dict) -> str:
    lines = [
        "# 墨墨言语词汇学习卡离线预览",
        "",
        f"- 冻结计划哈希：`{plan['plan_hash']}`",
        f"- 可渲染卡：{len(final_cards)}",
        f"- 待人工语义复核：{plan['action_counts'].get('manual-review', 0)}",
        "",
        "> 这不是写入授权。存在 manual-review 时，写入守卫必须拒绝执行。",
    ]
    for card in final_cards:
        lines.extend(
            [
                "",
                f"## {card['title']}",
                "",
                f"计划动作：{card['action']}",
                f"内容哈希：`{card['content_hash']}`",
                "",
                card["content"],
            ]
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--groups", type=Path, required=True)
    parser.add_argument("--applications", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "artifacts")
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8-sig"))
    registry = json.loads(args.registry.read_text(encoding="utf-8-sig"))["records"]
    groups = json.loads(args.groups.read_text(encoding="utf-8-sig"))["groups"]
    application_review = (
        json.loads(args.applications.read_text(encoding="utf-8-sig"))
        if args.applications
        else None
    )
    plan, final_cards = build_action_plan(
        snapshot, registry, groups, application_review
    )
    errors = validate_action_plan(plan, snapshot)
    if errors:
        for error in errors:
            print(error)
        return 1
    args.output_dir.mkdir(parents=True, exist_ok=True)
    final_payload = {
        "schema_version": 1,
        "complete": not bool(plan["action_counts"].get("manual-review")),
        "totals": {
            "rendered": len(final_cards),
            "by_type": dict(sorted(Counter(card["card_type"] for card in final_cards).items())),
        },
        "cards": final_cards,
    }
    (args.output_dir / "final_cards.json").write_text(
        json.dumps(final_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "action_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "learning_preview.md").write_text(
        _preview(final_cards, plan), encoding="utf-8"
    )
    print(json.dumps({"plan_hash": plan["plan_hash"], "counts": plan["action_counts"], "expected_after": plan["expected_after"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
