#!/usr/bin/env python3
"""Install or verify the repository's canonical verbal Maimemo skill."""

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unicodedata
import uuid
from pathlib import Path


RECEIPT_NAME = ".install-receipt.json"
RECEIPT_FIELDS = {
    "schema_version",
    "canonical_hash",
    "installed_hash",
    "merged_commit",
    "source_identity",
    "backup_retained",
    "backup_path",
    "backup_installed_hash",
    "directory_flush_mode",
}
CACHE_DIRECTORY_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
CACHE_FILE_SUFFIXES = {".pyc", ".pyo"}
HASH_PREAMBLE = b"skill-hash-v1\0"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40,64}\Z")
_IS_WINDOWS = os.name == "nt"
DIRECTORY_FLUSH_MODE = "best_effort" if _IS_WINDOWS else "required"


def _lexists(path):
    return os.path.lexists(os.fspath(path))


def _is_reparse(metadata):
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_flag)


def _reject_reparse_components(path, label):
    absolute = Path(os.path.abspath(os.fspath(path)))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if not _lexists(current):
            break
        try:
            metadata = current.lstat()
        except OSError as error:
            raise RuntimeError(f"cannot inspect {label}: {current}") from error
        if _is_reparse(metadata):
            raise RuntimeError(f"{label} contains a symlink or reparse point: {current}")


def _resolve_path(path, label, *, must_exist):
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    candidate = Path(os.path.abspath(os.fspath(candidate)))
    _reject_reparse_components(candidate, label)
    try:
        return candidate.resolve(strict=must_exist)
    except (OSError, RuntimeError) as error:
        raise RuntimeError(f"cannot resolve exact {label}: {candidate}") from error


def _is_relative_to(path, parent):
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _validate_source(path):
    source = _resolve_path(path, "source", must_exist=True)
    if not source.is_dir():
        raise RuntimeError(f"source is not a directory: {source}")
    return source


def _validate_target(path, source):
    target = _resolve_path(path, "target", must_exist=False)
    parent = target.parent
    _reject_reparse_components(parent, "target parent")
    if not parent.is_dir():
        raise RuntimeError(f"target parent is not an existing directory: {parent}")

    anchor = Path(target.anchor).resolve()
    home = Path.home().resolve()
    if target == anchor or target.parent == anchor or target == home:
        raise RuntimeError(f"unsafe target is too broad: {target}")
    if _lexists(target / ".git"):
        raise RuntimeError(f"target is a workspace root: {target}")
    if target == source or _is_relative_to(target, source) or _is_relative_to(source, target):
        raise RuntimeError("source and target overlap")
    if _lexists(target) and not target.is_dir():
        raise RuntimeError(f"target is not a directory: {target}")
    return target


def _normalized_relative(path, root):
    relative = path.relative_to(root).as_posix()
    return unicodedata.normalize("NFC", relative)


def _read_regular_file(path):
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise RuntimeError(f"cannot read skill file safely: {path}") from error
    try:
        before = os.fstat(descriptor)
        if _is_reparse(before) or not stat.S_ISREG(before.st_mode):
            raise RuntimeError(f"skill tree contains a symlink or reparse point: {path}")
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(getattr(before, field, None) != getattr(after, field, None) for field in stable_fields):
        raise RuntimeError(f"skill file changed while hashing: {path}")
    data = b"".join(chunks)
    if len(data) != before.st_size:
        raise RuntimeError(f"skill file changed while hashing: {path}")
    return data


