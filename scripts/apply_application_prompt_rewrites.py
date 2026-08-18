"""Apply the finite, reviewed rewrite set to existing application cards."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from maimemo_learning_rebuild.render import render_application_card


GENERIC_MARKERS = (
    "材料描述的并非一般现象，而是这样一种明确情形",
    "若用一个词准确概括，这种情形可称为",
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def rewrite(artifact_dir: Path, rewrite_path: Path, *, apply: bool) -> list[dict]:
    rewrites = load(rewrite_path)
    review_path = artifact_dir / "application_review.json"
    cards_path = artifact_dir / "final_cards.json"
    review = load(review_path)
    final_cards = load(cards_path)

    applications = review.get("applications", [])
    cards = [
        card
        for card in final_cards.get("cards", [])
        if card.get("card_type") == "application"
    ]
    by_title = {card["title"]: card for card in cards}
    if len(by_title) != len(cards):
        raise RuntimeError("application card titles must be unique")

    changes: list[dict] = []
    used: set[str] = set()
    for application in applications:
        prompt = str(application.get("prompt", ""))
        answer = str(application.get("answer", ""))
        if answer not in rewrites:
            continue
        title = str(application.get("title", ""))
        new_prompt = rewrites.get(answer)
        if not isinstance(new_prompt, str) or len(new_prompt.strip()) < 24:
            raise RuntimeError(f"missing usable rewrite: {answer}")
        if any(marker in new_prompt for marker in GENERIC_MARKERS):
            raise RuntimeError(f"rewrite is still a definition restatement: {answer}")
        if answer in new_prompt:
            raise RuntimeError(f"rewrite leaks its answer: {answer}")
        card = by_title.get(title)
        if card is None or card.get("application", {}).get("answer") != answer:
            raise RuntimeError(f"review/final-card mismatch: {title}")

        application["prompt"] = new_prompt
        card["application"]["prompt"] = new_prompt
        content = render_application_card(card["application"])
        card["content"] = content
        card["content_hash"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        changes.append(
            {
                "title": title,
                "answer": answer,
                "before": prompt,
                "after": new_prompt,
            }
        )
        used.add(answer)

    unused = sorted(set(rewrites) - used)
    if unused:
        raise RuntimeError(f"rewrite entries did not match generic cards: {unused}")
    if len(changes) != 103:
        raise RuntimeError(f"expected 103 application rewrites, got {len(changes)}")

    if apply:
        dump(review_path, review)
        dump(cards_path, final_cards)
    return changes


def write_preview(path: Path, changes: list[dict]) -> None:
    lines = [
        "# 场景应用卡题干改写预览",
        "",
        f"共改写 {len(changes)} 张。以下仅展示题干变化，答案与逐项辨析保留在正式卡片中。",
        "",
    ]
    for index, change in enumerate(changes, 1):
        lines.extend(
            [
                f"## {index:03d}｜{change['title']}",
                "",
                f"- 原题干：{change['before']}",
                f"- 新题干：{change['after']}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--rewrites", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--preview", type=Path)
    args = parser.parse_args()
    changes = rewrite(args.artifact_dir, args.rewrites, apply=args.apply)
    if args.preview is not None:
        write_preview(args.preview, changes)
    print(json.dumps({"ok": True, "rewritten": len(changes)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
