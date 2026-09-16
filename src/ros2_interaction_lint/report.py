"""Rendering: grouped text and JSON, plus the CI exit code.

The exit code is the number of ERROR findings, so a CI step can gate on
``ros2-lint <ws>`` returning non-zero. Warnings and info never fail the build.
"""
from __future__ import annotations

import json

from .model import Finding, RULE_GROUPS, Severity

_ICON = {Severity.ERROR: "E", Severity.WARNING: "W", Severity.INFO: "i"}


def error_count(findings: list[Finding]) -> int:
    return sum(1 for f in findings if f.severity == Severity.ERROR)


def exit_code(findings: list[Finding]) -> int:
    return error_count(findings)


def to_json(findings: list[Finding]) -> str:
    return json.dumps({
        "summary": summary_counts(findings),
        "findings": [f.as_dict() for f in findings],
    }, indent=2)


def summary_counts(findings: list[Finding]) -> dict:
    c = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        c[f.severity.value] += 1
    return c


def render_text(findings: list[Finding], root: str = "") -> str:
    lines: list[str] = []
    header = f"crosswire-lint  ({root})" if root else "crosswire-lint"
    lines.append(header)
    lines.append("=" * len(header))
    if not findings:
        lines.append("no findings.")
        return "\n".join(lines)

    by_group: dict[str, list[Finding]] = {}
    for f in findings:
        by_group.setdefault(f.group, []).append(f)

    for group in RULE_GROUPS:
        group_findings = by_group.get(group)
        if not group_findings:
            continue
        lines.append("")
        lines.append(f"[{group}]  {len(group_findings)} finding(s)")
        for f in group_findings:
            lines.append(f"  {_ICON[f.severity]} {f.location()}")
            lines.append(f"      {f.message}   ({f.rule})")
            if f.fix:
                lines.append(f"      fix: {f.fix}")

    c = summary_counts(findings)
    lines.append("")
    lines.append(f"summary: {c['error']} error(s), {c['warning']} warning(s), "
                 f"{c['info']} info")
    lines.append(f"exit code: {exit_code(findings)}")
    return "\n".join(lines)