def _snapshot_skill(root):
    root = _validate_source(root)
    snapshot = []
    portable_paths = {}

    def walk(directory):
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as error:
            raise RuntimeError(f"cannot inspect skill directory: {directory}") from error
        for entry in entries:
            path = Path(entry.path)
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise RuntimeError(f"cannot inspect skill entry: {path}") from error
            if _is_reparse(metadata):
                raise RuntimeError(f"skill tree contains a symlink or reparse point: {path}")
            if stat.S_ISDIR(metadata.st_mode):
                if entry.name not in CACHE_DIRECTORY_NAMES:
                    walk(path)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError(f"skill tree contains a non-regular file: {path}")
            if entry.name == RECEIPT_NAME or path.suffix.lower() in CACHE_FILE_SUFFIXES:
                continue
            relative = _normalized_relative(path, root)
            collision_key = unicodedata.normalize("NFC", relative.casefold())
            if collision_key in portable_paths:
                raise RuntimeError(
                    "portable path collision: "
                    f"{portable_paths[collision_key]} and {relative}"
                )
            portable_paths[collision_key] = relative
            snapshot.append((relative, _read_regular_file(path)))

    walk(root)
    snapshot.sort(key=lambda item: item[0].encode("utf-8"))
    return snapshot


def _hash_snapshot(snapshot):
    digest = hashlib.sha256()
    digest.update(HASH_PREAMBLE)
    for relative, data in snapshot:
        encoded_path = relative.encode("utf-8")
        digest.update(struct.pack(">Q", len(encoded_path)))
        digest.update(encoded_path)
        digest.update(struct.pack(">Q", len(data)))
        digest.update(data)
    return digest.hexdigest()


def compute_skill_hash(path):
    """Hash normalized relative file paths and bytes in a safe skill tree."""
    return _hash_snapshot(_snapshot_skill(path))


def _reject_constant(value):
    raise ValueError(f"non-finite JSON constant: {value}")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _metadata_identity(metadata):
    return (metadata.st_dev, metadata.st_ino)


def _metadata_signature(metadata):
    return (
        metadata.st_dev,
        metadata.st_ino,
        stat.S_IFMT(metadata.st_mode),
        metadata.st_size,
        getattr(metadata, "st_mtime_ns", None),
    )


def _read_stable_receipt_bytes(receipt_path):
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = None
    try:
        path_before = receipt_path.lstat()
        if _is_reparse(path_before) or not stat.S_ISREG(path_before.st_mode):
            raise RuntimeError("strict install receipt required")
        descriptor = os.open(receipt_path, flags)
        opened_before = os.fstat(descriptor)
        if (
            _is_reparse(opened_before)
            or not stat.S_ISREG(opened_before.st_mode)
            or _metadata_signature(path_before) != _metadata_signature(opened_before)
        ):
            raise RuntimeError("strict install receipt required")
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        opened_after = os.fstat(descriptor)
        path_after = receipt_path.lstat()
        if (
            _is_reparse(path_after)
            or not stat.S_ISREG(path_after.st_mode)
            or _metadata_signature(opened_before) != _metadata_signature(opened_after)
            or _metadata_signature(opened_after) != _metadata_signature(path_after)
        ):
            raise RuntimeError("strict install receipt required")
        raw = b"".join(chunks)
        if len(raw) != opened_before.st_size:
            raise RuntimeError("strict install receipt required")
        return raw
    except RuntimeError:
        raise
    except OSError as error:
        raise RuntimeError("strict install receipt required") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _validate_receipt(value):
    backup_valid = (
        value.get("backup_retained") is False
        and value.get("backup_path") is None
        and value.get("backup_installed_hash") is None
    ) or (
        value.get("backup_retained") is True
        and isinstance(value.get("backup_path"), str)
        and bool(value["backup_path"])
        and isinstance(value.get("backup_installed_hash"), str)
        and bool(_DIGEST.fullmatch(value["backup_installed_hash"]))
    )
    valid = (
        isinstance(value, dict)
        and set(value) == RECEIPT_FIELDS
        and type(value.get("schema_version")) is int
        and value.get("schema_version") == 1
        and isinstance(value.get("canonical_hash"), str)
        and _DIGEST.fullmatch(value["canonical_hash"])
        and isinstance(value.get("installed_hash"), str)
        and _DIGEST.fullmatch(value["installed_hash"])
        and value["canonical_hash"] == value["installed_hash"]
        and (
            value.get("merged_commit") is None
            or (
                isinstance(value.get("merged_commit"), str)
                and _COMMIT.fullmatch(value["merged_commit"])
            )
        )
        and isinstance(value.get("source_identity"), str)
        and bool(value["source_identity"])
        and "\x00" not in value["source_identity"]
        and type(value.get("backup_retained")) is bool
        and backup_valid
        and value.get("directory_flush_mode") in {"required", "best_effort"}
    )
    if not valid:
        raise RuntimeError("strict install receipt required")
    return value


