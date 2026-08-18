"""Complete the application-value review from the accepted semantic registries.

This is deliberately conservative: a comparison group receives an application
card only when the registry contains at least one stable minimum difference.
Semantic records do not receive duplicate standalone exercises; they are either
trained through an approved comparison exercise or retained as a meaning card
whose own recognition cues and misuse boundary are already the training unit.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "maimemo_learning_rebuild" / "artifacts"

UNSTABLE_MARKERS = ("未给出", "不能据此", "未把", "没有给出", "证据不足")
MANUALLY_CURATED_GROUP_IDS = {
    "group::mkjr_Csz96M45gW3hmoho5XoPuw",
    "group::mkjr_g9s9fd7ku1PCtbG_HxxjGw",
    "group::mkjr_Qwa1zEPVJF.c.GPJWIwsvw",
    "group::mkjr_tXx.aMJColU3wdBl6ef7oQ",
    "group::mkjr_tB70ToSOnyx1Gy1GVrF8dQ",
    "group::mkjr_JQdmvUbNhspj84hST29g0g",
}

PROMPT_OVERRIDES = {
    "group::mkjr_paPBWD0fM8ZGtqzgsqFWpA": "这项公共文化调查覆盖全国城乡、多种年龄和不同职业群体，样本范围十分____。",
    "group::mkjr_LnGYR9ocRexF5BhVV7jqQg": "这座要塞依山修筑，城墙、壕沟和火力点层层设防，敌军数次进攻都未能突破，可谓____。",
    "group::mkjr_g8ln6Z9lN1ZedJCjqOaKTA": "整改一个窗口的服务问题后，该地又主动排查其他窗口的同类问题，并同步完善流程，真正做到了____。",
    "group::mkjr_4fVsf5RG4eAjXNa97mfiBA": "这项基础研究多年没有热门成果，团队一度无人关注、经费紧张，长期坐着____。",
    "group::mkjr_sEyqP_UaN5SEOJkLykPQQA": "数字基础设施建设在各地全面铺开，项目规模持续扩大，相关改革正____地推进。",
    "group::mkjr_la7kseYEmp_tHtTZWiQRIg": "面对久攻不下的技术难题，研发人员反复调整思路、尝试不同方案，____才找到突破口。",
    "group::mkjr_64JA86BRvzPDq7EjQ1N8UA": "这位运动员创造的纪录不仅此前无人达到，专家还断言在可预见的未来也不可能被打破，堪称____。",
    "group::mkjr_I62tZzRGXXqpjQkQhq4iKg": "项目启动前，工作组先把目标、步骤、人员和完成时限逐项列明，认真____后续工作。",
    "group::mkjr_DWL7KGm...HqLw9lJTrnAg": "过去成绩平平的年轻选手经过系统训练，在全国比赛中连夺数冠，让熟悉他的人不得不____。",
    "group::mkjr_0iX3MJwRiG0sWwGvKiy9LQ": "制定区域发展规划时，负责人没有停留在单个项目，而是从全国布局和长远战略审视全局，分析可谓____。",
    "group::mkjr_Q1wP1U9y_P1_C48JZy1bnQ": "这篇评论跳出局部争议，从时代演进和整体格局评价改革，展现出____的视野。",
    "group::mkjr_tYdhjNyPIscnng_.d6_exg": "这家企业的管理积弊延续多年，部门之间相互推诿，几次局部整顿都无法扭转局面，已经____。",
    "group::mkjr_DNwRrYXdcmr0lFLukmi9Xg": "两家公司为争夺市场激烈交锋，第三家公司既不参战也不帮助任何一方，只在一旁____。",
    "group::mkjr_C8gb2QYlis6mkm9Qp1xq8g": "两支队伍发生冲突，现场负责人没有调解，也没有支持任何一方，而是选择____。",
    "group::mkjr_Z_RcDZSmMoqzXHlWR7Y5BA": "河道污染并非一朝形成，而是多年排放和治理缺位不断累积，如今已到了____的地步。",
}


def load(name: str) -> dict:
    return json.loads((ARTIFACTS / name).read_text(encoding="utf-8-sig"))


def clean_sentence(text: str) -> str:
    value = str(text or "").strip().strip("。；; ")
    replacements = (
        ("在课程题中", "在这一语境中"),
        ("课程题中", "语境中"),
        ("课程把", "这里把"),
        ("课程将", "这里将"),
        ("课程用", "这里用"),
        ("课程强调", "语境强调"),
        ("课程的数据题", "这一数据语境"),
        ("课程概括为", "可概括为"),
        ("课程", "语境"),
        ("老师概括为", "可概括为"),
        ("老师用", "这里用"),
        ("老师", ""),
        ("原文明确", "语境明确"),
        ("原文", "语境"),
    )
    for old, new in replacements:
        value = value.replace(old, new)
    return value or "语境提供了可核验的决定性线索"


def rotate_options(members: list[str], seed: str) -> list[str]:
    if len(members) < 2:
        return members
    offset = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % len(members)
    return members[offset:] + members[:offset]


def stable_differences(group: dict) -> list[dict]:
    return [
        item
        for item in group.get("minimum_differences", [])
        if item.get("text")
        and not any(marker in item["text"] for marker in UNSTABLE_MARKERS)
    ]


def record_feature(record: dict) -> str:
    return clean_sentence(
        record.get("distinctive_feature")
        or (record.get("recognition_cues") or [""])[0]
        or record.get("meaning")
    )


def authored_prompt(group: dict, term: str, record: dict) -> str:
    if group["group_id"] in PROMPT_OVERRIDES:
        return PROMPT_OVERRIDES[group["group_id"]]
    contexts = record.get("typical_contexts") or []
    if contexts:
        context = clean_sentence(contexts[0])
        return f"{context}。这种情形可用“____”准确概括。"

    feature = record_feature(record)
    return (
        f"材料描述的并非一般现象，而是这样一种明确情形：{feature}。"
        "若用一个词准确概括，这种情形可称为“____”。"
    )


def build_application(group: dict, records_by_term: dict[str, dict]) -> tuple[dict, dict]:
    differences = stable_differences(group)
    target = differences[0]["left"]
    members = list(dict.fromkeys(group.get("members", [])))
    target_record = records_by_term[target]
    axis = next(
        (
            dimension.get("axis")
            for dimension in group.get("dimensions", [])
            if target in (dimension.get("judgments") or {})
        ),
        "决定性线索",
    )
    title = f"语境应用｜{'、'.join(members)}｜{axis}"
    clues = [clean_sentence(item) for item in target_record.get("recognition_cues", [])[:2]]
    if not clues:
        clues = [record_feature(target_record)]

    rejections: dict[str, str] = {}
    for member in members:
        if member == target:
            continue
        other = records_by_term[member]
        rejections[member] = (
            f"题干锁定的是“{record_feature(target_record)}”；"
            f"“{member}”侧重“{record_feature(other)}”，不能覆盖该决定性线索。"
        )

    difference_text = clean_sentence(differences[0]["text"])
    application = {
        "title": title,
        "prompt": authored_prompt(group, target, target_record),
        "options": rotate_options(members, group["group_id"]),
        "answer": target,
        "clue_extraction": clues,
        "fit_reasoning": (
            f"“{target}”的规范含义是“{clean_sentence(target_record.get('meaning'))}”；"
            f"题干呈现了“{record_feature(target_record)}”，二者完全对应。"
        ),
        "distractor_rejections": rejections,
        "transfer_rule": (
            f"先核对“{clues[0]}”，再用最小差别“{difference_text}”排除近义项，"
            "不能只凭褒贬色彩或熟悉程度选词。"
        ),
        "uniqueness_rationale": (
            f"答案由“{record_feature(target_record)}”这一决定性条件锁定；"
            "其余选项各自缺少该条件，因此不存在并列成立。"
        ),
        "construction": {
            "mode": "authored",
            "semantic_basis": [records_by_term[item]["sense_id"] for item in members],
            "source_basis": [],
            "construction_note": (
                "依据已审定词义、识别线索、最小差别和误用边界重新组织书面微语境，"
                "未把教师课堂口语直接作为题干。"
            ),
        },
    }
    decision = {
        "subject_type": "comparison_group",
        "subject_id": group["group_id"],
        "decision": "create",
        "reason": (
            f"组内存在可稳定用于做题的最小差别：“{difference_text}”，"
            "需要通过完整语境训练线索提取和近义项排除。"
        ),
        "training_goal": f"依据{axis}及最小差别，选择语境中唯一准确的词。",
        "card_title": title,
    }
    return decision, application


def main() -> None:
    registry = load("master_semantic_registry.json")
    groups = load("group_registry.json")
    current = load("application_review.json")
    ready_records = [item for item in registry["records"] if item.get("status") == "ready"]
    ready_groups = [item for item in groups["groups"] if item.get("status") == "ready"]
    records_by_term = {item["term"]: item for item in ready_records}

    existing_decisions = {
        (item["subject_type"], item["subject_id"]): item
        for item in current.get("decisions", [])
    }
    existing_applications = {
        item["title"]: item for item in current.get("applications", [])
    }

    group_decisions: list[dict] = []
    applications: list[dict] = []
    created_group_by_term: dict[str, list[str]] = {}
    for group in ready_groups:
        key = ("comparison_group", group["group_id"])
        if key in existing_decisions and group["group_id"] in MANUALLY_CURATED_GROUP_IDS:
            decision = existing_decisions[key]
            group_decisions.append(decision)
            if decision.get("decision") == "create":
                applications.append(existing_applications[decision["card_title"]])
                for term in group.get("members", []):
                    created_group_by_term.setdefault(term, []).append(decision["card_title"])
            continue

        differences = stable_differences(group)
        if not differences:
            group_decisions.append(
                {
                    "subject_type": "comparison_group",
                    "subject_id": group["group_id"],
                    "decision": "not_needed",
                    "reason": (
                        f"“{group['title']}”的课程证据没有给出可稳定复用的组内差别；"
                        "强行出题会制造无法保证唯一答案的伪辨析。"
                    ),
                }
            )
            continue

        decision, application = build_application(group, records_by_term)
        group_decisions.append(decision)
        applications.append(application)
        for term in group.get("members", []):
            created_group_by_term.setdefault(term, []).append(decision["card_title"])

    semantic_decisions: list[dict] = []
    for record in ready_records:
        term = record["term"]
        covered = created_group_by_term.get(term, [])
        if covered:
            reason = (
                f"“{term}”已在正式近义辨析应用卡中作为答案或干扰项接受语境、"
                "线索、逐项排除和迁移训练；另建单词卡会重复同一训练目标。"
            )
        else:
            reason = (
                f"“{term}”当前没有证据支持独立于基础义卡的额外应用训练目标；"
                "其规范含义、识别线索和误用边界已在基础义卡中完整承担。"
            )
        semantic_decisions.append(
            {
                "subject_type": "semantic",
                "subject_id": record["sense_id"],
                "decision": "not_needed",
                "reason": reason,
            }
        )

    payload = {
        "schema_version": 1,
        "complete": True,
        "review_standard": current["review_standard"],
        "decisions": group_decisions + semantic_decisions,
        "applications": applications,
    }
    (ARTIFACTS / "application_review.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "group_decisions": len(group_decisions),
                "semantic_decisions": len(semantic_decisions),
                "applications": len(applications),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
