from ros2_interaction_lint import config as cfg
from ros2_interaction_lint import interfaces


def crules(sources, yamls, bounds=None):
    return {f.rule for f in cfg.analyze(sources, yamls, bounds)}


DECL = (
    "class N:\n"
    "    def __init__(self):\n"
    "        self.declare_parameter('rate_hz', 20.0)   # bounds: 1.0, 100.0\n"
    "        self.declare_parameter('kp', 0.5)\n"
)


def test_declared_never_set():
    y = {"p.yaml": "n:\n  ros__parameters:\n    rate_hz: 20.0\n"}
    assert "config.declared-never-set" in crules({"a.py": DECL}, y)


def test_set_never_declared():
    y = {"p.yaml": "n:\n  ros__parameters:\n    rate_hz: 20.0\n    mystery: 3\n"}
    assert "config.set-never-declared" in crules({"a.py": DECL}, y)


def test_out_of_bounds():
    y = {"p.yaml": "n:\n  ros__parameters:\n    rate_hz: 500.0\n"}
    assert "config.out-of-bounds" in crules({"a.py": DECL}, y)


def test_in_bounds_is_silent_for_that_rule():
    y = {"p.yaml": "n:\n  ros__parameters:\n    rate_hz: 50.0\n    kp: 0.5\n"}
    assert "config.out-of-bounds" not in crules({"a.py": DECL}, y)


def test_divergent_duplicate():
    y = {"p.yaml": ("na:\n  ros__parameters:\n    frame: base\n"
                    "nb:\n  ros__parameters:\n    frame: odom\n")}
    src = {"a.py": "class N:\n    def __init__(self):\n        self.declare_parameter('frame', 'x')\n"}
    assert "config.divergent-duplicate" in crules(src, y)


def test_extra_bounds_from_config():
    y = {"p.yaml": "n:\n  ros__parameters:\n    speed: 9.0\n"}
    src = {"a.py": "class N:\n    def __init__(self):\n        self.declare_parameter('speed', 1.0)\n"}
    assert "config.out-of-bounds" in crules(src, y, bounds={"speed": (0.0, 5.0)})


# ---- interfaces --------------------------------------------------------
def irules(sources):
    return {f.rule for f in interfaces.analyze(sources)}


def test_client_without_server():
    src = {"a.py": "class N:\n    def __init__(self):\n        self.cli = self.create_client(Srv, '/do_thing')\n"}
    assert "interfaces.no-service-server" in irules(src)


def test_client_with_server_is_silent():
    src = {
        "a.py": "class N:\n    def __init__(self):\n        self.create_client(Srv, '/do_thing')\n",
        "b.py": "class M:\n    def __init__(self):\n        self.create_service(Srv, '/do_thing', self.cb)\n",
    }
    assert "interfaces.no-service-server" not in irules(src)


def test_action_client_without_server():
    src = {"a.py": "class N:\n    def __init__(self):\n        ActionClient(self, Fib, '/fib')\n"}
    assert "interfaces.no-action-server" in irules(src)
