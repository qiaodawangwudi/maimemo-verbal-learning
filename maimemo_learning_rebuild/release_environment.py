"""Protected GitHub release environment and secret-isolation boundary."""

from __future__ import annotations

import copy
import os
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from .application_blind_review import strict_json_error


PROTECTED_ENVIRONMENT = "maimemo-final-release"
RECEIPT_FIELDS = {
    "schema_version",
    "receipt_type",
    "release_id",
    "release_hash",
    "approved_sha",
    "github_run_id",
    "github_environment",
    "deployment_status",
}
VALIDATION_FIELDS = {
    "ok",
    "receipt",
    "release_id",
    "release_hash",
    "github_run_id",
}
_APPROVED = object()


def _digest(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _run_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.isascii()
        and value.isdigit()
        and bool(value.strip("0"))
    )


def _strict_json(value: object) -> bool:
    try:
        return strict_json_error(value) is None
    except (RecursionError, OverflowError, TypeError, ValueError):
        return False


@dataclass(frozen=True)
class ReleaseEnvironment:
    """Non-secret GitHub metadata, optionally bound to one approved release."""

    github_sha: str
    github_run_id: str
    release_hash: str
    github_environment: str
    deployment_status: str
    release_id: str = ""
    deck_id: str = ""
    receipt: dict | None = field(default=None, repr=False, compare=False)
    _mapping: Mapping[str, str] = field(default_factory=dict, repr=False, compare=False)
    _authorization: object | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_mapping(cls, env: Mapping[str, str]) -> "ReleaseEnvironment":
        if not isinstance(env, Mapping):
            raise RuntimeError("protected GitHub Actions environment required")
        if env.get("GITHUB_ACTIONS") != "true":
            raise RuntimeError("protected GitHub Actions environment required")
        if env.get("GITHUB_REF") != "refs/heads/main":
            raise RuntimeError("exact main ref required")
        event_name = env.get("GITHUB_EVENT_NAME", "")
        if env.get("GITHUB_HEAD_REF", "") or event_name in {
            "pull_request",
            "pull_request_target",
        }:
            raise RuntimeError("fork or pull request context is forbidden")
        github_sha = env.get("GITHUB_SHA")
        if not _digest(github_sha, 40):
            raise RuntimeError("valid GitHub SHA required")
        github_run_id = env.get("GITHUB_RUN_ID")
        if not _run_id(github_run_id):
            raise RuntimeError("valid GitHub run id required")
        github_environment = env.get("GITHUB_ENVIRONMENT")
        if github_environment != PROTECTED_ENVIRONMENT:
            raise RuntimeError("exact protected environment required")
        deployment_status = env.get("GITHUB_DEPLOYMENT_STATUS")
        if deployment_status != "success":
            raise RuntimeError("successful protected deployment required")
        release_hash = env.get("RELEASE_HASH")
        if not _digest(release_hash, 64):
            raise RuntimeError("valid release hash environment required")
        return cls(
            github_sha=github_sha,
            github_run_id=github_run_id,
            release_hash=release_hash,
            github_environment=github_environment,
            deployment_status=deployment_status,
            _mapping=env,
        )


class _ValidationResult(dict):
    def __init__(self, value: dict, environment: ReleaseEnvironment):
        super().__init__(value)
        self.environment = environment


def _validate_manifest(manifest: object) -> tuple[str, str, str]:
    if not isinstance(manifest, dict) or not _strict_json(manifest):
        raise RuntimeError("valid schema-v2 release manifest required")
    release_id = manifest.get("release_id")
    release_hash = manifest.get("release_hash")
    deck = manifest.get("deck")
    if (
        type(manifest.get("schema_version")) is not int
        or manifest.get("schema_version") != 2
        or not isinstance(release_id, str)
        or not release_id
        or not _digest(release_hash, 64)
        or not isinstance(deck, dict)
        or not isinstance(deck.get("id"), str)
        or not deck.get("id")
    ):
        raise RuntimeError("valid schema-v2 release manifest required")
    return release_id, release_hash, deck["id"]