def _read_receipt(target, *, with_bytes=False):
    receipt_path = target / RECEIPT_NAME
    if not _lexists(receipt_path):
        raise RuntimeError("existing target has no valid receipt")
    try:
        raw = _read_stable_receipt_bytes(receipt_path)
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except RuntimeError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise RuntimeError("strict install receipt required") from error
    _validate_receipt(value)
    if raw != _receipt_bytes(value):
        raise RuntimeError("canonical install receipt required")
    return (value, raw) if with_bytes else value


def _same_identity(actual, expected):
    return os.path.normcase(actual) == os.path.normcase(expected)


def _assert_recorded_target(target, source_identity, *, expected_receipt_bytes=None):
    receipt, receipt_bytes = _read_receipt(target, with_bytes=True)
    if not _same_identity(receipt["source_identity"], source_identity):
        raise RuntimeError("installed skill source identity mismatch")
    if expected_receipt_bytes is not None and receipt_bytes != expected_receipt_bytes:
        raise RuntimeError("installed skill has unrecorded changes")
    if compute_skill_hash(target) != receipt["installed_hash"]:
        raise RuntimeError("installed skill has unrecorded changes")
    return receipt, receipt_bytes


def _verify_retained_backup(receipt, target):
    if not receipt["backup_retained"]:
        return None
    backup = _resolve_path(receipt["backup_path"], "retained backup", must_exist=True)
    if (
        not _same_identity(str(backup), receipt["backup_path"])
        or backup.parent != target.parent
        or not backup.name.startswith(target.name + ".backup-")
        or backup == target
    ):
        raise RuntimeError("retained backup path mismatch")
    backup_receipt, _ = _assert_recorded_target(backup, receipt["source_identity"])
    if backup_receipt["installed_hash"] != receipt["backup_installed_hash"]:
        raise RuntimeError("retained backup hash mismatch")
    return backup


def verify_install(source, target):
    """Fail closed unless target exactly matches its source-bound receipt."""
    source = _validate_source(source)
    target = _validate_target(target, source)
    if not _lexists(target):
        raise RuntimeError(f"installed target does not exist: {target}")
    _reject_reparse_components(target, "target")
    receipt, receipt_bytes = _read_receipt(target, with_bytes=True)
    if not _same_identity(receipt["source_identity"], str(source)):
        raise RuntimeError("installed skill source identity mismatch")
    if receipt["merged_commit"] != _merged_commit(source):
        raise RuntimeError("installed skill merged commit mismatch")
    canonical_hash = compute_skill_hash(source)
    if canonical_hash != receipt["canonical_hash"]:
        raise RuntimeError("canonical source hash mismatch")
    installed_hash = compute_skill_hash(target)
    if installed_hash != receipt["installed_hash"]:
        raise RuntimeError("installed skill has unrecorded changes")
    if canonical_hash != installed_hash:
        raise RuntimeError("installed skill hash does not match canonical source")
    _verify_retained_backup(receipt, target)
    final_receipt, final_bytes = _read_receipt(target, with_bytes=True)
    if final_bytes != receipt_bytes or final_receipt != receipt:
        raise RuntimeError("installed receipt changed during verification")
    return final_receipt


def _merged_commit(source):
    try:
        result = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "--verify", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None
    commit = result.stdout.strip().lower()
    return commit if _COMMIT.fullmatch(commit) else None


def _write_fsynced(path, data):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _flush_directory(path):
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        if _IS_WINDOWS:
            return False
        raise RuntimeError(f"directory flush failed: {path}") from error
    try:
        try:
            os.fsync(descriptor)
        except OSError as error:
            if _IS_WINDOWS:
                return False
            raise RuntimeError(f"directory flush failed: {path}") from error
        return True
    finally:
        os.close(descriptor)


