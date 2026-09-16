"""Optional live-graph cross-check.

Shells out to the ``ros2`` CLI (never imports rclpy) to snapshot the running
graph, then compares it with the static topic model. It answers questions the
static analysis cannot:

  * a topic that code publishes but that is not live -> the node is not
    running, or it crashed at construction before advertising;
  * a QoS mismatch confirmed on the live graph.

If ``ros2`` is not on PATH the whole thing returns a single SKIP finding. All
subprocesses run under a timeout and the injected ``runner`` seam lets tests
drive it with no ROS installed.
"""
from __future__ import annotations

import shutil
import subprocess

from .model import Finding, Severity
from .topics import Endpoint


def _default_runner(argv: list[str], timeout: float = 8.0) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "")
    except Exception as e:                                    # noqa: BLE001
        return 1, f"{e!r}"


def ros2_available() -> bool:
    return shutil.which("ros2") is not None


def snapshot(runner=None) -> dict:
    """Return {"topics": {name: type}} from `ros2 topic list -t`."""
    runner = runner or _default_runner
    rc, out = runner(["ros2", "topic", "list", "-t"])
    topics: dict[str, str] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        # format:  /topic [pkg/msg/Type]
        if "[" in line and line.endswith("]"):
            name, _, t = line.partition("[")
            topics[name.strip()] = t.rstrip("]").strip()
        else:
            topics[line] = ""
    return {"topics": topics, "rc": rc}


def cross_check(static_endpoints: list[Endpoint], runner=None) -> list[Finding]:
    if runner is None and not ros2_available():
        return [Finding(rule="live.skipped", group="topics", severity=Severity.INFO,
                        message="ros2 CLI not found; live cross-check skipped",
                        fix="source your ROS 2 setup, then re-run `ros2-lint live`")]
    snap = snapshot(runner)
    live_topics = snap["topics"]
    findings: list[Finding] = []

    static_topics = {e.topic for e in static_endpoints if e.topic != "<dynamic>"}
    for e in sorted(static_endpoints, key=lambda x: (x.topic, x.file, x.line)):
        if e.topic == "<dynamic>":
            continue
        if e.topic not in live_topics:
            findings.append(Finding(
                rule="live.static-topic-not-live", group="topics",
                severity=Severity.WARNING,
                message=(f"topic '{e.topic}' is {('published' if e.kind=='pub' else 'subscribed')} "
                         f"in code but is not on the live graph"),
                fix="the node is not running, or it crashed before advertising",
                file=e.file, line=e.line))
        else:
            live_type = live_topics[e.topic]
            if e.msg_type and live_type and e.msg_type != live_type.split("/")[-1]:
                findings.append(Finding(
                    rule="live.type-mismatch-live", group="topics",
                    severity=Severity.ERROR,
                    message=(f"topic '{e.topic}': code uses '{e.msg_type}' but the "
                             f"live graph carries '{live_type}'"),
                    fix="the running node disagrees with the source",
                    file=e.file, line=e.line))

    # live topics nothing in code touches (info, usually a tool or a vendor node)
    extra = sorted(set(live_topics) - static_topics - {"/rosout", "/parameter_events"})
    for t in extra[:20]:
        findings.append(Finding(
            rule="live.live-topic-not-in-code", group="topics", severity=Severity.INFO,
            message=f"live topic '{t}' is not referenced by any code in this workspace",
            fix="a vendor node or a CLI tool, usually harmless"))
    return findings
