"""Render validated semantic records as layered Markji learning cards."""

from __future__ import annotations

import re


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
    if cues:
        lines.extend(["", _line("【题干关键词】", "；".join(cues) + "。")])
    boundary = str(record.get("misuse_boundary") or "").strip()
    if boundary and _adds_information(boundary, seen + cues):
        lines.extend(["", _line("【易错边界】", boundary)])
    contexts = [
        str(context)
        for context in record.get("typical_contexts", [])
        if str(context).strip()
    ]
    if contexts:
        lines.extend(["", "[T#B,!d16056#【典型语境】]"])
        lines.extend(f"- {context}" for context in contexts)
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
