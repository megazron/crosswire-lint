"""ros2-interaction-lint: catch the cheap-to-detect ROS 2 bug classes.

A static (plus optional live) linter for physical-unit mismatches, cross-node
interaction bugs, parameter misconfiguration, dependency-declaration gaps and
service/action contract holes. It is a linter, not a proof: it finds common
mistakes cheaply, and does not certify a system correct.
"""
from .engine import analyze, load_sources
from .model import Finding, LintConfig, Severity, RULE_GROUPS

__version__ = "0.1.0"
__all__ = ["analyze", "load_sources", "Finding", "LintConfig", "Severity",
           "RULE_GROUPS", "__version__"]
