"""Physical-unit mismatch detection (the flagship rule).

A unit mismatch is one of the cheapest bugs to write and one of the most
expensive to find: the code runs, the types check, and the arm moves to the
wrong place. This rule reads units from two lightweight sources that cost the
author almost nothing:

  * a trailing ``# unit: rad`` / ``# unit: deg`` / ``# unit: m`` comment, and
  * a name suffix -- ``_deg``, ``_rad``, ``_m``, ``_mm``, ``_cm``,
    ``_mps`` (m/s), ``_dps`` (deg/s), ``_ms`` (milliseconds).

plus the known units of common ROS message fields (sensor_msgs/JointState
positions are radians, geometry_msgs/Twist linear is m/s, and so on), which
the user can extend through a units registry.

It flags three shapes:

  1. assigning a value of one unit into a name/field of a mismatched unit with
     no conversion on the way (``q_rad = angle_deg`` -- the classic);
  2. an arithmetic expression mixing incompatible units
     (``x_mm + reach_m`` -- one operand is a thousand times the other);
  3. publishing into a known-united message field from a differently-united
     source (``js.position = [a_deg ...]`` where position is radians).

It is deliberately conservative: a value that passes through a recognised
conversion (``math.radians``, ``deg2rad``, ``* DEG2RAD``, ``/ 1000.0`` for
mm->m, an explicit ``# unit:`` re-annotation) clears the finding. False
positives are worse than silence for a linter people are meant to keep on.
"""
from __future__ import annotations

import ast
import re

from .model import Finding, Severity

# Canonical dimension for each unit, so we compare dimensions not spellings.
# Angular and linear and time are different dimensions; deg vs rad is the same
# dimension but a mismatch we still care about because the scale differs 57x.
_UNIT_DIM = {
    "rad": "angle", "deg": "angle",
    "m": "length", "mm": "length", "cm": "length", "km": "length",
    "mps": "linvel", "kmph": "linvel",
    "dps": "angvel", "radps": "angvel",
    "s": "time", "ms": "time", "ns": "time",
    "kg": "mass", "g": "mass",
    "n": "force",
    "c": "temp", "k": "temp",
    "pct": "ratio",
}

# Scale to the SI base of each dimension (for the "same dimension, wrong scale"
# report). Only used to describe the size of the error, not to auto-fix.
_TO_BASE = {
    "rad": 1.0, "deg": 0.0174532925,
    "m": 1.0, "mm": 0.001, "cm": 0.01, "km": 1000.0,
    "s": 1.0, "ms": 0.001, "ns": 1e-9,
    "mps": 1.0, "dps": 0.0174532925, "radps": 1.0,
    "kg": 1.0, "g": 0.001,
}

_SUFFIX_UNIT = {
    "deg": "deg", "rad": "rad",
    "mm": "mm", "cm": "cm", "km": "km", "m": "m",
    "mps": "mps", "dps": "dps", "radps": "radps",
    "ms": "ms", "ns": "ns", "s": "s",
    "kg": "kg", "g": "g",
    "pct": "pct",
}

# Conversions that legitimately change a unit; a value passing through one of
# these is not a mismatch.
_CONVERSION_CALLS = {
    "radians", "degrees", "deg2rad", "rad2deg", "deg_to_rad", "rad_to_deg",
    "to_rad", "to_deg", "np.radians", "np.degrees", "math.radians",
    "math.degrees", "deg", "rad",
}
_CONVERSION_TOKENS = re.compile(
    r"(DEG2RAD|RAD2DEG|DEG_TO_RAD|RAD_TO_DEG|MM_TO_M|M_TO_MM|/\s*1000|\*\s*1000|"
    r"pi\s*/\s*180|180\s*/\s*pi)")

# Common ROS message fields with a fixed unit. Keyed by "Msg.field" and by the
# fully-qualified "pkg/Msg.field". The user's registry is merged over this.
_ROS_FIELD_UNITS = {
    "JointState.position": "rad",
    "sensor_msgs/JointState.position": "rad",
    "JointState.velocity": "radps",
    "sensor_msgs/JointState.velocity": "radps",
    "Twist.linear": "mps",
    "geometry_msgs/Twist.linear": "mps",
    "Twist.angular": "radps",
    "geometry_msgs/Twist.angular": "radps",
    "Imu.angular_velocity": "radps",
    "sensor_msgs/Imu.angular_velocity": "radps",
    "Temperature.temperature": "c",
    "sensor_msgs/Temperature.temperature": "c",
}

