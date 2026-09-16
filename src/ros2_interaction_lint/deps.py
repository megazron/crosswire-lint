"""Dependency and build declarations.

Compares what a package imports against what its ``package.xml`` declares, and
flags the two cheap, common mistakes:

  * an in-repo/known ROS package imported in code but not declared as a
    ``<depend>`` (works on the author's machine, fails a clean build);
  * a declared ``<depend>`` that nothing in the package imports (rot).

Purely lexical over package.xml (xml.etree) and the package's Python imports.
It only reasons about packages it can map from an import name to a ROS package
name, so it does not flag every third-party import -- it targets ROS deps,
which are the ones a colcon build actually needs and the ones people forget.
"""
from __future__ import annotations

import ast
import os
import xml.etree.ElementTree as ET

from .model import Finding, Severity, rel

# import-name -> ros package name for the common cases
_IMPORT_TO_PKG = {
    "rclpy": "rclpy",
    "std_msgs": "std_msgs",
    "sensor_msgs": "sensor_msgs",
    "geometry_msgs": "geometry_msgs",
    "nav_msgs": "nav_msgs",
    "trajectory_msgs": "trajectory_msgs",
    "tf2_ros": "tf2_ros",
    "tf2_geometry_msgs": "tf2_geometry_msgs",
    "rcl_interfaces": "rcl_interfaces",
    "action_msgs": "action_msgs",
    "control_msgs": "control_msgs",
    "moveit_msgs": "moveit_msgs",
    "visualization_msgs": "visualization_msgs",
    "diagnostic_msgs": "diagnostic_msgs",
    "builtin_interfaces": "builtin_interfaces",
    "launch": "launch",
    "launch_ros": "launch_ros",
    "ament_index_python": "ament_index_python",
}


def _package_dirs(root: str) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        if any(s in dirpath.split(os.sep) for s in
               ("build", "install", "log", ".git", "__pycache__")):
            continue
        if "package.xml" in filenames:
            out.append(dirpath)
            dirnames[:] = [d for d in dirnames]     # keep descending for nested
    return sorted(out)


def _declared_depends(pkg_xml: str) -> set[str]:
    try:
        tree = ET.parse(pkg_xml)
    except ET.ParseError:
        return set()
    tags = ("depend", "build_depend", "exec_depend", "run_depend",
            "build_export_depend", "test_depend")
    out = set()
    for el in tree.getroot():
        if el.tag in tags and el.text:
            out.add(el.text.strip())
    return out


def _imports_in_dir(pkg_dir: str) -> dict[str, tuple[str, int]]:
    """top-level import name -> (relfile, line) for python files under pkg_dir."""
    out: dict[str, tuple[str, int]] = {}
    for dirpath, dirnames, filenames in os.walk(pkg_dir):
        dirnames[:] = [d for d in dirnames if d not in
                       ("build", "install", "log", "__pycache__", ".git")]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            ap = os.path.join(dirpath, name)
            try:
                tree = ast.parse(open(ap, encoding="utf-8", errors="replace").read())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        top = a.name.split(".")[0]
                        out.setdefault(top, (ap, node.lineno))
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    top = node.module.split(".")[0]
                    out.setdefault(top, (ap, node.lineno))
    return out


def analyze(root: str) -> list[Finding]:
    findings: list[Finding] = []
    for pkg_dir in _package_dirs(root):
        pkg_xml = os.path.join(pkg_dir, "package.xml")
        declared = _declared_depends(pkg_xml)
        imports = _imports_in_dir(pkg_dir)
        relxml = rel(pkg_xml, root)

        # imported ROS pkg, not declared
        used_pkgs = set()
        for imp, (ap, line) in sorted(imports.items()):
            pkg = _IMPORT_TO_PKG.get(imp)
            if pkg:
                used_pkgs.add(pkg)
                if pkg not in declared:
                    findings.append(Finding(
                        rule="deps.missing-depend", group="deps",
                        severity=Severity.ERROR,
                        message=(f"'{imp}' is imported but package.xml declares no "
                                 f"<depend>{pkg}</depend>"),
                        fix=f"add <depend>{pkg}</depend> to {relxml}",
                        file=rel(ap, root), line=line))

        # declared ROS pkg, never imported (only for ones we can map, to avoid
        # false positives on message-only or C++ deps)
        known_declared = {d for d in declared if d in _IMPORT_TO_PKG.values()}
        for pkg in sorted(known_declared - used_pkgs):
            findings.append(Finding(
                rule="deps.unused-depend", group="deps", severity=Severity.WARNING,
                message=(f"package.xml declares <depend>{pkg}</depend> but no Python "
                         f"file imports it"),
                fix="remove the stale depend, or confirm it is used elsewhere (C++)",
                file=relxml, line=0))
    return findings
