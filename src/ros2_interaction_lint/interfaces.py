"""Inter-component service/action contracts across the workspace.

Flags a client that has no server:

  * a ``create_client(Srv, "/name")`` whose service ``/name`` no node in the
    workspace ``create_service``s;
  * an ``ActionClient(..., "/name")`` with no matching ``ActionServer``.

Same shape as the no-publisher topic bug, and just as silent: the client
waits forever on a service nobody offers.
"""
from __future__ import annotations

import ast

from .model import Finding, Severity


def _str_arg(node: ast.Call, index: int) -> str | None:
    if len(node.args) > index:
        a = node.args[index]
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            return a.value
    return None


def _scan(sources: dict[str, str]):
    clients: dict[str, list[tuple[str, int]]] = {}       # service name -> [(file,line)]
    servers: set[str] = set()
    action_clients: dict[str, list[tuple[str, int]]] = {}
    action_servers: set[str] = set()
    for relfile, text in sources.items():
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
            if fname == "create_client":
                name = _str_arg(node, 1)
                if name:
                    clients.setdefault(name, []).append((relfile, node.lineno))
            elif fname == "create_service":
                name = _str_arg(node, 1)
                if name:
                    servers.add(name)
            elif fname == "ActionClient":
                name = _str_arg(node, 2)
                if name:
                    action_clients.setdefault(name, []).append((relfile, node.lineno))
            elif fname == "ActionServer":
                name = _str_arg(node, 2)
                if name:
                    action_servers.add(name)
    return clients, servers, action_clients, action_servers


def analyze(sources: dict[str, str]) -> list[Finding]:
    findings: list[Finding] = []
    clients, servers, aclients, aservers = _scan(sources)
    for name, locs in sorted(clients.items()):
        if name not in servers:
            f0, l0 = locs[0]
            findings.append(Finding(
                rule="interfaces.no-service-server", group="interfaces",
                severity=Severity.ERROR,
                message=(f"service '{name}' has a client but no node in the "
                         f"workspace advertises it"),
                fix="check the service name, or the server node is missing",
                file=f0, line=l0))
    for name, locs in sorted(aclients.items()):
        if name not in aservers:
            f0, l0 = locs[0]
            findings.append(Finding(
                rule="interfaces.no-action-server", group="interfaces",
                severity=Severity.ERROR,
                message=(f"action '{name}' has a client but no node in the "
                         f"workspace advertises it"),
                fix="check the action name, or the server node is missing",
                file=f0, line=l0))
    return findings
