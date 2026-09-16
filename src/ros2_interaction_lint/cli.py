"""Command-line entry point.

    ros2-lint <workspace>            run every rule
    ros2-lint units <path>           just the unit checks
    ros2-lint topics <path>          just the topic-graph checks
    ros2-lint live <workspace>       static, then cross-check the live graph
    ros2-lint selftest               run on the bundled demo workspace

Exit code is the number of ERROR findings, so CI can gate on it.
"""
from __future__ import annotations

import argparse
import os
import sys

from . import engine, live, loadconfig, report
from .model import LintConfig, RULE_GROUPS, Severity, rel
from .topics import collect_endpoints


def _add_common(p):
    p.add_argument("--config", help="path to a lint.yaml")
    p.add_argument("--exclude", action="append", default=[],
                   help="glob to exclude (repeatable)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--severity", choices=[s.value for s in Severity],
                   default=None, help="minimum severity to report")


def _build_config(args, only=RULE_GROUPS) -> LintConfig:
    cfg = loadconfig.load(getattr(args, "config", None))
    cfg.only = tuple(only)
    if getattr(args, "exclude", None):
        cfg.exclude = tuple(cfg.exclude) + tuple(args.exclude)
    if getattr(args, "severity", None):
        cfg.min_severity = Severity(args.severity)
    return cfg


def _emit(findings, root, as_json):
    if as_json:
        print(report.to_json(findings))
    else:
        print(report.render_text(findings, root))
    return report.exit_code(findings)


def _demo_ws() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    # installed layout: package data not shipped; fall back to repo layout
    for cand in (
        os.path.join(here, "..", "..", "examples", "demo_ws"),
        os.path.join(here, "examples", "demo_ws"),
    ):
        cand = os.path.abspath(cand)
        if os.path.isdir(cand):
            return cand
    return ""


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="ros2-lint",
        description="Static + live linter for ROS 2 interaction, unit, config, "
                    "dependency and interface bugs.")
    sub = parser.add_subparsers(dest="cmd")

    p_all = sub.add_parser("all", help="run every rule on a workspace")
    p_all.add_argument("path")
    _add_common(p_all)

    for g in ("units", "topics", "config", "deps", "interfaces"):
        pg = sub.add_parser(g, help=f"run only the {g} rule on a path")
        pg.add_argument("path")
        _add_common(pg)

    p_live = sub.add_parser("live", help="static topic model + live graph cross-check")
    p_live.add_argument("path")
    _add_common(p_live)

    p_self = sub.add_parser("selftest", help="run on the bundled demo workspace")
    _add_common(p_self)

    # allow the bare form `ros2-lint <path>` (no subcommand)
    if argv and argv[0] not in {"all", "units", "topics", "config", "deps",
                                "interfaces", "live", "selftest", "-h", "--help"}:
        argv = ["all"] + argv

    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 0

    if args.cmd == "selftest":
        ws = _demo_ws()
        if not ws:
            print("demo workspace not found (install did not ship examples/)")
            return 0
        cfg = _build_config(args)
        findings = engine.analyze(ws, cfg)
        return _emit(findings, ws, args.json)

    if args.cmd == "live":
        cfg = _build_config(args)
        static = engine.analyze(args.path, cfg)
        sources = engine.load_sources(args.path, cfg)
        endpoints = collect_endpoints(sources)
        static += live.cross_check(endpoints)
        static.sort(key=lambda f: f.sort_key())
        return _emit(static, args.path, args.json)

    groups = RULE_GROUPS if args.cmd == "all" else (args.cmd,)
    cfg = _build_config(args, only=groups)
    findings = engine.analyze(args.path, cfg)
    return _emit(findings, args.path, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
