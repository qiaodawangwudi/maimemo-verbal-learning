"""Compatibility namespace for the runtime bundled by verbal-maimemo-cards."""

from pathlib import Path


_RUNTIME_PACKAGE = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "verbal-maimemo-cards"
    / "scripts"
    / "runtime"
    / "maimemo_learning_rebuild"
)
if not _RUNTIME_PACKAGE.is_dir():
    raise ImportError("verbal-maimemo-cards bundled runtime is missing")

__path__.append(str(_RUNTIME_PACKAGE))
