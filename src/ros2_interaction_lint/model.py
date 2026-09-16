"""Core data types: findings, severities, and the lint configuration.

Nothing here imports rclpy or ros2. The static core is stdlib-only so it runs
in CI on a machine with no ROS installed.
"""
from __future__ import annotations

import dataclasses
import fnmatch
import os
from enum import Enum
from typing import Iterable


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    def rank(self) -> int:
        return {"error": 3, "warning": 2, "info": 1}[self.value]


# The rule groups, used for grouping output and for `--only`/`--skip`.
RULE_GROUPS = ("units", "topics", "config", "deps", "interfaces")


@dataclasses.dataclass
class Finding:
    """One problem, anchored to a file and line where possible."""

    rule: str                      # e.g. "units.deg-into-rad"
    group: str                     # one of RULE_GROUPS
    severity: Severity
    message: str
    fix: str = ""
    file: str = ""                 # workspace-relative path
    line: int = 0                  # 1-indexed, 0 = whole file / not applicable

    def as_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["severity"] = self.severity.value
        return d

    def location(self) -> str:
        if not self.file:
            return "(workspace)"
        return f"{self.file}:{self.line}" if self.line else self.file

    def sort_key(self):
        return (self.file, self.line, self.group, self.rule)


@dataclasses.dataclass
class LintConfig:
    """What to run and what to ignore.

    `units_registry` maps a "pkg/Msg.field" path (or a bare field name) to a
    unit string, extending the built-in ROS conventions. `param_bounds` maps a
    parameter name to (min, max). Both usually come from a lint.yaml.
    """

    only: tuple[str, ...] = RULE_GROUPS
    skip: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()          # glob patterns on workspace-relative paths
    min_severity: Severity = Severity.INFO
    units_registry: dict[str, str] = dataclasses.field(default_factory=dict)
    param_bounds: dict[str, tuple[float, float]] = dataclasses.field(default_factory=dict)

    def groups_to_run(self) -> tuple[str, ...]:
        return tuple(g for g in RULE_GROUPS if g in self.only and g not in self.skip)

    def is_excluded(self, rel_path: str) -> bool:
        rel_path = rel_path.replace(os.sep, "/")
        for pat in self.exclude:
            pat = pat.replace(os.sep, "/")
            if fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(rel_path, pat + "/*"):
                return True
            # match a bare directory name anywhere in the path
            if "/" not in pat and pat in rel_path.split("/"):
                return True
        return False

    def keep(self, f: Finding) -> bool:
        return f.severity.rank() >= self.min_severity.rank()


# Directories we never descend into.
SKIP_DIRS = frozenset({
    "build", "install", "log", ".git", "__pycache__", ".pytest_cache",
    "node_modules", ".tox", ".mypy_cache",
})


def _looks_like_venv(path: str) -> bool:
    return (
        os.path.isfile(os.path.join(path, "pyvenv.cfg"))
        or os.path.basename(path).startswith(".venv")
        or os.path.basename(path).startswith("venv")
    )


def walk_files(root: str, config: LintConfig, suffixes: Iterable[str]) -> list[str]:
    """Every file under `root` with one of `suffixes`, honouring skips/excludes.

    Returns absolute paths. Deterministic order (sorted) so output is stable.
    """
    suffixes = tuple(suffixes)
    out: list[str] = []
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        # prune in-place so os.walk does not descend
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in SKIP_DIRS and not _looks_like_venv(os.path.join(dirpath, d))
        )
        for name in sorted(filenames):
            if not name.endswith(suffixes):
                continue
            ap = os.path.join(dirpath, name)
            rel = os.path.relpath(ap, root)
            if config.is_excluded(rel):
                continue
            out.append(ap)
    return sorted(out)


def rel(path: str, root: str) -> str:
    try:
        return os.path.relpath(path, root).replace(os.sep, "/")
    except ValueError:
        return path
