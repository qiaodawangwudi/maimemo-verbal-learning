"""Run mandatory learning-quality checks against one hash-bound release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import weakref
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

from .groups import validate_group_registry
from .learning_quality import (
    evaluate_learning_quality,
    learning_review_hash,
    validate_independent_review,
)
from .models import validate_semantic_record
from .release_manifest import _parse_json_artifact
from .release_writer import (
    _StableReleaseSnapshot,
    _load_frozen_release_snapshot,
    _read_stable_release_snapshot,
    _verify_stable_release_snapshot,
)


QUALITY_REPORT_FIELDS = {
    "schema_version",
    "complete",
    "reports",
    "independent_review",
}
REPORT_FIELDS = {"name", "passed"}
REQUIRED_REPORTS = {"public_quality_gate", "application_blind_review"}
INDEPENDENT_REVIEW_FIELDS = {
    "complete",
    "reviewer_context_isolated",
    "resolutions",
    "edge_reviews",
    "comparison_reviews",
    "semantic_registry_hash",
    "group_registry_hash",
    "review_hash",
}
PROTECTED_QUALITY_ENVIRONMENT = "maimemo-final-release"
_QUALITY_CAPABILITY_KEY = object()


class _ProtectedQualityEnvironment(NamedTuple):
    github_actions: str
    github_ref: str
    github_sha: str
    github_run_id: str
    github_environment: str
    deployment_status: str
    github_event_name: str
    github_head_ref: str
    github_base_ref: str
    github_workflow_ref: str
    approved_commit_sha: str
    release_hash: str


def _lower_digest(value: object, length: int) -> bool:
    return (
        type(value) is str
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _positive_run_id(value: object) -> bool:
    return (
        type(value) is str
        and value.isascii()
        and value.isdigit()
        and bool(value.strip("0"))
    )


def _protected_quality_environment(
    mapping: Mapping[str, str], release_hash: str
) -> _ProtectedQualityEnvironment:
    if not isinstance(mapping, Mapping) or mapping.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("protected GitHub Actions review environment required")
    github_ref = mapping.get("GITHUB_REF")
    if github_ref != "refs/heads/main":
        raise RuntimeError("exact main review ref required")
    event = mapping.get("GITHUB_EVENT_NAME")
    head_ref = mapping.get("GITHUB_HEAD_REF", "")
    base_ref = mapping.get("GITHUB_BASE_REF", "")
    if event != "workflow_dispatch" or head_ref or base_ref:
        raise RuntimeError("workflow_dispatch review context required")
    github_sha = mapping.get("GITHUB_SHA")
    approved_sha = mapping.get("APPROVED_COMMIT_SHA")
    if (
        not _lower_digest(github_sha, 40)
        or not _lower_digest(approved_sha, 40)
        or github_sha != approved_sha
    ):
        raise RuntimeError("exact approved review SHA required")
    run_id = mapping.get("GITHUB_RUN_ID")
    if not _positive_run_id(run_id):
        raise RuntimeError("valid GitHub review run id required")
    workflow_ref = mapping.get("GITHUB_WORKFLOW_REF")
    if not isinstance(workflow_ref, str) or re.fullmatch(
        r"[^/\s]+/[^/\s]+/\.github/workflows/maimemo-release\.yml@refs/heads/main",
        workflow_ref,
    ) is None:
        raise RuntimeError("exact protected release workflow required")
    environment = mapping.get("GITHUB_ENVIRONMENT")
    if environment != PROTECTED_QUALITY_ENVIRONMENT:
        raise RuntimeError("exact protected review environment required")
    deployment_status = mapping.get("GITHUB_DEPLOYMENT_STATUS")
    if deployment_status != "success":
        raise RuntimeError("successful protected review deployment required")
    current_release_hash = mapping.get("RELEASE_HASH")
    if not _lower_digest(current_release_hash, 64) or current_release_hash != release_hash:
        raise RuntimeError("protected review release hash mismatch")
    return _ProtectedQualityEnvironment(
        "true",
        github_ref,
        github_sha,
        run_id,
        environment,
        deployment_status,
        event,
        head_ref,
        base_ref,
        workflow_ref,
        approved_sha,
        current_release_hash,
    )


class _ProtectedQualityCapability:
    __slots__ = ("__weakref__",)

    def __new__(cls, key=None):
        if key is not _QUALITY_CAPABILITY_KEY:
            raise TypeError("protected review capability cannot be constructed")
        return super().__new__(cls)

    def __copy__(self):
        raise TypeError("protected review capability cannot be copied")

    def __deepcopy__(self, memo):
        raise TypeError("protected review capability cannot be copied")

    def __reduce__(self):
        raise TypeError("protected review capability cannot be serialized")

    def __reduce_ex__(self, protocol):
        raise TypeError("protected review capability cannot be serialized")


class _ProtectedQualityBinding(NamedTuple):
    environment_mapping: Mapping[str, str]
    environment: _ProtectedQualityEnvironment
    release_dir: Path
    release_hash: str
    sealed_snapshot: _StableReleaseSnapshot
    sealed_digest: str


_QUALITY_CAPABILITIES: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _payload(artifacts: Mapping[str, bytes], key: str) -> tuple[bytes, object]:
    raw = artifacts[key]
    return raw, _parse_json_artifact(raw, key)


def _length_prefixed(value: bytes) -> bytes:
    return len(value).to_bytes(8, "big") + value


def _sealed_snapshot_digest(snapshot: _StableReleaseSnapshot) -> str:
    if type(snapshot) is not _StableReleaseSnapshot:
        raise RuntimeError("sealed protected review snapshot required")
    digest = hashlib.sha256()
    digest.update(_length_prefixed(str(snapshot.release_dir).encode("utf-8")))
    digest.update(_length_prefixed(snapshot.manifest_bytes))
    for key, raw in snapshot.artifacts:
        digest.update(_length_prefixed(key.encode("ascii")))
        digest.update(_length_prefixed(raw))
    for item in snapshot.files:
        for value in (
            item.label,
            str(item.path),
            str(item.device),
            str(item.inode),
            str(item.mode),
            str(item.size),
            str(item.modified_ns),
            item.digest,
        ):
            digest.update(_length_prefixed(value.encode("utf-8")))
    return digest.hexdigest()


def _quality_report_errors(quality_reports: object) -> list[str]:
    if (
        not isinstance(quality_reports, dict)
        or set(quality_reports) != QUALITY_REPORT_FIELDS
    ):
        return ["quality reports schema mismatch"]
    errors: list[str] = []
    if quality_reports.get("schema_version") != 2:
        errors.append("quality reports schema mismatch")
    if quality_reports.get("complete") is not True:
        errors.append("quality reports are incomplete")
    reports = quality_reports.get("reports")
    if not isinstance(reports, list) or any(
        not isinstance(report, dict)
        or set(report) != REPORT_FIELDS
        or not isinstance(report.get("name"), str)
        or type(report.get("passed")) is not bool
        for report in reports or []
    ):
        errors.append("quality reports schema mismatch")
    else:
        names = [report["name"] for report in reports]
        if set(names) != REQUIRED_REPORTS or len(names) != len(REQUIRED_REPORTS):
            errors.append("quality reports coverage mismatch")
        if any(report.get("passed") is not True for report in reports):
            errors.append("quality report did not pass")
    return errors


def _frozen_comparison_review_errors(
    cards: list[dict], manifest: dict, review: dict
) -> list[str]:
    errors: list[str] = []
    final_comparisons = [
        card
        for card in cards
        if isinstance(card, dict) and card.get("card_type") == "comparison"
    ]
    comparison_reviews = review.get("comparison_reviews")
    if not isinstance(comparison_reviews, list):
        comparison_reviews = []
    reviews_by_key: dict[str, list[dict]] = {}
    for comparison_review in comparison_reviews:
        if not isinstance(comparison_review, dict):
            continue
        stable_key = comparison_review.get("stable_card_key")
        if isinstance(stable_key, str) and stable_key:
            reviews_by_key.setdefault(stable_key, []).append(comparison_review)
    frozen_keys: set[str] = set()
    route = manifest.get("chapter_routes", {}).get("comparison", {})
    for card in final_comparisons:
        stable_key = card.get("stable_card_key")
        if not isinstance(stable_key, str) or not stable_key:
            continue
        frozen_keys.add(stable_key)
        matches = reviews_by_key.get(stable_key, [])
        if len(matches) != 1:
            errors.append(
                f"frozen comparison missing independent review: {stable_key}"
            )
            continue
        comparison_review = matches[0]
        content = card.get("content")
        content_digest = (
            hashlib.sha256(content.encode("utf-8")).hexdigest()
            if isinstance(content, str)
            else ""
        )
        expected = {
            "stable_card_key": stable_key,
            "card_type": "comparison",
            "route_id": route.get("id"),
            "route_name": route.get("name"),
            "title": card.get("title"),
            "final_content_hash": content_digest,
        }
        if any(
            comparison_review.get(field) != value
            for field, value in expected.items()
        ):
            errors.append(f"reviewed comparison output mismatch: {stable_key}")
    for stable_key in reviews_by_key:
        if stable_key not in frozen_keys:
            errors.append(
                f"independent comparison review has no frozen card: {stable_key}"
            )
    return errors


def _evaluate_sealed_release_quality(
    snapshot: _StableReleaseSnapshot,
) -> list[str]:
    """Recompute quality only from the exact bytes the writer will execute."""

    manifest, frozen_cards = _load_frozen_release_snapshot(snapshot)
    artifacts = snapshot.artifact_bytes()
    semantic_raw, semantic_payload = _payload(artifacts, "semantic_registry")
    group_raw, group_payload = _payload(artifacts, "group_registry")
    _quality_raw, quality_reports = _payload(artifacts, "quality_reports")

    errors = _quality_report_errors(quality_reports)
    if not isinstance(semantic_payload, dict) or not isinstance(
        semantic_payload.get("records"), list
    ):
        errors.append("semantic registry records are missing")
        records = []
    else:
        records = semantic_payload["records"]
    if not isinstance(group_payload, dict) or not isinstance(
        group_payload.get("groups"), list
    ):
        errors.append("group registry groups are missing")
        groups = []
    else:
        groups = group_payload["groups"]

    review = (
        quality_reports.get("independent_review")
        if isinstance(quality_reports, dict)
        else None
    )
    if not isinstance(review, dict) or set(review) != INDEPENDENT_REVIEW_FIELDS:
        errors.append("independent learning review schema mismatch")
        review = None
    if isinstance(review, dict):
        if review.get("semantic_registry_hash") != _digest(semantic_raw):
            errors.append("independent learning review semantic hash mismatch")
        if review.get("group_registry_hash") != _digest(group_raw):
            errors.append("independent learning review group hash mismatch")
        if review.get("review_hash") != learning_review_hash(review):
            errors.append("independent learning review hash mismatch")
    errors.extend(validate_independent_review(review))

    typed_records = [record for record in records if isinstance(record, dict)]
    if len(typed_records) != len(records):
        errors.append("semantic registry record must be an object")
    for record in typed_records:
        errors.extend(validate_semantic_record(record))
    term_counts = Counter(str(record.get("term") or "") for record in typed_records)
    for term, count in term_counts.items():
        if term and count > 1:
            errors.append(f"duplicate semantic term: {term}")
    known_terms = set(term_counts)
    for record in typed_records:
        for edge in record.get("comparison_edges", []) or []:
            if (
                isinstance(edge, dict)
                and str(edge.get("other_term") or "") not in known_terms
            ):
                errors.append(
                    f"unknown comparison member: {edge.get('other_term', '')}"
                )

    typed_groups = [group for group in groups if isinstance(group, dict)]
    if len(typed_groups) != len(groups):
        errors.append("group registry entry must be an object")
    records_by_term = {
        str(record.get("term") or ""): record for record in typed_records
    }
    errors.extend(validate_group_registry(typed_groups, records_by_term))
    if isinstance(review, dict):
        errors.extend(evaluate_learning_quality(typed_records, typed_groups, review))
        errors.extend(
            _frozen_comparison_review_errors(list(frozen_cards), manifest, review)
        )

    expected_hashes = manifest.get("artifact_hashes", {})
    if expected_hashes.get("semantic_registry") != _digest(semantic_raw):
        errors.append("semantic registry manifest hash mismatch")
    if expected_hashes.get("group_registry") != _digest(group_raw):
        errors.append("group registry manifest hash mismatch")
    return list(dict.fromkeys(errors))


def evaluate_frozen_release_quality(release_dir: Path | str) -> list[str]:
    """Structural precheck; it grants no authority and uses one stable snapshot."""

    return _evaluate_sealed_release_quality(_read_stable_release_snapshot(release_dir))


def _binding_for_quality_capability(capability: object) -> _ProtectedQualityBinding:
    if type(capability) is not _ProtectedQualityCapability:
        raise RuntimeError("protected current-environment review capability required")
    binding = _QUALITY_CAPABILITIES.get(capability)
    if binding is None:
        raise RuntimeError("protected current-environment review capability required")
    return binding


def _assert_quality_environment(binding: _ProtectedQualityBinding) -> None:
    mapping = os.environ
    if mapping is not binding.environment_mapping:
        raise RuntimeError("protected review environment mapping changed")
    if _protected_quality_environment(mapping, binding.release_hash) != binding.environment:
        raise RuntimeError("protected review environment changed after validation")


def _consume_protected_quality_release(
    capability: object,
    release_dir: Path | str | None = None,
    *,
    verify_paths: bool = True,
):
    """Return fresh parsed execution objects from one registry-bound sealed snapshot."""

    binding = _binding_for_quality_capability(capability)
    _assert_quality_environment(binding)
    if release_dir is not None:
        try:
            supplied_dir = Path(release_dir).resolve(strict=True)
        except OSError as error:
            raise RuntimeError("protected review release directory is missing") from error
        if supplied_dir != binding.release_dir:
            raise RuntimeError("protected review release directory mismatch")
    if _sealed_snapshot_digest(binding.sealed_snapshot) != binding.sealed_digest:
        raise RuntimeError("sealed protected review snapshot changed")
    if verify_paths:
        _verify_stable_release_snapshot(binding.sealed_snapshot)
    _assert_quality_environment(binding)
    errors = _evaluate_sealed_release_quality(binding.sealed_snapshot)
    if errors:
        raise RuntimeError("protected learning quality gate failed: " + "; ".join(errors))
    _assert_quality_environment(binding)
    manifest, cards = _load_frozen_release_snapshot(binding.sealed_snapshot)
    if manifest.get("release_hash") != binding.release_hash:
        raise RuntimeError("sealed protected review release hash changed")
    return binding.sealed_snapshot, manifest, cards


def open_protected_quality_capability(
    release_dir: Path | str,
) -> _ProtectedQualityCapability:
    """Authorize exact frozen quality only in the current protected release job."""

    mapping = os.environ
    snapshot = _read_stable_release_snapshot(release_dir)
    canonical = snapshot.release_dir
    manifest, _cards = _load_frozen_release_snapshot(snapshot)
    release_hash = manifest.get("release_hash")
    if not _lower_digest(release_hash, 64):
        raise RuntimeError("protected review release hash is invalid")
    environment = _protected_quality_environment(mapping, release_hash)
    errors = _evaluate_sealed_release_quality(snapshot)
    if errors:
        raise RuntimeError("protected learning quality gate failed: " + "; ".join(errors))
    if os.environ is not mapping:
        raise RuntimeError("protected review environment mapping changed")
    if _protected_quality_environment(mapping, release_hash) != environment:
        raise RuntimeError("protected review environment changed during validation")
    _verify_stable_release_snapshot(snapshot)
    if os.environ is not mapping:
        raise RuntimeError("protected review environment mapping changed")
    if _protected_quality_environment(mapping, release_hash) != environment:
        raise RuntimeError("protected review environment changed during validation")
    capability = _ProtectedQualityCapability(_QUALITY_CAPABILITY_KEY)
    _QUALITY_CAPABILITIES[capability] = _ProtectedQualityBinding(
        mapping,
        environment,
        canonical,
        release_hash,
        snapshot,
        _sealed_snapshot_digest(snapshot),
    )
    return capability


def _revalidate_protected_quality_capability(
    capability: object, release_dir: Path | str | None = None
) -> None:
    _consume_protected_quality_release(capability, release_dir)


def run_release_quality_gate(
    release_dir: Path | str, capability: object
) -> list[str]:
    """Consume a live opaque authority; JSON review files alone never authorize."""

    try:
        _revalidate_protected_quality_capability(capability, release_dir)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        return [str(error)]
    return []


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate one independently reviewed frozen release"
    )
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument(
        "--precheck",
        action="store_true",
        help="run structural checks only; never authorizes a protected write",
    )
    args = parser.parse_args(argv)
    try:
        if args.precheck:
            errors = evaluate_frozen_release_quality(args.release_dir)
        else:
            capability = open_protected_quality_capability(args.release_dir)
            errors = run_release_quality_gate(args.release_dir, capability)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        errors = [str(error)]
    print(
        json.dumps(
            {"ok": not errors, "errors": errors},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
