"""Render validated semantic records as layered Markji learning cards."""

from __future__ import annotations

import re


_NON_DIMENSION_AXES = {
    "选择落点",
    "落点",
    "核心辨析",
    "词义",
    "题干关键词",
    "一眼辨析",
    "怎么选",
    "判断维度",
}


def _line(label: str, text: str) -> str:
    return f"[T#B#{label}]{text}"


def _core(record: dict) -> str:
    return str(
        record.get("core_discrimination")
        or record.get("distinctive_feature")
        or ""
    ).strip()


def _normalized(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", str(text)).lower()


def _adds_information(text: str, existing: list[str]) -> bool:
    candidate = _normalized(text)
    if not candidate:
        return False
    for prior in existing:
        normalized = _normalized(prior)
        if (
            candidate == normalized
            or candidate in normalized
            or normalized in candidate
        ):
            return False
    return True


def _same_judgment(left: str, right: str) -> bool:
    return bool(_normalized(left)) and _normalized(left) == _normalized(right)


def _is_independent_dimension(axis: str) -> bool:
    normalized = _normalized(axis)
    return bool(normalized) and normalized not in {
        _normalized(value) for value in _NON_DIMENSION_AXES
    }


def _landing_from_clause(term: str, clause: str) -> str:
    value = str(clause).strip("。；，： ")
    value = re.sub(
        rf"^{re.escape(term)}(?:的)?(?:重|看|侧重|强调|落点(?:是|在)?|：)",
        "",
        value,
    )
    return value.strip("。；，： ")


def _pairwise_glance(left: str, right: str, text: str) -> str:
    clauses = [part.strip() for part in re.split(r"[；。]", str(text)) if part.strip()]
    left_clause = next((part for part in clauses if left in part), "")
    right_clause = next((part for part in clauses if right in part), "")
    left_landing = _landing_from_clause(left, left_clause)
    right_landing = _landing_from_clause(right, right_clause)
    if not left_landing or not right_landing:
        return ""
    return f"{left_landing} vs {right_landing}"


def _core_landing(record: dict) -> str:
    parts = [part.strip() for part in _core(record).split("+") if part.strip()]
    return (parts[-1] if parts else _core(record)).strip("。；，： ")


def render_application_card(application: dict) -> str:
    """Render a scenario exercise with the judgment process hidden on the back."""

    title = str(application["title"])
    options = [str(option) for option in application["options"]]
    answer = str(application["answer"])
    rejections = application.get("distractor_rejections", {})
    lines = [
        f"[P#H1#{title}]",
        "",
        str(application["prompt"]),
        "",
    ]
    lines.extend(f"{chr(65 + index)}. {option}" for index, option in enumerate(options))
    lines.extend(
        [
            "",
            "---",
            "",
            _line("【答案】", answer),
            "",
            "[T#B#【题干线索】]",
        ]
    )
    lines.extend(f"- {clue}" for clue in application.get("clue_extraction", []))
    lines.extend(
        [
            "",
            _line("【为什么匹配】", str(application["fit_reasoning"])),
        ]
    )
    for option in options:
        if option != answer:
            lines.extend(
                [
                    "",
                    _line(f"【排除{option}】", str(rejections[option])),
                ]
            )
    lines.extend(
        [
            "",
            _line("【迁移规则】", str(application["transfer_rule"])),
            "",
            _line("【答案唯一性】", str(application["uniqueness_rationale"])),
            "",
            _line(
                "【题目性质】",
                {
                    "authored": "自主创作",
                    "adapted": "原题改编",
                }[application["construction"]["mode"]],
            ),
        ]
    )
    return "\n".join(lines).rstrip()


def render_base_card(record: dict, group_refs: list[dict]) -> str:
    term = str(record["term"])
    core = _core(record)
    meaning = str(record["meaning"])
    lines = [
        f"[P#H1#基础词义｜{term}]",
        "",
        f"{term}是什么意思？做题时怎样识别和辨析？",
        "",
        "---",
        "",
        _line("【核心辨析】", core),
    ]
    if not _same_judgment(core, meaning):
        lines.extend(["", _line("【词义】", meaning)])
    seen = [core, meaning]
    cues = []
    for cue in record.get("recognition_cues", []):
        text = str(cue).strip()
        if _adds_information(text, seen + cues):
            cues.append(text)
    glances = []
    for edge in record.get("comparison_edges") or []:
        other = str(edge.get("other_term") or "").strip()
        glance = str(edge.get("one_glance") or "").strip()
        if not glance:
            glance = _pairwise_glance(
                term, other, str(edge.get("minimum_difference") or "")
            )
            if " vs " in glance:
                _, other_landing = glance.split(" vs ", 1)
                glance = f"{_core_landing(record)} vs {other_landing}"
        if other and glance and _adds_information(
            glance, [item[1] for item in glances]
        ):
            glances.append((other, glance))
    if glances:
        lines.extend(["", "[T#B#【一眼辨析】]"])
        for other, glance in glances:
            lines.append(_line(f"{term} × {other}：", glance))
    novel_dimensions = []
    dimension_seen = seen + cues + [item[1] for item in glances]
    dimension_axes = set()
    for dimension in record.get("dimensions") or []:
        axis = str(dimension.get("axis") or "").strip()
        normalized_axis = _normalized(axis)
        judgment = str(dimension.get("judgment") or "").strip()
        if (
            _is_independent_dimension(axis)
            and normalized_axis not in dimension_axes
            and judgment
            and _adds_information(judgment, dimension_seen)
        ):
            novel_dimensions.append((axis, judgment))
            dimension_axes.add(normalized_axis)
            dimension_seen.append(judgment)
    if len(novel_dimensions) >= 2:
        lines.extend(["", "[T#B,!d16056#【多维判断】]"])
        for axis, judgment in novel_dimensions:
            lines.append(_line(f"{axis}：", judgment))
    boundary = str(record.get("misuse_boundary") or "").strip()
    if boundary and _adds_information(boundary, dimension_seen):
        lines.extend(["", _line("【易错边界】", boundary)])
    contexts = [
        str(context)
        for context in record.get("typical_contexts", [])
        if str(context).strip()
    ]
    if contexts:
        lines.extend(["", "[T#B,!d16056#【典型语境】]"])
        lines.extend(f"- {context}" for context in contexts)
    if cues:
        lines.extend([
            "",
            _line("【附加｜题干可圈出】", "；".join(cues) + "。"),
        ])
    if group_refs:
        lines.extend(["", "[T#B,!d16056#【完整辨析】]"])
        for reference in group_refs:
            lines.append(
                f"[Card#ID/{reference['root_id']}#{reference['title']}]"
            )
    return "\n".join(lines).rstrip()


def render_comparison_card(group: dict, records: list[dict]) -> str:
    by_term = {record["term"]: record for record in records}
    members = list(group["members"])
    title = str(group.get("title") or f"近义辨析｜{'、'.join(members)}")
    lines = [
        f"[P#H1#{title}]",
        "",
        f"{'、'.join(members)}怎么区分？",
        "",
        "---",
    ]
    lines.extend(["", "[T#B#【核心辨析】]"])
    for term in members:
        record = by_term[term]
        lines.append(_line(f"【{term}】", _core(record)))
    meanings = []
    for term in members:
        record = by_term[term]
        meaning = str(record["meaning"])
        if not _same_judgment(_core(record), meaning):
            meanings.append((term, meaning))
    if meanings:
        lines.extend(["", "[T#B#【词义】]"])
        for term, meaning in meanings:
            lines.append(_line(f"【{term}｜词义】", meaning))
    glances = []
    for edge in group.get("minimum_differences") or []:
        left = str(edge.get("left") or "").strip()
        right = str(edge.get("right") or "").strip()
        glance = str(edge.get("one_glance") or "").strip()
        if not glance and left in by_term and right in by_term:
            glance = f"{_core_landing(by_term[left])} vs {_core_landing(by_term[right])}"
        if not glance:
            glance = _pairwise_glance(left, right, str(edge.get("text") or ""))
        if left and right and glance and _adds_information(glance, glances):
            glances.append((left, right, glance))
    if glances:
        lines.extend(["", "[T#B#【一眼辨析】]"])
        for left, right, glance in glances:
            lines.append(_line(f"{left} × {right}：", glance))
    novel_dimensions = []
    selection_texts_by_term = {
        term: [
            str(rule.get("text") or "").strip()
            for rule in group.get("selection_rules") or []
            if str(rule.get("term") or "").strip() == term
        ]
        for term in members
    }
    dimension_axes = set()
    for dimension in group.get("dimensions") or []:
        axis = str(dimension.get("axis") or "").strip()
        normalized_axis = _normalized(axis)
        if not _is_independent_dimension(axis) or normalized_axis in dimension_axes:
            continue
        judgments = dimension.get("judgments") or {}
        novel = []
        for term in members:
            judgment = str(judgments.get(term) or "").strip()
            if judgment and _adds_information(
                judgment,
                [
                    _core(by_term[term]),
                    str(by_term[term].get("meaning") or ""),
                    *selection_texts_by_term[term],
                ],
            ):
                novel.append((term, judgment))
        if len(novel) >= 2:
            novel_dimensions.append((axis, novel))
            dimension_axes.add(normalized_axis)
    if len(novel_dimensions) >= 2:
        lines.extend(["", "[T#B,!d16056#【多维判断】]"])
        for axis, judgments in novel_dimensions:
            lines.append(_line(f"{axis}：", ""))
            for term, judgment in judgments:
                lines.append(f"- {term}：{judgment}")
    rules = []
    for rule in group.get("selection_rules") or []:
        term = str(rule["term"])
        text = str(rule["text"]).strip()
        if _adds_information(text, [_core(by_term[term])]):
            rules.append((term, text))
    if not rules:
        seen_conditions = []
        for edge in group.get("minimum_differences") or []:
            condition = str(edge.get("question_selection_condition") or "").strip()
            if condition and _adds_information(condition, seen_conditions):
                rules.append(("", condition))
                seen_conditions.append(condition)
    if rules:
        lines.extend(["", "[T#B,!d16056#【怎么选】]"])
        for term, text in rules:
            lines.append(f"- {text} → {term}" if term else f"- {text}")
    boundary = str(group.get("misuse_boundary") or "").strip()
    if boundary:
        lines.extend(["", _line("【易错边界】", boundary)])
    contexts = group.get("typical_contexts", [])
    if contexts:
        lines.extend(["", "[T#B,!d16056#【典型语境】]"])
        for context in contexts:
            lines.append(f"- {context}")
    return "\n".join(lines).rstrip()
