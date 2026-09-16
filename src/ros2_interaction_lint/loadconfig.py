"""Load a lint.yaml into a LintConfig. YAML optional; sane defaults without it."""
from __future__ import annotations

import os

from .model import LintConfig, RULE_GROUPS, Severity


def load(path: str | None) -> LintConfig:
    if not path or not os.path.isfile(path):
        return LintConfig()
    try:
        import yaml
        doc = yaml.safe_load(open(path, encoding="utf-8")) or {}
    except Exception:
        return LintConfig()
    only = tuple(doc.get("only", RULE_GROUPS))
    skip = tuple(doc.get("skip", ()))
    exclude = tuple(doc.get("exclude", ()))
    sev = doc.get("min_severity", "info")
    try:
        min_sev = Severity(sev)
    except ValueError:
        min_sev = Severity.INFO
    registry = dict(doc.get("units", {}) or {})
    bounds_raw = doc.get("param_bounds", {}) or {}
    bounds = {}
    for k, v in bounds_raw.items():
        if isinstance(v, (list, tuple)) and len(v) == 2:
            bounds[k] = (float(v[0]), float(v[1]))
    return LintConfig(only=only, skip=skip, exclude=exclude, min_severity=min_sev,
                      units_registry=registry, param_bounds=bounds)
