"""Extract source-bound application prompts without approving them as cards."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


LECTURE_MARKERS = (
    "侧重点",
    "这个词",
    "指的是",
    "意思是",
    "形容",
    "选项",
    "答案",
    "同学",
    "对不对",
    "可以吗",
    "认识一下",
    "咱们",
    "来看一下",
    "代入",
    "主要是",
    "主要指",
    "就是说",
    "所谓",
    "字面",
    "拆分",
    "可以吧",
    "记住",
    "区别在",
)


def extract_context_candidates(record: dict, option_terms: list[str]) -> list[dict]:
    term = str(record["term"])
    candidates: list[dict] = []
    seen_prompts: set[str] = set()
    for evidence in record.get("evidence", []):
        quote = str(evidence.get("quote") or "")
        for sentence in re.split(r"(?<=[。！？；])", quote):
            sentence = sentence.strip()
            if term not in sentence or not 24 <= len(sentence) <= 160:
                continue
            if any(marker in sentence for marker in LECTURE_MARKERS):
                continue
            prompt = sentence.replace(term, "______")
            if any(other != term and other in prompt for other in option_terms):
                continue
            if prompt in seen_prompts:
                continue
            seen_prompts.add(prompt)
            candidate_id = hashlib.sha256(
                f"{term}\n{evidence.get('source')}\n{evidence.get('location')}\n{prompt}".encode(
                    "utf-8"
                )
            ).hexdigest()[:16]
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "status": "pending",
                    "source_material_only": True,
                    "formal_prompt_eligible": False,
                    "prompt": prompt,
                    "answer": term,
                    "options": list(option_terms),
                    "source": str(evidence.get("source") or ""),
                    "location": str(evidence.get("location") or ""),
                    "rejection_reason": "",
                }
            )
    return candidates


def build_candidate_queue(registry: dict, groups: dict) -> dict:
    records = {
        record["term"]: record
        for record in registry.get("records", [])
        if record.get("status") == "ready"
    }
    grouped_terms = {
        term for group in groups.get("groups", []) for term in group.get("members", [])
    }
    group_queue: list[dict] = []
    for group in groups.get("groups", []):
        if group.get("status") != "ready":
            continue
        members = list(group.get("members", []))
        candidates = [
            candidate
            for term in members
            for candidate in extract_context_candidates(records[term], members)
        ]
        group_queue.append(
            {
                "subject_type": "comparison_group",
                "subject_id": group["group_id"],
                "members": members,
                "status": "pending",
                "candidates": candidates,
            }
        )

    semantic_queue: list[dict] = []
    for record in registry.get("records", []):
        term = record.get("term")
        if record.get("status") != "ready" or term in grouped_terms:
            continue
        edges = record.get("comparison_edges") or []
        options = [term]
        if edges:
            options.append(str(edges[0]["other_term"]))
        candidates = (
            extract_context_candidates(record, options) if len(options) >= 2 else []
        )
        semantic_queue.append(
            {
                "subject_type": "semantic",
                "subject_id": record["sense_id"],
                "term": term,
                "status": "pending",
                "candidates": candidates,
            }
        )

    return {
        "schema_version": 1,
        "complete": False,
        "warning": "这是原始语境素材索引，不是应用题候选成品；必须理解词义后自主创作或深度改编，禁止直接生成正式应用卡。",
        "totals": {
            "comparison_groups": len(group_queue),
            "comparison_groups_with_candidates": sum(
                bool(item["candidates"]) for item in group_queue
            ),
            "standalone_semantics": len(semantic_queue),
            "standalone_semantics_with_candidates": sum(
                bool(item["candidates"]) for item in semantic_queue
            ),
        },
        "comparison_groups": group_queue,
        "standalone_semantics": semantic_queue,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--groups", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    queue = build_candidate_queue(
        json.loads(args.registry.read_text(encoding="utf-8-sig")),
        json.loads(args.groups.read_text(encoding="utf-8-sig")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(queue["totals"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
