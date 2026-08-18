"""Repository-only release gate for GitHub branch protection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .reconciliation import reconciliation_hash, semantic_registry_hash


def evaluate_public_gate(
    registry: dict, groups: dict, plan: dict, final_cards: dict
) -> list[str]:
    errors: list[str] = []
    records = registry.get("records", [])
    group_records = groups.get("groups", [])
    actions = plan.get("actions", [])
    reconciliation = plan.get("library_reconciliation")
    if reconciliation is None:
        errors.append("public gate library reconciliation is missing")
    else:
        if not isinstance(reconciliation, dict):
            errors.append("public gate library reconciliation is invalid")
        else:
            if reconciliation.get("status") != "passed":
                errors.append("public gate library reconciliation is not passed")
            if reconciliation.get("semantic_registry_hash") != semantic_registry_hash(
                records
            ):
                errors.append(
                    "public gate semantic registry differs from reconciliation"
                )
            try:
                if reconciliation.get("reconciliation_hash") != reconciliation_hash(
                    reconciliation
                ):
                    errors.append("public gate library reconciliation hash mismatch")
            except (TypeError, ValueError, OverflowError, RecursionError):
                errors.append("public gate library reconciliation hash mismatch")

    non_ready_records = sum(record.get("status") != "ready" for record in records)
    if non_ready_records:
        errors.append(f"semantic records still require review: {non_ready_records}")
    non_ready_groups = sum(group.get("status") != "ready" for group in group_records)
    if non_ready_groups:
        errors.append(f"comparison groups still require review: {non_ready_groups}")
    planned_base_creates = {
        str(action.get("title") or "").removeprefix("基础词义｜")
        for action in actions
        if action.get("action") == "create"
        and str(action.get("title") or "").startswith("基础词义｜")
    }
    missing_base_groups = sum(
        any(
            term not in planned_base_creates
            for term in group.get("audit", {}).get("missing_base_terms", [])
        )
        for group in group_records
    )
    if missing_base_groups:
        errors.append(f"comparison groups have missing base cards: {missing_base_groups}")
    manual_actions = sum(action.get("action") == "manual-review" for action in actions)
    if manual_actions:
        errors.append(f"action plan still contains manual review: {manual_actions}")
    if not final_cards.get("complete"):
        errors.append("final card set is not marked complete")
    if len(final_cards.get("cards", [])) != plan.get("expected_after"):
        errors.append("final card count does not match expected library size")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()

    def load(name: str) -> dict:
        return json.loads((args.artifact_dir / name).read_text(encoding="utf-8-sig"))

    errors = evaluate_public_gate(
        load("master_semantic_registry.json"),
        load("group_registry.json"),
        load("action_plan.json"),
        load("final_cards.json"),
    )
    print(json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
