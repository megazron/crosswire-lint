import os

from ros2_interaction_lint import engine, live, report
from ros2_interaction_lint.cli import main
from ros2_interaction_lint.model import LintConfig, Severity
from ros2_interaction_lint.topics import Endpoint

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.abspath(os.path.join(HERE, "..", "examples", "demo_ws"))


def test_demo_workspace_fires_every_group():
    findings = engine.analyze(DEMO)
    groups = {f.group for f in findings}
    assert groups == {"units", "topics", "config", "deps", "interfaces"}


def test_demo_has_errors_and_nonzero_exit():
    findings = engine.analyze(DEMO)
    assert report.error_count(findings) >= 6
    assert report.exit_code(findings) == report.error_count(findings)


def test_deps_missing_and_unused_present():
    findings = engine.analyze(DEMO)
    rules = {f.rule for f in findings}
    assert "deps.missing-depend" in rules
    assert "deps.unused-depend" in rules


def test_only_and_skip():
    only = engine.analyze(DEMO, LintConfig(only=("units",)))
    assert {f.group for f in only} == {"units"}
    skip = engine.analyze(DEMO, LintConfig(skip=("units", "topics", "config", "deps")))
    assert {f.group for f in skip} == {"interfaces"}


def test_exclude_glob():
    full = engine.analyze(DEMO, LintConfig(only=("units",)))
    excl = engine.analyze(DEMO, LintConfig(only=("units",), exclude=("*talker.py",)))
    assert len(excl) < len(full)


def test_min_severity_filters_warnings():
    errs = engine.analyze(DEMO, LintConfig(min_severity=Severity.ERROR))
    assert all(f.severity == Severity.ERROR for f in errs)


def test_json_render_is_valid():
    import json
    findings = engine.analyze(DEMO)
    doc = json.loads(report.to_json(findings))
    assert doc["summary"]["error"] >= 1
    assert len(doc["findings"]) == len(findings)


# ---- live cross-check with an injected fake ros2 -----------------------
def _fake_runner_ok(argv, timeout=8.0):
    # pretend /scan is live with the right type, /cmd is absent
    return 0, "/scan [std_msgs/msg/Float64]\n/rosout [rcl_interfaces/msg/Log]\n"


def test_live_cross_check_flags_absent_topic():
    eps = [
        Endpoint("pub", "/scan", "Float64", "reliable", "a.py", 1),
        Endpoint("sub", "/cmd", "Int32", "reliable", "b.py", 2),
    ]
    findings = live.cross_check(eps, runner=_fake_runner_ok)
    rules = {f.rule for f in findings}
    assert "live.static-topic-not-live" in rules   # /cmd not live


def test_live_type_mismatch_against_graph():
    eps = [Endpoint("pub", "/scan", "Int32", "reliable", "a.py", 1)]
    findings = live.cross_check(eps, runner=_fake_runner_ok)
    assert "live.type-mismatch-live" in {f.rule for f in findings}


def test_live_skips_without_ros2(monkeypatch):
    monkeypatch.setattr(live, "ros2_available", lambda: False)
    findings = live.cross_check([], runner=None)
    assert findings and findings[0].rule == "live.skipped"


# ---- cli ---------------------------------------------------------------
def test_cli_bare_path_runs_all(capsys):
    code = main([DEMO])
    out = capsys.readouterr().out
    assert code >= 1
    assert "[units]" in out and "[topics]" in out


def test_cli_json_flag(capsys):
    code = main([DEMO, "--json"])
    out = capsys.readouterr().out
    assert '"findings"' in out and code >= 1


def test_cli_single_group(capsys):
    main(["units", DEMO])
    out = capsys.readouterr().out
    assert "[units]" in out and "[topics]" not in out


def test_cli_selftest(capsys):
    code = main(["selftest"])
    out = capsys.readouterr().out
    assert "[units]" in out and code >= 1
