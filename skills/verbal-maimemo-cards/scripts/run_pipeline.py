#!/usr/bin/env python3
"""Run the self-contained verbal Maimemo workflow from an installed Skill."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import runpy
import shutil
import sys


SKILL_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = Path(__file__).resolve().parent / "runtime"
ASSET_ROOT = SKILL_ROOT / "assets" / "github"

STAGE_MODULES = {
    "collect-sources": "maimemo_learning_rebuild.sources",
    "review-semantics": "maimemo_learning_rebuild.review",
    "reconcile-library": "maimemo_learning_rebuild.reconciliation",
    "build-groups": "maimemo_learning_rebuild.groups",
    "review-dimensions": "maimemo_learning_rebuild.dimension_review",
    "build-applications": "maimemo_learning_rebuild.application_candidates",
    "review-applications": "maimemo_learning_rebuild.application_quality_gate",
    "build-plan": "maimemo_learning_rebuild.planning",
    "public-preflight": "maimemo_learning_rebuild.public_quality_gate",
    "release-quality": "maimemo_learning_rebuild.release_quality_gate",
    "authorize": "maimemo_learning_rebuild.guard",
    "write-release": "maimemo_learning_rebuild.release_writer",
}

REQUIRED_RUNTIME_MODULES = (
    "source_inventory",
    "review",
    "reconciliation",
    "learning_quality",
    "dimension_review",
    "application_quality_gate",
    "content_acceptance_v2",
    "release_manifest",
    "release_environment",
    "release_writer",
    "readback",
    "guard",
)


def _activate_runtime() -> None:
    runtime = str(RUNTIME_ROOT)
    if runtime not in sys.path:
        sys.path.insert(0, runtime)


def _self_check() -> int:
    _activate_runtime()
    origins: dict[str, str] = {}
    for name in REQUIRED_RUNTIME_MODULES:
        module = importlib.import_module(f"maimemo_learning_rebuild.{name}")
        origin = Path(module.__file__).resolve()
        if not origin.is_relative_to(RUNTIME_ROOT.resolve()):
            raise RuntimeError(f"runtime escaped installed Skill: {name}")
        origins[name] = str(origin.relative_to(RUNTIME_ROOT))

    templates = (
        ASSET_ROOT / "CODEOWNERS",
        ASSET_ROOT / "workflows" / "learning-quality-gate.yml",
        ASSET_ROOT / "workflows" / "maimemo-release.yml",
    )
    templates_ready = all(path.is_file() for path in templates)
    if not templates_ready:
        raise RuntimeError("GitHub protected-release templates are incomplete")

    print(
        json.dumps(
            {
                "status": "passed",
                "runtime_origin": "installed_skill",
                "runtime_modules": origins,
                "github_templates_ready": True,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _install_github_templates(target: Path, *, force: bool) -> int:
    target = target.resolve()
    if not (target / ".git").exists():
        raise RuntimeError("target must be a Git repository")
    destinations = {
        ASSET_ROOT / "CODEOWNERS": target / ".github" / "CODEOWNERS",
        ASSET_ROOT / "workflows" / "learning-quality-gate.yml": (
            target / ".github" / "workflows" / "learning-quality-gate.yml"
        ),
        ASSET_ROOT / "workflows" / "maimemo-release.yml": (
            target / ".github" / "workflows" / "maimemo-release.yml"
        ),
    }
    runtime_source = RUNTIME_ROOT / "maimemo_learning_rebuild"
    runtime_destination = target / "maimemo_learning_rebuild"
    for source in runtime_source.glob("*.py"):
        destinations[source] = runtime_destination / source.name
    for source, destination in destinations.items():
        if destination.exists() and destination.read_bytes() != source.read_bytes() and not force:
            raise RuntimeError(f"refusing to overwrite changed template: {destination}")
    for source, destination in destinations.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    print(json.dumps({"status": "installed", "target": str(target)}, ensure_ascii=False))
    return 0


def _run_stage(stage: str, arguments: list[str]) -> int:
    _activate_runtime()
    module_name = STAGE_MODULES[stage]
    sys.argv = [module_name, *arguments]
    runpy.run_module(module_name, run_name="__main__")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the self-contained verbal Maimemo card workflow."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("self-check")

    install = subparsers.add_parser("install-github-templates")
    install.add_argument("--target", type=Path, required=True)
    install.add_argument("--force", action="store_true")

    for stage in STAGE_MODULES:
        subparsers.add_parser(stage, add_help=False)

    args, stage_arguments = parser.parse_known_args(argv)
    if args.command == "self-check":
        if stage_arguments:
            parser.error("self-check does not accept stage arguments")
        return _self_check()
    if args.command == "install-github-templates":
        if stage_arguments:
            parser.error("unrecognized template arguments")
        return _install_github_templates(args.target, force=args.force)
    return _run_stage(args.command, stage_arguments)


if __name__ == "__main__":
    raise SystemExit(main())
