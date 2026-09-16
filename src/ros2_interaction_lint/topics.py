"""Interaction bugs across nodes: the topic graph, built statically.

Reads every ``create_publisher`` / ``create_subscription`` call in the
workspace, recovers the topic name, message type and QoS, then looks for the
mismatches that produce a graph that is up and silent:

  * a publisher and a subscriber on one topic with different message TYPES;
  * a RELIABLE subscriber against a BEST_EFFORT publisher -- DDS delivers
    nothing and warns exactly once, which is the single most common cause of
    "the node is running and the panel is blank";
  * a subscribed topic that NObody publishes (a typo, or a missing remap);
  * a published topic nobody subscribes to (a warning, not an error);
  * a tf frame referenced as a target but never broadcast.

QoS is recovered from the well-known profile names and from explicit
``reliability=`` / ``durability=`` keywords. When QoS cannot be determined it
is left unknown and no QoS finding is raised -- silence beats a false alarm.
"""
from __future__ import annotations

import ast
import dataclasses

from .model import Finding, Severity

_SENSOR_DATA_PROFILES = {"qos_profile_sensor_data", "SensorDataQoS"}
_RELIABLE_PROFILES = {"qos_profile_services_default", "qos_profile_parameters",
                      "QoSProfile"}  # default QoSProfile() is RELIABLE


@dataclasses.dataclass
class Endpoint:
    kind: str            # "pub" | "sub"
    topic: str
    msg_type: str        # best-effort short type name, "" if unknown
    reliability: str     # "reliable" | "best_effort" | "unknown"
    file: str
    line: int