def _stage_snapshot(snapshot, stage):
    for relative, data in snapshot:
        destination = stage.joinpath(*relative.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_fsynced(destination, data)
    directories = {stage}
    for relative, _ in snapshot:
        current = stage.joinpath(*relative.split("/")).parent
        while current != stage:
            directories.add(current)
            current = current.parent
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        _flush_directory(directory)


def _receipt_bytes(receipt):
    return (
        json.dumps(
            receipt,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _owned_sibling(target, purpose):
    return target.parent / f"{target.name}.{purpose}-{uuid.uuid4().hex}"


def _directory_identity(path, label):
    try:
        metadata = Path(path).lstat()
    except OSError as error:
        raise RuntimeError(f"cannot inspect {label}: {path}") from error
    if _is_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError(f"{label} is not an owned regular directory: {path}")
    return _metadata_identity(metadata)


def _matches_directory_identity(path, expected_identity):
    if not _lexists(path):
        return False
    try:
        metadata = Path(path).lstat()
    except OSError:
        return False
    return (
        not _is_reparse(metadata)
        and stat.S_ISDIR(metadata.st_mode)
        and _metadata_identity(metadata) == expected_identity
    )


def _remove_owned_tree(path, target, purpose, expected_identity):
    if purpose not in {"staging", "failed"}:
        raise RuntimeError(f"refusing to remove non-generated {purpose} tree")
    expected_prefix = f"{target.name}.{purpose}-"
    resolved_parent = target.parent.resolve()
    candidate = Path(os.path.abspath(os.fspath(path)))
    if candidate.parent.resolve() != resolved_parent or not candidate.name.startswith(
        expected_prefix
    ):
        raise RuntimeError(f"refusing to remove unverified path: {candidate}")
    if not _lexists(candidate):
        return
    _reject_reparse_components(candidate, f"owned {purpose} path")
    if not _matches_directory_identity(candidate, expected_identity):
        raise RuntimeError(f"owned {purpose} identity changed; tree preserved at {candidate}")
    _snapshot_skill(candidate)
    if not _matches_directory_identity(candidate, expected_identity):
        raise RuntimeError(f"owned {purpose} identity changed; tree preserved at {candidate}")
    shutil.rmtree(candidate)


def _restore_backup(target, backup):
    if _lexists(target):
        return False
    if backup is None or not _lexists(backup):
        raise RuntimeError("rollback backup disappeared")
    os.replace(backup, target)
    _flush_directory(target.parent)
    return True


def _rollback_owned_target(target, target_identity, backup):
    if not _matches_directory_identity(target, target_identity):
        return False
    failed = _owned_sibling(target, "failed")
    os.replace(target, failed)
    if not _matches_directory_identity(failed, target_identity):
        if not _lexists(target):
            os.replace(failed, target)
            _flush_directory(target.parent)
        return False
    if backup is not None:
        if not _restore_backup(target, backup):
            return False
    else:
        _flush_directory(target.parent)
    _remove_owned_tree(failed, target, "failed", target_identity)
    return True


def install(source, target):
    """Install through a file-fsynced stage and ownership-safe namespace swap."""
    source = _validate_source(source)
    target = _validate_target(target, source)
    source_identity = str(source)
    had_target = _lexists(target)
    previous_receipt = None
    previous_receipt_bytes = None
    if had_target:
        _reject_reparse_components(target, "target")
        previous_receipt, previous_receipt_bytes = _assert_recorded_target(
            target, source_identity
        )

    snapshot = _snapshot_skill(source)
    canonical_hash = _hash_snapshot(snapshot)
    backup = _owned_sibling(target, "backup") if had_target else None
    receipt = {
        "schema_version": 1,
        "canonical_hash": canonical_hash,
        "installed_hash": canonical_hash,
        "merged_commit": _merged_commit(source),
        "source_identity": source_identity,
        "backup_retained": had_target,
        "backup_path": str(backup) if had_target else None,
        "backup_installed_hash": (
            previous_receipt["installed_hash"] if had_target else None
        ),
        "directory_flush_mode": DIRECTORY_FLUSH_MODE,
    }
    _validate_receipt(receipt)

    stage = Path(
        tempfile.mkdtemp(prefix=f"{target.name}.staging-", dir=target.parent)
    ).resolve()
    stage_identity = _directory_identity(stage, "staging directory")
    stage_owned = True
    backup_moved = False
    try:
        _stage_snapshot(snapshot, stage)
        _write_fsynced(stage / RECEIPT_NAME, _receipt_bytes(receipt))
        _flush_directory(stage)
        if compute_skill_hash(stage) != canonical_hash:
            raise RuntimeError("staged skill hash does not match canonical source")
        if _read_receipt(stage) != receipt:
            raise RuntimeError("staged install receipt verification failed")
        if compute_skill_hash(source) != canonical_hash:
            raise RuntimeError("canonical source changed during installation")

        _reject_reparse_components(target.parent, "target parent")
        if had_target:
            _assert_recorded_target(
                target,
                source_identity,
                expected_receipt_bytes=previous_receipt_bytes,
            )
            os.replace(target, backup)
            backup_moved = True
            try:
                _assert_recorded_target(
                    backup,
                    source_identity,
                    expected_receipt_bytes=previous_receipt_bytes,
                )
            except Exception:
                if _lexists(target):
                    raise RuntimeError(
                        f"target changed during swap; original preserved at {backup}"
                    )
                os.replace(backup, target)
                backup_moved = False
                _flush_directory(target.parent)
                raise
        elif _lexists(target):
            raise RuntimeError("target appeared during installation")

        try:
            os.replace(stage, target)
        except Exception as error:
            if _matches_directory_identity(stage, stage_identity):
                if _lexists(target):
                    backup_note = (
                        f"; recorded backup preserved at {backup}" if backup_moved else ""
                    )
                    raise RuntimeError(
                        f"installation failed; foreign target preserved{backup_note}"
                    ) from error
                if backup_moved:
                    _restore_backup(target, backup)
                    backup_moved = False
                    raise RuntimeError("installation failed; original restored") from error
                raise RuntimeError("installation failed; no target retained") from error
            stage_owned = False
            if _matches_directory_identity(target, stage_identity):
                rollback_backup = backup if backup_moved else None
                if _rollback_owned_target(target, stage_identity, rollback_backup):
                    backup_moved = False
                    if had_target:
                        raise RuntimeError("installation failed; original restored") from error
                    raise RuntimeError("installation failed; no target retained") from error
            backup_note = f"; recorded backup preserved at {backup}" if backup_moved else ""
            raise RuntimeError(
                f"installation failed; foreign target preserved{backup_note}"
            ) from error

        stage_owned = False
        if not _matches_directory_identity(target, stage_identity):
            backup_note = f"; recorded backup preserved at {backup}" if backup_moved else ""
            raise RuntimeError(
                f"installed target identity changed; foreign target preserved{backup_note}"
            )

        try:
            _flush_directory(target.parent)
            verified = verify_install(source, target)
            if verified != receipt:
                raise RuntimeError("installed receipt changed during verification")
        except Exception as error:
            if _rollback_owned_target(target, stage_identity, backup if backup_moved else None):
                backup_moved = False
                if had_target:
                    raise RuntimeError("installation failed; original restored") from error
                raise RuntimeError("installation failed; no target retained") from error
            backup_note = f"; recorded backup preserved at {backup}" if backup_moved else ""
            raise RuntimeError(
                f"installation failed; foreign target preserved{backup_note}"
            ) from error

        if had_target:
            try:
                _assert_recorded_target(
                    backup,
                    source_identity,
                    expected_receipt_bytes=previous_receipt_bytes,
                )
            except Exception as error:
                raise RuntimeError(
                    f"installation completed; changed backup preserved at {backup}"
                ) from error
        return receipt
    finally:
        if stage_owned and _lexists(stage):
            _remove_owned_tree(stage, target, "staging", stage_identity)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Install or verify the canonical verbal Maimemo skill by hash."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--install", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = install(args.source, args.target) if args.install else verify_install(
            args.source, args.target
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
