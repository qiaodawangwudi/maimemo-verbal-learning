"""Machine-enforced write guard for the rebuilt Maimemo library."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from .groups import validate_group_registry
from .learning_quality import learning_review_hash
from .planning import content_hash, validate_action_plan
from .review import GENERIC_WARNINGS, review_registry
from .snapshot import audit_snapshot
from .sources import load_source_catalog


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    errors: tuple[str, ...]
    plan_hash: str
    learning_review_hash: str = ""


def evaluate_guard(
    *,
    snapshot: dict,
    registry: list[dict],
    groups: list[dict],
    final_cards: list[dict],
    plan: dict,
    catalog: dict,
    approval: dict | None,
    target_chapter_id: str,
    independent_review: dict | None = None,
) -> GuardResult:
    errors: list[str] = []
    plan_hash = str(plan.get("plan_hash") or "")
    current_learning_review_hash = ""
    errors.extend(validate_action_plan(plan, snapshot))

    if isinstance(independent_review, dict):
        current_learning_review_hash = learning_review_hash(independent_review)
        stored_review_hash = independent_review.get("review_hash")
        if stored_review_hash is not None and (
            not isinstance(stored_review_hash, str)
            or stored_review_hash.strip() != current_learning_review_hash
        ):
            errors.append("independent learning review hash mismatch")

    snapshot_report = audit_snapshot(snapshot)
    if snapshot_report["missing_reference_targets"]:
        errors.append(
            f"snapshot has missing root references: {len(snapshot_report['missing_reference_targets'])}"
        )
    if snapshot_report["duplicate_titles"]:
        errors.append(f"snapshot has duplicate titles: {len(snapshot_report['duplicate_titles'])}")

    review = review_registry(registry, catalog, groups, independent_review)
    for detail in review["details"]:
        for error in detail["errors"]:
            errors.append(f"semantic error {detail['term']}: {error}")
    errors.extend(review["learning_quality_errors"])
    non_ready = sum(record.get("status") != "ready" for record in registry)
    if non_ready:
        errors.append(f"registry has non-ready records: {non_ready}")

    records_by_term = {record["term"]: record for record in registry}
    group_errors = validate_group_registry(groups, records_by_term)
    errors.extend(group_errors)
    non_ready_groups = sum(group.get("status") != "ready" for group in groups)
    if non_ready_groups:
        errors.append(f"group registry has non-ready groups: {non_ready_groups}")
    meanings = {
        str(record.get("meaning") or "").strip()
        for record in registry
        if str(record.get("meaning") or "").strip()
    }
    features = {
        str(record.get("distinctive_feature") or "").strip()
        for record in registry
        if str(record.get("distinctive_feature") or "").strip()
    }
    for group in groups:
        for edge in group.get("minimum_differences", []) or []:
            difference = str(edge.get("text") or edge.get("minimum_difference") or "").strip()
            if difference and difference in meanings | features:
                errors.append(f"comparison difference copies definition: {group.get('group_id')}")

    manual_actions = sum(
        action.get("action") == "manual-review" for action in plan.get("actions", [])
    )
    if manual_actions:
        errors.append(f"action plan has manual-review actions: {manual_actions}")
    for card in final_cards:
        content = str(card.get("content") or "")
        if card.get("content_hash") != content_hash(content):
            errors.append(f"final card hash mismatch: {card.get('title')}")
        for warning in GENERIC_WARNINGS:
            if warning in content:
                errors.append(f"final card contains generic warning: {card.get('title')}")

    expected_chapter_id = str(plan.get("chapter_id") or "")
    if target_chapter_id != expected_chapter_id:
        errors.append(f"wrong target chapter: {target_chapter_id}")
    if approval is None:
        errors.append("missing write approval")
    else:
        if approval.get("plan_hash") != plan_hash:
            errors.append("approval plan hash mismatch")
        if approval.get("action_counts") != plan.get("action_counts"):
            errors.append("approval action counts mismatch")
        if approval.get("chapter_id") != expected_chapter_id:
            errors.append("approval chapter mismatch")
        if approval.get("learning_review_hash") != current_learning_review_hash:
            errors.append("approval learning review hash mismatch")
    return GuardResult(
        ok=not errors,
        errors=tuple(dict.fromkeys(errors)),
        plan_hash=plan_hash,
        learning_review_hash=current_learning_review_hash,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--groups", type=Path, required=True)
    parser.add_argument("--cards", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--independent-review", type=Path)
    parser.add_argument("--target-chapter-id", required=True)
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8-sig"))
    registry = json.loads(args.registry.read_text(encoding="utf-8-sig"))["records"]
    groups = json.loads(args.groups.read_text(encoding="utf-8-sig"))["groups"]
    cards = json.loads(args.cards.read_text(encoding="utf-8-sig"))["cards"]
    plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
    catalog = load_source_catalog(args.sources)
    approval = (
        json.loads(args.approval.read_text(encoding="utf-8-sig"))
        if args.approval
        else None
    )
    independent_review = (
        json.loads(args.independent_review.read_text(encoding="utf-8-sig"))
        if args.independent_review
        else None
    )
    result = evaluate_guard(
        snapshot=snapshot,
        registry=registry,
        groups=groups,
        final_cards=cards,
        plan=plan,
        catalog=catalog,
        approval=approval,
        target_chapter_id=args.target_chapter_id,
        independent_review=independent_review,
    )
    print(
        json.dumps(
            {
                "ok": result.ok,
                "plan_hash": result.plan_hash,
                "learning_review_hash": result.learning_review_hash,
                "errors": result.errors,
            },
            ensure_ascii=False,
        )
    )
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
