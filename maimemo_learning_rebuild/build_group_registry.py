"""Reconstruct the complete current comparison-card universe for semantic review."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path

from .groups import audit_group_overlaps, validate_group_registry
from .markji import parse_card


PAIR_PATTERN = re.compile(r"\[T#B#([^：\]\n]+) × ([^：\]\n]+)：\]")


def _edge_text(records: dict[str, dict], left: str, right: str) -> str:
    for source, target in ((left, right), (right, left)):
        for edge in records[source].get("comparison_edges", []):
            if edge.get("other_term") == target:
                text = str(edge.get("minimum_difference") or "").strip()
                if text:
                    return text
    return (
        f"{left}：{records[left]['distinctive_feature']}；"
        f"{right}：{records[right]['distinctive_feature']}"
    )


def _select_learning_cluster(
    members: list[str], records: dict[str, dict], current_pairs: list[list[str]]
) -> list[str]:
    if len(members) <= 6:
        return members
    order = {term: index for index, term in enumerate(members)}
    neighbors = {term: set() for term in members}
    for term in members:
        for edge in records[term].get("comparison_edges", []):
            other = str(edge.get("other_term") or "")
            if other in neighbors and other != term:
                neighbors[term].add(other)
                neighbors[other].add(term)
    for pair in current_pairs:
        if len(pair) == 2 and pair[0] in neighbors and pair[1] in neighbors:
            neighbors[pair[0]].add(pair[1])
            neighbors[pair[1]].add(pair[0])

    components: list[list[str]] = []
    unseen = set(members)
    while unseen:
        start = min(unseen, key=order.get)
        component: list[str] = []
        queue = [start]
        unseen.remove(start)
        while queue:
            term = queue.pop(0)
            component.append(term)
            for other in sorted(neighbors[term] & unseen, key=order.get):
                unseen.remove(other)
                queue.append(other)
        components.append(sorted(component, key=order.get))
    component = min(components, key=lambda items: (-len(items), order[items[0]]))
    if len(component) <= 6:
        return component if len(component) >= 2 else members[:2]
    start = min(component, key=lambda term: (-len(neighbors[term]), order[term]))
    selected: list[str] = []
    queued = {start}
    queue = [start]
    while queue and len(selected) < 6:
        term = queue.pop(0)
        selected.append(term)
        for other in sorted(neighbors[term] - queued, key=order.get):
            if other in component:
                queued.add(other)
                queue.append(other)
    return sorted(selected, key=order.get)


def synthesize_group_review(group: dict, records: dict[str, dict]) -> dict:
    """Build a connected, learner-facing comparison view from reviewed meanings."""
    original_members = list(group.get("members", []))
    if any(records.get(term, {}).get("status") != "ready" for term in original_members):
        return group
    current_pairs = group.get("audit", {}).get("current_pairs", [])
    members = _select_learning_cluster(original_members, records, current_pairs)
    order = {term: index for index, term in enumerate(members)}
    candidate_pairs: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()

    def add_pair(left: str, right: str) -> None:
        if left not in order or right not in order or left == right:
            return
        pair = tuple(sorted((left, right), key=lambda term: order[term]))
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            candidate_pairs.append(pair)

    for left in members:
        for edge in records[left].get("comparison_edges", []):
            add_pair(left, str(edge.get("other_term") or ""))
    for pair in current_pairs:
        if len(pair) == 2:
            add_pair(str(pair[0]), str(pair[1]))

    parent = {term: term for term in members}

    def find(term: str) -> str:
        while parent[term] != term:
            parent[term] = parent[parent[term]]
            term = parent[term]
        return term

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left, right in candidate_pairs:
        union(left, right)
    for left, right in zip(members, members[1:]):
        if find(left) != find(right):
            add_pair(left, right)
            union(left, right)

    differences = [
        {"left": left, "right": right, "text": _edge_text(records, left, right)}
        for left, right in candidate_pairs
    ]
    axes: dict[str, dict[str, str]] = {}
    for term in members:
        for dimension in records[term].get("dimensions", []):
            axis = str(dimension.get("axis") or "").strip()
            judgment = str(dimension.get("judgment") or "").strip()
            if axis and judgment:
                axes.setdefault(axis, {})[term] = judgment
    dimensions = [
        {"axis": axis, "judgments": judgments}
        for axis, judgments in axes.items()
        if len(judgments) >= 2
    ]
    if not dimensions:
        dimensions = [
            {
                "axis": "特别落点",
                "judgments": {
                    term: str(records[term]["distinctive_feature"]) for term in members
                },
            }
        ]
    boundaries = "；".join(
        f"{term}：{records[term]['misuse_boundary']}" for term in members
    )
    reviewed = dict(group)
    excluded = [term for term in original_members if term not in members]
    audit = dict(group.get("audit", {}))
    audit["missing_base_terms"] = [
        term for term in audit.get("missing_base_terms", []) if term in members
    ]
    reviewed.update(
        {
            "members": members,
            # Generated prose is a review candidate, not independent evidence.
            # Only an explicit override carrying the object-level comparison
            # contract may promote this group to ready later in the pipeline.
            "status": "pending",
            "pending_reason": "independent comparison edge review required",
            "title": f"近义辨析｜{'、'.join(members)}",
            "purpose": "依据准确词义、特别之处和题干判断维度，区分组内词语的最小差别。",
            "minimum_differences": differences,
            "dimensions": dimensions,
            "misuse_boundary": "逐词排除误用边界：" + boundaries,
            "audit": audit,
        }
    )
    if excluded:
        reviewed["decision"] = "repurpose"
        reviewed["excluded_members"] = excluded
        reviewed["decision_reason"] = (
            f"原卡含{len(original_members)}个成员，超过单卡学习上限；"
            "保留内部关系最强且可形成连通判断链的成员，其余词回到基础卡或其他辨析轴。"
        )
    return reviewed


def build_group_registry(
    source_root: Path,
    semantic_registry_path: Path | None = None,
    override_paths: list[Path] | None = None,
) -> dict:
    audit_root = source_root / "maimemo_four_poems" / "audit_readonly"
    snapshot_path = audit_root / "current_library_snapshot_2026-08-17.json"
    issue_path = audit_root / "content_field_audit_2026-08-17.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
    content_audit = json.loads(issue_path.read_text(encoding="utf-8-sig"))
    copied_titles = {
        issue["title"] for issue in content_audit.get("comparison_issues", [])
    }
    parsed = [parse_card(card) for card in snapshot.get("cards", [])]
    base_terms = [card.term for card in parsed if card.card_type == "base"]
    base_set = set(base_terms)
    comparison_cards = [card for card in parsed if card.card_type == "comparison"]

    order: dict[str, int] = {term: index for index, term in enumerate(base_terms)}
    for card in comparison_cards:
        for term in card.members:
            order.setdefault(term, len(order))
    records = [
        {"term": term, "registry_order": index, "status": "pending"}
        for term, index in sorted(order.items(), key=lambda item: item[1])
    ]
    if semantic_registry_path:
        semantic_payload = json.loads(
            semantic_registry_path.read_text(encoding="utf-8-sig")
        )
        semantic_by_term = {
            record["term"]: record for record in semantic_payload.get("records", [])
        }
        records = [semantic_by_term.get(record["term"], record) for record in records]

    groups: list[dict] = []
    for card in comparison_cards:
        current_edges = [list(pair) for pair in PAIR_PATTERN.findall(card.content)]
        copied = card.title in copied_titles
        missing_base = [term for term in card.members if term not in base_set]
        members = sorted(card.members, key=lambda term: (order[term], term))
        if len(members) > 6 and (copied or len(current_edges) < len(members) - 1):
            decision = "split"
            reason = (
                f"当前{len(members)}个成员，但仅识别到{len(current_edges)}条直接比较，"
                "且现有内容不能证明所有成员属于同一可学习语义场；须按证据拆成小组。"
            )
        elif copied:
            decision = "repurpose"
            reason = "现有最小差别直接复制词义，保留卡位但必须重建比较轴与迁移判断。"
        else:
            decision = "keep"
            reason = (
                "当前成员关系暂予保留；直接比较和课程分组仍须在逐词语义重建后复核。"
            )
        if missing_base:
            reason += " 当前缺少基础卡：" + "、".join(missing_base) + "。"
        if decision == "split":
            purpose = "恢复课程中的直接比较关系，并拆成能形成稳定最小差别的小组。"
        elif decision == "repurpose":
            purpose = "去除复制定义式辨析，重建可用于题干判断的最小差别。"
        else:
            purpose = "复核并保留有学习价值的成员关系，重写词义、特点与最小差别。"
        groups.append(
            {
                "group_id": f"group::{card.root_id}",
                "source_card_id": card.card_id,
                "root_id": card.root_id,
                "current_title": card.title,
                "status": "pending",
                "purpose": purpose,
                "members": members,
                "decision": decision,
                "decision_reason": reason,
                "overlap_reasons": {},
                "audit": {
                    "member_count": len(members),
                    "current_direct_comparisons": len(current_edges),
                    "current_pairs": current_edges,
                    "minimum_difference_copies_definition": copied,
                    "missing_base_terms": missing_base,
                },
            }
        )

    by_id = {group["group_id"]: group for group in groups}
    overlaps = audit_group_overlaps(groups)
    for overlap in overlaps:
        left_id = overlap["left_group_id"]
        right_id = overlap["right_group_id"]
        shared = "、".join(overlap["shared_members"])
        by_id[left_id]["overlap_reasons"][right_id] = (
            f"暂保留共享词{shared}的多轴关系；语义重建时必须证明两个组的判断任务不同，"
            "否则合并、拆分或改造其中一张卡。"
        )

    if semantic_registry_path:
        semantic_by_term = {
            record["term"]: record for record in records if record.get("term")
        }
        groups = [synthesize_group_review(group, semantic_by_term) for group in groups]

    if override_paths:
        overrides: dict[str, dict] = {}
        for path in override_paths:
            override_payload = json.loads(path.read_text(encoding="utf-8-sig"))
            batch = override_payload.get("groups", {})
            duplicates = set(overrides) & set(batch)
            if duplicates:
                raise ValueError(f"duplicate group overrides: {sorted(duplicates)}")
            overrides.update(batch)
        for group in groups:
            override = overrides.get(group["group_id"])
            if override:
                group.update(override)

    overlaps = audit_group_overlaps(groups)
    by_id = {group["group_id"]: group for group in groups}
    for overlap in overlaps:
        left_id = overlap["left_group_id"]
        right_id = overlap["right_group_id"]
        shared = "、".join(overlap["shared_members"])
        left_reasons = by_id[left_id].setdefault("overlap_reasons", {})
        right_reasons = by_id[right_id].setdefault("overlap_reasons", {})
        if not left_reasons.get(right_id) and not right_reasons.get(left_id):
            left_reasons[right_id] = f"共享词{shared}分别承担不同题干判断轴，保留交叉训练。"

    decision_counts = Counter(group["decision"] for group in groups)
    status_counts = Counter(group["status"] for group in groups)
    return {
        "schema_version": 1,
        "snapshot": str(snapshot_path.resolve()),
        "scope_note": "完整登记当前125张辨析卡；pending表示尚未用最终语义档案验收，不代表默认保留旧内容。",
        "totals": {
            "groups": len(groups),
            "terms": len(records),
            "decisions": dict(sorted(decision_counts.items())),
            "statuses": dict(sorted(status_counts.items())),
            "overlaps": dict(
                sorted(Counter(item["type"] for item in overlaps).items())
            ),
            "groups_with_missing_base_terms": sum(
                bool(group["audit"]["missing_base_terms"]) for group in groups
            ),
        },
        "records": records,
        "groups": groups,
        "overlaps": overlaps,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--semantic-registry", type=Path)
    parser.add_argument("--overrides", type=Path, action="append")
    args = parser.parse_args()
    payload = build_group_registry(
        args.source_root,
        semantic_registry_path=args.semantic_registry,
        override_paths=args.overrides,
    )
    records = {record["term"]: record for record in payload["records"]}
    errors = validate_group_registry(payload["groups"], records)
    if errors:
        for error in errors:
            print(error)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload["snapshot"] = Path(
        os.path.relpath(Path(payload["snapshot"]), args.output.parent.resolve())
    ).as_posix()
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload["totals"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