_TRAILING_UNIT = re.compile(r"#\s*unit\s*:\s*([A-Za-z/%]+)", re.IGNORECASE)


def _norm_unit(u: str) -> str | None:
    u = u.strip().lower()
    u = {"m/s": "mps", "km/h": "kmph", "deg/s": "dps", "rad/s": "radps",
         "%": "pct", "millimeters": "mm", "millimetres": "mm",
         "meters": "m", "metres": "m", "degrees": "deg", "radians": "rad"}.get(u, u)
    return u if u in _UNIT_DIM else None


def _unit_from_name(name: str) -> str | None:
    parts = re.split(r"[_\W]+", name)
    if not parts:
        return None
    tail = parts[-1].lower()
    return _SUFFIX_UNIT.get(tail)


def _line_comment_units(source: str) -> dict[int, str]:
    """1-indexed line -> unit declared by a trailing ``# unit:`` comment."""
    out: dict[int, str] = {}
    for i, line in enumerate(source.splitlines(), start=1):
        m = _TRAILING_UNIT.search(line)
        if m:
            u = _norm_unit(m.group(1))
            if u:
                out[i] = u
    return out


def _describe_scale(src_u: str, dst_u: str) -> str:
    a, b = _TO_BASE.get(src_u), _TO_BASE.get(dst_u)
    if a and b and a != 0 and b != 0:
        ratio = a / b
        big = max(ratio, 1.0 / ratio)      # always report the >1 side
        if big >= 1.5:
            return f" (a factor of about {big:.0f} off)"
    return ""


