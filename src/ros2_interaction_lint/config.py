"""Parameter misconfiguration.

Cross-checks the parameters a node ``declare_parameter``s in code against the
parameters set in the workspace's ROS 2 params YAML files, and flags:

  * a parameter declared in code but set in no config (ships whatever default
    the author happened to write, silently);
  * a config key set for a node that the code never declares (a typo, or a
    parameter that moved and left its config behind);
  * a numeric parameter whose configured value is outside a documented
    ``[min, max]`` (from a ``# bounds: lo, hi`` comment or the lint config);
  * the same parameter set under two nodes with different values -- the
    "one fact, two homes" bug that drifts.

Params YAML needs a YAML parser. PyYAML is a declared dependency; if it is
somehow missing the config rule degrades to a single INFO finding rather than
crashing the whole run.
"""
from __future__ import annotations

import ast
import re

from .model import Finding, Severity

_BOUNDS = re.compile(r"#\s*bounds\s*:\s*([-\d.eE]+)\s*,\s*([-\d.eE]+)")


def _load_yaml(text: str):
    try:
        import yaml
    except ImportError:                                       # pragma: no cover
        return None
    try:
        return yaml.safe_load(text)
    except Exception:
        return {}


def declared_params(sources: dict[str, str]) -> dict[str, tuple[str, int, tuple | None]]:
    """param name -> (relfile, line, bounds|None) from declare_parameter calls."""
    out: dict[str, tuple[str, int, tuple | None]] = {}
    for relfile, text in sources.items():
        lines = text.splitlines()
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            fname = fn.attr if isinstance(fn, ast.Attribute) else (
                fn.id if isinstance(fn, ast.Name) else "")
            if fname not in ("declare_parameter", "declare_parameters"):
                continue
            if not node.args:
                continue
            a0 = node.args[0]
            if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                name = a0.value
                bounds = None
                if 1 <= node.lineno <= len(lines):
                    m = _BOUNDS.search(lines[node.lineno - 1])
                    if m:
                        bounds = (float(m.group(1)), float(m.group(2)))
                out[name] = (relfile, node.lineno, bounds)
    return out


def _iter_param_settings(doc, node_path=""):
    """Yield (node_name, param_name, value) from a parsed ROS 2 params doc.

    ROS 2 layout: {node_name: {"ros__parameters": {p: v, nested: {q: w}}}}.
    """
    if not isinstance(doc, dict):
        return
    for node_name, body in doc.items():
        if not isinstance(body, dict):
            continue
        params = body.get("ros__parameters")
        if not isinstance(params, dict):
            # allow a flat doc too
            params = body
        yield from _flatten(node_name, params)


def _flatten(node_name, params, prefix=""):
    for k, v in params.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            yield from _flatten(node_name, v, prefix=key + ".")
        else:
            yield (node_name, key, v)


def configured_params(yaml_texts: dict[str, str]):
    """relfile -> list of (node, param, value)."""
    out = {}
    for relfile, text in yaml_texts.items():
        doc = _load_yaml(text)
        if doc is None:
            out[relfile] = None          # signal: no yaml parser
            continue
        out[relfile] = list(_iter_param_settings(doc))
    return out


def analyze(sources: dict[str, str], yaml_texts: dict[str, str],
            extra_bounds: dict[str, tuple[float, float]] | None = None
            ) -> list[Finding]:
    findings: list[Finding] = []
    declared = declared_params(sources)
    conf = configured_params(yaml_texts)

    if any(v is None for v in conf.values()):
        findings.append(Finding(
            rule="config.no-yaml-parser", group="config", severity=Severity.INFO,
            message="PyYAML not available; config checks skipped",
            fix="pip install pyyaml"))
        conf = {k: v for k, v in conf.items() if v is not None}

    # gather all settings
    settings: list[tuple[str, str, str, object]] = []   # (relfile, node, param, value)
    for relfile, entries in conf.items():
        for node, param, value in entries:
            settings.append((relfile, node, param, value))

    set_names = {param for (_, _, param, _) in settings}

    # declared but never set
    for name, (relfile, line, _bounds) in sorted(declared.items()):
        if name not in set_names:
            findings.append(Finding(
                rule="config.declared-never-set", group="config",
                severity=Severity.WARNING,
                message=(f"parameter '{name}' is declared in code but set in no "
                         f"config file; it ships its in-code default"),
                fix="set it in a params YAML, or confirm the default is intended",
                file=relfile, line=line))

    # set but never declared
    for relfile, node, param, value in settings:
        if param not in declared and not param.startswith("qos_overrides"):
            findings.append(Finding(
                rule="config.set-never-declared", group="config",
                severity=Severity.WARNING,
                message=(f"config sets '{param}' for node '{node}' but no code "
                         f"declares it (typo, or a stale key)"),
                fix="declare it, or remove the stale config key",
                file=relfile, line=0))

    # bounds violations
    all_bounds = dict(extra_bounds or {})
    for name, (_, _, b) in declared.items():
        if b:
            all_bounds[name] = b
    for relfile, node, param, value in settings:
        if param in all_bounds and isinstance(value, (int, float)) and not isinstance(value, bool):
            lo, hi = all_bounds[param]
            if value < lo or value > hi:
                findings.append(Finding(
                    rule="config.out-of-bounds", group="config",
                    severity=Severity.ERROR,
                    message=(f"parameter '{param}' = {value} for '{node}' is outside "
                             f"the documented bounds [{lo}, {hi}]"),
                    fix="fix the value or widen the documented bounds",
                    file=relfile, line=0))

    # same param, two nodes, divergent values
    by_param: dict[str, set] = {}
    where: dict[str, list[tuple[str, str, object]]] = {}
    for relfile, node, param, value in settings:
        try:
            hv = (param, repr(value))
        except Exception:
            continue
        by_param.setdefault(param, set()).add(repr(value))
        where.setdefault(param, []).append((relfile, node, value))
    for param, values in sorted(by_param.items()):
        if len(values) > 1:
            locs = where[param]
            desc = "; ".join(f"{n}={v!r}" for (_, n, v) in locs)
            findings.append(Finding(
                rule="config.divergent-duplicate", group="config",
                severity=Severity.WARNING,
                message=(f"parameter '{param}' is set to different values in "
                         f"different places: {desc}"),
                fix="give this fact one owner rather than one copy per node",
                file=locs[0][0], line=0))

    return findings
