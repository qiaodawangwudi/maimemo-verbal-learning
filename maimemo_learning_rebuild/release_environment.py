"""Opaque protected-release capability and secret-isolation boundary."""

from __future__ import annotations

import json
import os
import weakref
from collections.abc import Mapping
from typing import NamedTuple

from .application_blind_review import strict_json_error
from .release_manifest import (
    load_release_manifest_bytes,
    validate_release_manifest_envelope,
)


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
_CAPABILITY_KEY = object()
_QUALITY_CLIENT_KEY = object()


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


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def validate_receipt_contract(
    receipt: object,
    *,
    release_id: object | None = None,
    release_hash: object | None = None,
) -> tuple[str, ...]:
    """Validate the one exact protected-release receipt contract and binding."""

    if (
        not isinstance(receipt, dict)
        or set(receipt) != RECEIPT_FIELDS
        or not _strict_json(receipt)
        or type(receipt.get("schema_version")) is not int
        or receipt.get("schema_version") != 2
        or receipt.get("receipt_type") != "github_protected_release"
        or not isinstance(receipt.get("release_id"), str)
        or not receipt.get("release_id")
        or not _digest(receipt.get("release_hash"), 64)
        or not _digest(receipt.get("approved_sha"), 40)
        or not _run_id(receipt.get("github_run_id"))
        or receipt.get("github_environment") != PROTECTED_ENVIRONMENT
        or receipt.get("deployment_status") != "success"
    ):
        return ("strict GitHub receipt required",)
    errors: list[str] = []
    if release_id is not None and receipt["release_id"] != release_id:
        errors.append("release id mismatch")
    if release_hash is not None and receipt["release_hash"] != release_hash:
        errors.append("release hash mismatch")
    return tuple(errors)


class _EnvironmentSnapshot(NamedTuple):
    github_actions: str
    github_ref: str
    github_sha: str
    github_run_id: str
    github_environment: str
    deployment_status: str
    release_hash: str
    github_event_name: str
    github_head_ref: str
    github_base_ref: str


def _snapshot_environment(env: Mapping[str, str]) -> _EnvironmentSnapshot:
    if not isinstance(env, Mapping) or env.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("protected GitHub Actions environment required")
    github_ref = env.get("GITHUB_REF")
    if github_ref != "refs/heads/main":
        raise RuntimeError("exact main ref required")
    event_name = env.get("GITHUB_EVENT_NAME")
    head_ref = env.get("GITHUB_HEAD_REF", "")
    base_ref = env.get("GITHUB_BASE_REF", "")
    if event_name != "workflow_dispatch" or head_ref or base_ref:
        raise RuntimeError("workflow_dispatch release context required")
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
    return _EnvironmentSnapshot(
        "true",
        github_ref,
        github_sha,
        github_run_id,
        github_environment,
        deployment_status,
        release_hash,
        event_name,
        head_ref,
        base_ref,
    )


class ReleaseEnvironment:
    """Non-authorizing facade for strict non-secret environment validation."""

    def __new__(cls, *args, **kwargs):
        raise TypeError("ReleaseEnvironment is not constructible")

    @classmethod
    def from_mapping(cls, env: Mapping[str, str]) -> _EnvironmentSnapshot:
        return _snapshot_environment(env)


class _ReleaseCapability:
    __slots__ = ("__weakref__",)

    def __new__(cls, key=None):
        if key is not _CAPABILITY_KEY:
            raise TypeError("release capability cannot be constructed")
        return super().__new__(cls)

    def __copy__(self):
        raise TypeError("release capability cannot be copied")

    def __deepcopy__(self, memo):
        raise TypeError("release capability cannot be copied")

    def __reduce__(self):
        raise TypeError("release capability cannot be serialized")

    def __reduce_ex__(self, protocol):
        raise TypeError("release capability cannot be serialized")


class _CapabilityBinding(NamedTuple):
    environment_mapping: Mapping[str, str]
    environment: _EnvironmentSnapshot
    release_id: str
    release_hash: str
    deck_id: str
    receipt_bytes: bytes
    manifest_bytes: bytes


