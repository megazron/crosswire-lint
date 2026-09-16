"""The workspace analyzer: read the tree once, run every enabled rule.

`analyze(path, config)` is the one entry point the CLI, the tests and any
CI script call.
"""
from __future__ import annotations

import os

from . import config as config_rule
from . import deps as deps_rule
from . import interfaces as interfaces_rule
from . import topics as topics_rule
from . import units as units_rule
from .model import Finding, LintConfig, rel, walk_files


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def load_sources(root: str, config: LintConfig) -> dict[str, str]:
    """relfile -> text for every .py under root (excluding launch files, which
    are handled the same way but tagged)."""
    out: dict[str, str] = {}
    for ap in walk_files(root, config, (".py",)):
        out[rel(ap, root)] = _read(ap)
    return out


def load_yaml_texts(root: str, config: LintConfig) -> dict[str, str]:
    out: dict[str, str] = {}
    for ap in walk_files(root, config, (".yaml", ".yml")):
        r = rel(ap, root)
        # a lint config or a package manifest is not a params file
        if os.path.basename(ap) in ("lint.yaml", "lint.yml"):
            continue
        out[r] = _read(ap)
    return out


def analyze(root: str, config: LintConfig | None = None) -> list[Finding]:
    config = config or LintConfig()
    root = os.path.abspath(root)
    groups = config.groups_to_run()
    sources = load_sources(root, config)
    findings: list[Finding] = []

    if "units" in groups:
        for relfile, text in sources.items():
            for f in units_rule.check_source(text, config.units_registry):
                f.file = relfile
                findings.append(f)

    if "topics" in groups:
        findings.extend(topics_rule.analyze_sources(sources))

    if "config" in groups:
        yaml_texts = load_yaml_texts(root, config)
        findings.extend(config_rule.analyze(sources, yaml_texts, config.param_bounds))

    if "deps" in groups:
        findings.extend(deps_rule.analyze(root))

    if "interfaces" in groups:
        findings.extend(interfaces_rule.analyze(sources))

    findings = [f for f in findings if config.keep(f)]
    findings.sort(key=lambda f: f.sort_key())
    return findings