class _Visitor(ast.NodeVisitor):
    def __init__(self, source: str, registry: dict[str, str]):
        self.findings: list[Finding] = []
        self.comment_units = _line_comment_units(source)
        self.registry = dict(_ROS_FIELD_UNITS)
        self.registry.update(registry or {})

    # ---- helpers -----------------------------------------------------------
    def _expr_has_conversion(self, node: ast.AST) -> bool:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                fn = _dotted(sub.func)
                if fn and fn.split(".")[-1] in {c.split(".")[-1]
                                                for c in _CONVERSION_CALLS}:
                    return True
        try:
            seg = ast.get_source_segment(self._source, node) or ""
        except Exception:
            seg = ""
        return bool(_CONVERSION_TOKENS.search(seg))

    def _unit_of_expr(self, node: ast.AST) -> str | None:
        """Best-effort unit of an rvalue: a bare Name/Attribute with a united
        suffix, or a message-field attribute in the registry."""
        if isinstance(node, ast.Name):
            return _unit_from_name(node.id)
        if isinstance(node, ast.Attribute):
            u = _unit_from_name(node.attr)
            if u:
                return u
            key = self._field_key(node)
            if key:
                for k in key:
                    if k in self.registry:
                        return self.registry[k]
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
            # unit of the first element (lists of joint angles etc.)
            return self._unit_of_expr(node.elts[0])
        if isinstance(node, ast.Subscript):
            return self._unit_of_expr(node.value)
        return None

    def _field_key(self, node: ast.Attribute) -> list[str]:
        """Return candidate registry keys for msg.field like ['JointState.position']
        -- we only know the attribute chain, so use the last two names."""
        attr = node.attr
        base = node.value
        # try to recover a type hint from a name like js/joint_state -> JointState
        names = []
        if isinstance(base, ast.Name):
            names.append(base.id)
        return [f"{n}.{attr}" for n in _msgish(names)] + [f"*.{attr}"]

    # ---- visits ------------------------------------------------------------
    def visit_Assign(self, node: ast.Assign):
        self._check_assign_targets(node.targets, node.value, node.lineno)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        if node.value is not None:
            self._check_assign_targets([node.target], node.value, node.lineno)
        self.generic_visit(node)

    def _check_assign_targets(self, targets, value, lineno):
        # a re-annotation on the assignment line overrides suffix inference
        forced = self.comment_units.get(lineno)
        src_u = forced or self._unit_of_expr(value)
        if src_u is None:
            return
        for tgt in targets:
            dst_u = self._target_unit(tgt)
            if dst_u is None or dst_u == src_u:
                continue
            if _UNIT_DIM.get(src_u) != _UNIT_DIM.get(dst_u):
                # cross-dimension: only report if both are clearly united, it is
                # usually a genuine bug (time into length etc.) -- but skip if a
                # conversion is present.
                if self._expr_has_conversion(value):
                    continue
                self._add(lineno, "units.dimension-mismatch", Severity.ERROR,
                          f"assigning a {src_u} value ({_UNIT_DIM.get(src_u)}) into "
                          f"'{_tname(tgt)}' which is {dst_u} ({_UNIT_DIM.get(dst_u)})",
                          "these are different physical dimensions; check the source")
                continue
            # same dimension, wrong unit (deg into rad, mm into m)
            if self._expr_has_conversion(value):
                continue
            self._add(lineno, f"units.{src_u}-into-{dst_u}", Severity.ERROR,
                      f"assigning a {src_u} value into '{_tname(tgt)}' which is "
                      f"{dst_u}{_describe_scale(src_u, dst_u)} with no conversion",
                      f"convert on assignment, e.g. math.radians(...) or an explicit factor")

    def _target_unit(self, tgt) -> str | None:
        if isinstance(tgt, ast.Name):
            return _unit_from_name(tgt.id)
        if isinstance(tgt, ast.Attribute):
            u = _unit_from_name(tgt.attr)
            if u:
                return u
            key = self._field_key(tgt)
            for k in key:
                if k in self.registry:
                    return self.registry[k]
        if isinstance(tgt, ast.Subscript):
            return self._target_unit(tgt.value)
        return None

    def visit_BinOp(self, node: ast.BinOp):
        if isinstance(node.op, (ast.Add, ast.Sub)):
            lu = self._unit_of_expr(node.left)
            ru = self._unit_of_expr(node.right)
            if lu and ru and lu != ru and _UNIT_DIM.get(lu) == _UNIT_DIM.get(ru):
                self._add(node.lineno, "units.mixed-scale-arithmetic",
                          Severity.ERROR,
                          f"adding/subtracting {lu} and {ru}"
                          f"{_describe_scale(ru, lu)} in one expression",
                          "bring both operands to the same unit first")
            elif lu and ru and _UNIT_DIM.get(lu) != _UNIT_DIM.get(ru):
                self._add(node.lineno, "units.mixed-dimension-arithmetic",
                          Severity.WARNING,
                          f"adding/subtracting {lu} ({_UNIT_DIM.get(lu)}) and "
                          f"{ru} ({_UNIT_DIM.get(ru)})",
                          "these are different dimensions; verify the intent")
        self.generic_visit(node)

    def _add(self, line, rule, sev, msg, fix):
        self.findings.append(Finding(rule=rule, group="units", severity=sev,
                                     message=msg, fix=fix, line=line))


def _dotted(node) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _tname(node) -> str:
    return _dotted(node) or "<target>"


def _msgish(names: list[str]) -> list[str]:
    """Guess a message type name from a variable name: js -> JointState is too
    much; instead just also try the CamelCase of the variable, which covers
    ``twist.linear`` -> ``Twist.linear``."""
    out = list(names)
    for n in names:
        cap = "".join(p.capitalize() for p in n.split("_"))
        if cap and cap not in out:
            out.append(cap)
    return out


def check_source(source: str, registry: dict[str, str] | None = None) -> list[Finding]:
    """Findings for one Python source string. Used directly by tests."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [Finding(rule="units.parse-error", group="units",
                        severity=Severity.INFO,
                        message=f"could not parse: {e.msg}", line=e.lineno or 0)]
    v = _Visitor(source, registry or {})
    v._source = source
    v.visit(tree)
    return v.findings


def check_file(path: str, registry: dict[str, str] | None = None) -> list[Finding]:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return check_source(fh.read(), registry)