_CAPABILITIES: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


class _FrozenDict(dict):
    def _immutable(self, *args, **kwargs):
        raise TypeError("validated release result is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable

    def __setattr__(self, name, value):
        raise TypeError("validated release result is immutable")

    def __delattr__(self, name):
        raise TypeError("validated release result is immutable")

    def __copy__(self):
        raise TypeError("validated release result cannot be copied")

    def __deepcopy__(self, memo):
        raise TypeError("validated release result cannot be copied")

    def __reduce__(self):
        raise TypeError("validated release result cannot be serialized")

    def __reduce_ex__(self, protocol):
        raise TypeError("validated release result cannot be serialized")


class _ValidationResult(_FrozenDict):
    pass


_VALIDATIONS: dict[int, tuple[weakref.ReferenceType, _ReleaseCapability, bytes]] = {}


def _register_validation(
    result: _ValidationResult,
    capability: _ReleaseCapability,
) -> None:
    identity = id(result)

    def discard(reference, identity=identity):
        current = _VALIDATIONS.get(identity)
        if current is not None and current[0] is reference:
            _VALIDATIONS.pop(identity, None)

    reference = weakref.ref(result, discard)
    _VALIDATIONS[identity] = (reference, capability, _canonical(result))


def _capability_for_validation(validation: object) -> _ReleaseCapability:
    if type(validation) is not _ValidationResult:
        raise RuntimeError("GitHub release environment receipt is not approved")
    registered = _VALIDATIONS.get(id(validation))
    if (
        registered is None
        or registered[0]() is not validation
        or set(validation) != VALIDATION_FIELDS
        or not _strict_json(validation)
    ):
        raise RuntimeError("GitHub release environment receipt is not approved")
    try:
        unchanged = _canonical(validation) == registered[2]
    except (TypeError, ValueError, OverflowError, RecursionError):
        unchanged = False
    capability = registered[1]
    if not unchanged or capability not in _CAPABILITIES:
        raise RuntimeError("GitHub release environment receipt is not approved")
    return capability


def validate_github_receipt(receipt: object, manifest: object) -> _ReleaseCapability:
    """Return an opaque capability bound to one fully authorized v2 release."""

    manifest_errors = validate_release_manifest_envelope(manifest)
    if manifest_errors:
        raise RuntimeError("validated authorized schema-v2 release manifest required")
    try:
        manifest_bytes = _canonical(manifest)
        frozen_manifest = load_release_manifest_bytes(manifest_bytes)
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise RuntimeError(
            "validated authorized schema-v2 release manifest required"
        ) from None
    if validate_release_manifest_envelope(frozen_manifest):
        raise RuntimeError("validated authorized schema-v2 release manifest required")
    release_id = frozen_manifest["release_id"]
    release_hash = frozen_manifest["release_hash"]
    receipt_errors = validate_receipt_contract(
        receipt,
        release_id=release_id,
        release_hash=release_hash,
    )
    if receipt_errors:
        raise RuntimeError(receipt_errors[0])

    receipt_bytes = _canonical(receipt)
    frozen_receipt = json.loads(receipt_bytes.decode("utf-8"))

    mapping = os.environ
    environment = ReleaseEnvironment.from_mapping(mapping)
    if environment.release_hash != release_hash:
        raise RuntimeError("release hash environment mismatch")
    if frozen_receipt["approved_sha"] != environment.github_sha:
        raise RuntimeError("approved SHA mismatch")
    if frozen_receipt["github_run_id"] != environment.github_run_id:
        raise RuntimeError("GitHub run id mismatch")
    if frozen_receipt["github_environment"] != environment.github_environment:
        raise RuntimeError("GitHub environment mismatch")
    if frozen_receipt["deployment_status"] != environment.deployment_status:
        raise RuntimeError("deployment status mismatch")
    try:
        inputs_unchanged = (
            _canonical(manifest) == manifest_bytes
            and _canonical(receipt) == receipt_bytes
        )
    except (TypeError, ValueError, OverflowError, RecursionError):
        inputs_unchanged = False
    if not inputs_unchanged:
        raise RuntimeError("release authorization inputs changed during validation")

    capability = _ReleaseCapability(_CAPABILITY_KEY)
    _CAPABILITIES[capability] = _CapabilityBinding(
        mapping,
        environment,
        release_id,
        release_hash,
        frozen_manifest["deck"]["id"],
        receipt_bytes,
        manifest_bytes,
    )
    return capability


def validate_release_environment(manifest: object, receipt: object) -> dict:
    """Return Task 7's exact immutable five-key success shape."""

    capability = validate_github_receipt(receipt, manifest)
    binding = _CAPABILITIES[capability]
    frozen_receipt = _FrozenDict(json.loads(binding.receipt_bytes.decode("utf-8")))
    result = _ValidationResult(
        {
            "ok": True,
            "receipt": frozen_receipt,
            "release_id": binding.release_id,
            "release_hash": binding.release_hash,
            "github_run_id": binding.environment.github_run_id,
        }
    )
    _register_validation(result, capability)
    return result


def _revalidate_release_capability(capability: object):
    if type(capability) is not _ReleaseCapability:
        raise RuntimeError("validated GitHub receipt required")
    binding = _CAPABILITIES.get(capability)
    if binding is None:
        raise RuntimeError("validated GitHub receipt required")

    current_mapping = os.environ
    if current_mapping is not binding.environment_mapping:
        raise RuntimeError("protected release environment mapping changed")
    current = ReleaseEnvironment.from_mapping(current_mapping)
    if current != binding.environment:
        raise RuntimeError("protected release environment changed after validation")
    receipt = json.loads(binding.receipt_bytes.decode("utf-8"))
    if validate_receipt_contract(
        receipt,
        release_id=binding.release_id,
        release_hash=binding.release_hash,
    ):
        raise RuntimeError("validated GitHub receipt required")
    if (
        receipt["approved_sha"] != current.github_sha
        or receipt["github_run_id"] != current.github_run_id
        or receipt["github_environment"] != current.github_environment
        or receipt["deployment_status"] != current.deployment_status
        or receipt["release_hash"] != current.release_hash
    ):
        raise RuntimeError("validated GitHub receipt required")
    return binding, current_mapping


def _discard_client_secret(client) -> None:
    if client is not None:
        try:
            client._token = ""
        except Exception:
            pass


def _construct_protected_client(binding, current_mapping, post_token_check):
    """Read the secret once; any later drift yields only one redacted failure."""

    from .api import MaimemoClient, UrllibTransport

    if os.environ is not current_mapping:
        raise RuntimeError("protected release environment changed before token access")
    failed = False
    client = None
    token = None
    try:
        token = current_mapping.get("MAIMEMO_API_TOKEN")
        if not isinstance(token, str) or not token:
            raise RuntimeError("missing protected token")
        client = MaimemoClient(
            UrllibTransport(),
            token=token,
            deck_id=binding.deck_id,
        )
        post_token_check()
    except Exception:
        failed = True
    token = None
    if failed:
        _discard_client_secret(client)
        client = None
        _raise_protected_client_failure()
    return client


def open_protected_client(capability: object):
    """Revalidate live non-secret state, then read the token exactly once."""

    binding, current_mapping = _revalidate_release_capability(capability)

    def post_token_check():
        checked, checked_mapping = _revalidate_release_capability(capability)
        if checked is not binding or checked_mapping is not current_mapping:
            raise RuntimeError("protected release environment changed")

    return _construct_protected_client(binding, current_mapping, post_token_check)


class _ProtectedQualityClient:
    """Delegate reads, but revalidate both authorities before every POST."""

    __slots__ = ("__weakref__",)

    def __new__(cls, key=None):
        if key is not _QUALITY_CLIENT_KEY:
            raise TypeError("protected quality client cannot be constructed")
        return super().__new__(cls)

    def __copy__(self):
        raise TypeError("protected quality client cannot be copied")

    def __deepcopy__(self, memo):
        raise TypeError("protected quality client cannot be copied")

    def __reduce__(self):
        raise TypeError("protected quality client cannot be serialized")

    def __reduce_ex__(self, protocol):
        raise TypeError("protected quality client cannot be serialized")

    def _binding(self):
        binding = _QUALITY_CLIENTS.get(self)
        if binding is None:
            raise RuntimeError("protected quality client is no longer valid")
        return binding

    @property
    def deck_id(self):
        return self._binding().client.deck_id

    def read_deck(self):
        return self._binding().client.read_deck()

    def update_card(self, card_id, content, guard):
        binding = self._binding()
        binding.pre_write()
        return binding.client.update_card(card_id, content, guard)

    def create_card(self, chapter_id, content, guard):
        binding = self._binding()
        binding.pre_write()
        return binding.client.create_card(chapter_id, content, guard)


class _ProtectedQualityClientBinding(NamedTuple):
    client: object
    pre_write: object


_QUALITY_CLIENTS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def open_protected_quality_client(
    capability: object,
    quality_capability: object,
    release_dir=None,
):
    """Atomically consume Task 8 + sealed Task 11 authority before token access."""

    binding, current_mapping = _revalidate_release_capability(capability)
    from . import release_quality_gate

    consume = release_quality_gate._consume_protected_quality_release
    sealed_snapshot, manifest, cards = consume(
        quality_capability, release_dir, verify_paths=True
    )
    release_quality_gate._verify_stable_release_snapshot(sealed_snapshot)
    try:
        exact_manifest = _canonical(manifest) == binding.manifest_bytes
    except (TypeError, ValueError, OverflowError, RecursionError):
        exact_manifest = False
    if not exact_manifest:
        raise RuntimeError("protected review and release manifest differ")
    try:
        execution_bytes = _canonical(
            {
                "manifest": manifest,
                "cards": list(cards),
                "snapshot": cards.snapshot,
            }
        )
    except (AttributeError, TypeError, ValueError, OverflowError, RecursionError):
        raise RuntimeError("sealed protected execution payload is invalid") from None
    checked, checked_mapping = _revalidate_release_capability(capability)
    if checked is not binding or checked_mapping is not current_mapping:
        raise RuntimeError("protected release environment changed before token access")
    release_quality_gate._assert_quality_environment(
        release_quality_gate._binding_for_quality_capability(quality_capability)
    )

    def revalidate_both(*, verify_paths):
        checked_binding, checked_environment = _revalidate_release_capability(capability)
        if checked_binding is not binding or checked_environment is not current_mapping:
            raise RuntimeError("protected release environment changed")
        current_snapshot, current_manifest, _current_cards = consume(
            quality_capability,
            release_dir,
            verify_paths=verify_paths,
        )
        if (
            current_snapshot is not sealed_snapshot
            or _canonical(current_manifest) != binding.manifest_bytes
        ):
            raise RuntimeError("sealed protected release changed")
        try:
            execution_unchanged = _canonical(
                {
                    "manifest": manifest,
                    "cards": list(cards),
                    "snapshot": cards.snapshot,
                }
            ) == execution_bytes
        except (AttributeError, TypeError, ValueError, OverflowError, RecursionError):
            execution_unchanged = False
        if not execution_unchanged:
            raise RuntimeError("sealed protected execution payload changed")

    client = _construct_protected_client(
        binding,
        current_mapping,
        lambda: revalidate_both(verify_paths=False),
    )
    protected_client = _ProtectedQualityClient(_QUALITY_CLIENT_KEY)
    _QUALITY_CLIENTS[protected_client] = _ProtectedQualityClientBinding(
        client,
        lambda: revalidate_both(verify_paths=True),
    )
    return protected_client, manifest, cards


def _raise_protected_client_failure() -> None:
    raise RuntimeError("protected client could not be opened [REDACTED]")