def validate_github_receipt(receipt: object, manifest: object) -> ReleaseEnvironment:
    """Bind one exact v2 manifest and receipt to the current protected run."""

    release_id, manifest_hash, deck_id = _validate_manifest(manifest)
    if (
        not isinstance(receipt, dict)
        or set(receipt) != RECEIPT_FIELDS
        or not _strict_json(receipt)
        or type(receipt.get("schema_version")) is not int
        or receipt.get("schema_version") != 2
        or receipt.get("receipt_type") != "github_protected_release"
        or not isinstance(receipt.get("release_id"), str)
        or not _digest(receipt.get("release_hash"), 64)
        or not _digest(receipt.get("approved_sha"), 40)
        or not _run_id(receipt.get("github_run_id"))
        or not isinstance(receipt.get("github_environment"), str)
        or not isinstance(receipt.get("deployment_status"), str)
    ):
        raise RuntimeError("strict GitHub receipt required")

    environment = ReleaseEnvironment.from_mapping(os.environ)
    if receipt["release_id"] != release_id:
        raise RuntimeError("release id mismatch")
    if receipt["release_hash"] != manifest_hash:
        raise RuntimeError("release hash mismatch")
    if environment.release_hash != manifest_hash:
        raise RuntimeError("release hash environment mismatch")
    if receipt["approved_sha"] != environment.github_sha:
        raise RuntimeError("approved SHA mismatch")
    if receipt["github_run_id"] != environment.github_run_id:
        raise RuntimeError("GitHub run id mismatch")
    if receipt["github_environment"] != environment.github_environment:
        raise RuntimeError("GitHub environment mismatch")
    if receipt["deployment_status"] != environment.deployment_status:
        raise RuntimeError("deployment status mismatch")

    return replace(
        environment,
        release_id=release_id,
        deck_id=deck_id,
        receipt=copy.deepcopy(receipt),
        _authorization=_APPROVED,
    )


def validate_release_environment(manifest: object, receipt: object) -> dict:
    """Task-7 adapter returning its exact strict success shape."""

    environment = validate_github_receipt(receipt, manifest)
    result = {
        "ok": True,
        "receipt": copy.deepcopy(environment.receipt),
        "release_id": environment.release_id,
        "release_hash": environment.release_hash,
        "github_run_id": environment.github_run_id,
    }
    if set(result) != VALIDATION_FIELDS:
        raise RuntimeError("GitHub release environment receipt is not approved")
    return _ValidationResult(result, environment)


def open_protected_client(environment: ReleaseEnvironment):
    """Read the API token only after every non-secret gate has passed."""

    if not isinstance(environment, ReleaseEnvironment) or (
        environment._authorization is not _APPROVED
    ):
        raise RuntimeError("validated GitHub receipt required")
    if (
        not environment.release_id
        or not environment.deck_id
        or not _digest(environment.github_sha, 40)
        or not _run_id(environment.github_run_id)
        or not _digest(environment.release_hash, 64)
        or environment.github_environment != PROTECTED_ENVIRONMENT
        or environment.deployment_status != "success"
        or not isinstance(environment.receipt, dict)
        or set(environment.receipt) != RECEIPT_FIELDS
    ):
        raise RuntimeError("validated GitHub receipt required")

    token = environment._mapping.get("MAIMEMO_API_TOKEN")
    if not isinstance(token, str) or not token:
        raise RuntimeError("MAIMEMO_API_TOKEN is required")
    try:
        from .api import MaimemoClient, UrllibTransport

        return MaimemoClient(
            UrllibTransport(),
            token=token,
            deck_id=environment.deck_id,
        )
    except Exception as error:
        message = str(error).replace(token, "[REDACTED]")
        message = message.replace(f"Bearer {token}", "Bearer [REDACTED]")
        raise RuntimeError(message) from error
