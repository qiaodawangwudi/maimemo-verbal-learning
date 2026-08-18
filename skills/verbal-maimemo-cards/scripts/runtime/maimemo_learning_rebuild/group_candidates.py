"""Build review candidates from already-normalized semantic records."""

from __future__ import annotations

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