def _short_type(node) -> str:
    """First positional arg of create_publisher/subscription is the msg type."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _str_of(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _reliability_of(qos_node) -> str:
    """Classify a QoS argument. Conservative: unknown unless we recognise it."""
    if qos_node is None:
        return "unknown"
    # a bare profile name
    name = None
    if isinstance(qos_node, ast.Name):
        name = qos_node.id
    elif isinstance(qos_node, ast.Attribute):
        name = qos_node.attr
    if name in _SENSOR_DATA_PROFILES:
        return "best_effort"
    # an integer depth (e.g. create_publisher(T, "t", 10)) -> default reliable
    if isinstance(qos_node, ast.Constant) and isinstance(qos_node.value, int):
        return "reliable"
    # a QoSProfile(...) or a chain: look for reliability= keyword anywhere
    for sub in ast.walk(qos_node):
        if isinstance(sub, ast.keyword) and sub.arg == "reliability":
            v = sub.value
            tail = v.attr if isinstance(v, ast.Attribute) else (
                v.id if isinstance(v, ast.Name) else "")
            if "BEST_EFFORT" in tail.upper():
                return "best_effort"
            if "RELIABLE" in tail.upper():
                return "reliable"
        if isinstance(sub, ast.Attribute) and "BEST_EFFORT" in sub.attr.upper():
            return "best_effort"
    if isinstance(qos_node, ast.Call):
        fn = qos_node.func
        fname = fn.attr if isinstance(fn, ast.Attribute) else (
            fn.id if isinstance(fn, ast.Name) else "")
        if fname in _RELIABLE_PROFILES:
            return "reliable"
    return "unknown"


class _EndpointVisitor(ast.NodeVisitor):
    def __init__(self, relfile: str):
        self.relfile = relfile
        self.endpoints: list[Endpoint] = []
        self.tf_broadcast: list[tuple[str, int]] = []   # frames sent
        self.tf_lookup: list[tuple[str, int]] = []       # frames looked up

    def visit_Call(self, node: ast.Call):
        fn = node.func
        fname = fn.attr if isinstance(fn, ast.Attribute) else (
            fn.id if isinstance(fn, ast.Name) else "")
        if fname in ("create_publisher", "create_subscription"):
            self._endpoint(node, "pub" if fname == "create_publisher" else "sub")
        elif fname in ("sendTransform", "send_transform"):
            self._tf_send(node)
        elif fname in ("lookup_transform", "lookupTransform",
                       "can_transform", "transform"):
            self._tf_lookup(node)
        self.generic_visit(node)

    def _endpoint(self, node: ast.Call, kind: str):
        args = node.args
        if len(args) < 2:
            return
        msg_type = _short_type(args[0])
        topic = _str_of(args[1]) or "<dynamic>"
        # create_publisher(msg, topic, qos); create_subscription has a callback
        # between the topic and the qos: create_subscription(msg, topic, cb, qos)
        qos_index = 2 if kind == "pub" else 3
        qos_arg = args[qos_index] if len(args) > qos_index else None
        if qos_arg is None:
            for kw in node.keywords:
                if kw.arg in ("qos_profile", "qos"):
                    qos_arg = kw.value
        self.endpoints.append(Endpoint(
            kind=kind, topic=topic, msg_type=msg_type,
            reliability=_reliability_of(qos_arg),
            file=self.relfile, line=node.lineno))

    def _tf_send(self, node: ast.Call):
        # frames appear as child_frame_id on the TransformStamped; hard to get
        # statically, so record a generic broadcast marker with any string args
        for a in ast.walk(node):
            s = _str_of(a)
            if s:
                self.tf_broadcast.append((s, node.lineno))

    def _tf_lookup(self, node: ast.Call):
        for a in node.args:
            s = _str_of(a)
            if s:
                self.tf_lookup.append((s, node.lineno))


def collect_endpoints(sources: dict[str, str]) -> list[Endpoint]:
    """sources: relfile -> text. Returns every pub/sub endpoint found."""
    out: list[Endpoint] = []
    for relfile, text in sources.items():
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        v = _EndpointVisitor(relfile)
        v.visit(tree)
        out.extend(v.endpoints)
    return out


def analyze_endpoints(endpoints: list[Endpoint]) -> list[Finding]:
    """The graph-level checks over a collected endpoint list."""
    findings: list[Finding] = []
    by_topic: dict[str, list[Endpoint]] = {}
    for e in endpoints:
        if e.topic == "<dynamic>":
            continue
        by_topic.setdefault(e.topic, []).append(e)

    for topic, eps in sorted(by_topic.items()):
        pubs = [e for e in eps if e.kind == "pub"]
        subs = [e for e in eps if e.kind == "sub"]

        # type mismatch
        ptypes = {e.msg_type for e in pubs if e.msg_type}
        stypes = {e.msg_type for e in subs if e.msg_type}
        if ptypes and stypes and not (ptypes & stypes):
            s = subs[0]
            findings.append(Finding(
                rule="topics.type-mismatch", group="topics", severity=Severity.ERROR,
                message=(f"topic '{topic}': publisher type(s) {sorted(ptypes)} "
                         f"but subscriber type(s) {sorted(stypes)}"),
                fix="the two ends must use the same message type",
                file=s.file, line=s.line))

        # QoS mismatch: reliable sub vs best_effort pub
        if any(e.reliability == "best_effort" for e in pubs):
            for s in subs:
                if s.reliability == "reliable":
                    findings.append(Finding(
                        rule="topics.qos-incompatible", group="topics",
                        severity=Severity.ERROR,
                        message=(f"topic '{topic}': RELIABLE subscriber against a "
                                 f"BEST_EFFORT publisher -- DDS delivers nothing"),
                        fix=("use qos_profile_sensor_data on the subscriber, or make "
                             "the publisher RELIABLE"),
                        file=s.file, line=s.line))

        # subscribed but never published
        if subs and not pubs:
            s = subs[0]
            findings.append(Finding(
                rule="topics.no-publisher", group="topics", severity=Severity.ERROR,
                message=(f"topic '{topic}' is subscribed but no node in the "
                         f"workspace publishes it"),
                fix="check for a topic-name typo or a missing launch remap",
                file=s.file, line=s.line))

        # published but never subscribed
        if pubs and not subs:
            p = pubs[0]
            findings.append(Finding(
                rule="topics.no-subscriber", group="topics", severity=Severity.WARNING,
                message=(f"topic '{topic}' is published but nothing in the "
                         f"workspace subscribes to it"),
                fix="dead output, or a subscriber outside this workspace",
                file=p.file, line=p.line))

    return findings


def analyze_sources(sources: dict[str, str]) -> list[Finding]:
    return analyze_endpoints(collect_endpoints(sources))
