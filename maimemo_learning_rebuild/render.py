"""Render validated semantic records as layered Markji learning cards."""

from __future__ import annotations


def _line(label: str, text: str) -> str:
    return f"[T#B#{label}]{text}"


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
        ]
    )
    return "\n".join(lines).rstrip()


def render_base_card(record: dict, group_refs: list[dict]) -> str:
    term = str(record["term"])
    lines = [
        f"[P#H1#基础词义｜{term}]",
        "",
        f"{term}是什么意思？做题时怎样识别和辨析？",
        "",
        "---",
        "",
        _line("【词义】", str(record["meaning"])),
        "",
        _line("【特别之处】", str(record["distinctive_feature"])),
    ]
    cues = [str(cue) for cue in record.get("recognition_cues", []) if str(cue).strip()]
    if cues:
        lines.extend(["", _line("【做题识别点】", "；".join(cues) + "。")])
    edges = record.get("comparison_edges", [])
    if edges:
        lines.extend(["", "[T#B#【一眼辨析】]"])
        for edge in edges:
            other = str(edge["other_term"])
            lines.append(
                _line(
                    f"{term} × {other}：",
                    str(edge["minimum_difference"]),
                )
            )
    dimensions = record.get("dimensions", [])
    if dimensions:
        lines.extend(["", "[T#B,!d16056#【多维判断】]"])
        for dimension in dimensions:
            lines.append(
                _line(
                    f"{dimension['axis']}：",
                    str(dimension["judgment"]),
                )
            )
    boundary = str(record.get("misuse_boundary") or "").strip()
    if boundary:
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
    for term in members:
        record = by_term[term]
        lines.extend(
            [
                "",
                _line(f"【{term}｜词义】", str(record["meaning"])),
                _line(
                    f"【{term}｜特别之处】",
                    str(record["distinctive_feature"]),
                ),
            ]
        )
    differences = group.get("minimum_differences", [])
    if differences:
        lines.extend(["", "[T#B,!d16056#【最小差别】]"])
        for edge in differences:
            lines.append(
                _line(
                    f"{edge['left']} × {edge['right']}：",
                    str(edge["text"]),
                )
            )
    dimensions = group.get("dimensions", [])
    if dimensions:
        lines.extend(["", "[T#B,!d16056#【多维判断】]"])
        for dimension in dimensions:
            lines.append(_line(f"{dimension['axis']}：", ""))
            judgments = dimension.get("judgments", {})
            for term in members:
                judgment = str(judgments.get(term) or "").strip()
                if judgment:
                    lines.append(f"- {term}：{judgment}")
    boundary = str(group.get("misuse_boundary") or "").strip()
    if boundary:
        lines.extend(["", _line("【易错边界】", boundary)])
    contexts = group.get("typical_contexts", [])
    if contexts:
        lines.extend(["", "[T#B,!d16056#【典型语境】]"])
        for context in contexts:
            lines.append(f"- {context}")
    return "\n".join(lines).rstrip()
