from ros2_interaction_lint import topics


def rules(sources):
    return {f.rule for f in topics.analyze_sources(sources)}


PUB_BE = (
    "from rclpy.qos import qos_profile_sensor_data\n"
    "class N:\n"
    "    def __init__(self):\n"
    "        self.create_publisher(Float64, '/scan', qos_profile_sensor_data)\n"
)
SUB_RELIABLE = (
    "class M:\n"
    "    def __init__(self):\n"
    "        self.create_subscription(Float64, '/scan', self.cb, 10)\n"
)


def test_qos_incompatible_reliable_sub_best_effort_pub():
    assert "topics.qos-incompatible" in rules({"a.py": PUB_BE, "b.py": SUB_RELIABLE})


def test_matched_qos_is_silent():
    both_be = (
        "from rclpy.qos import qos_profile_sensor_data\n"
        "class M:\n"
        "    def __init__(self):\n"
        "        self.create_subscription(F, '/scan', self.cb, qos_profile_sensor_data)\n"
    )
    assert "topics.qos-incompatible" not in rules({"a.py": PUB_BE, "b.py": both_be})


def test_type_mismatch():
    src = {
        "a.py": "class N:\n    def __init__(self):\n        self.create_publisher(String, '/cmd', 10)\n",
        "b.py": "class M:\n    def __init__(self):\n        self.create_subscription(Int32, '/cmd', self.cb, 10)\n",
    }
    assert "topics.type-mismatch" in rules(src)


def test_no_publisher():
    src = {"b.py": "class M:\n    def __init__(self):\n        self.create_subscription(F, '/ghost', self.cb, 10)\n"}
    assert "topics.no-publisher" in rules(src)


def test_no_subscriber_is_warning():
    src = {"a.py": "class N:\n    def __init__(self):\n        self.create_publisher(F, '/lonely', 10)\n"}
    r = rules(src)
    assert "topics.no-subscriber" in r
    assert "topics.no-publisher" not in r


def test_matched_pub_sub_same_type_is_silent():
    src = {
        "a.py": "class N:\n    def __init__(self):\n        self.create_publisher(F, '/t', 10)\n",
        "b.py": "class M:\n    def __init__(self):\n        self.create_subscription(F, '/t', self.cb, 10)\n",
    }
    assert rules(src) == set()
