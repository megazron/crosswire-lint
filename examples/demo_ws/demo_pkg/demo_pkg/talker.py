"""A deliberately buggy publisher node, for the linter's demo.

Every bug in this file is intentional; see the repo README.
"""
import math

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64, String


class Talker(Node):
    def __init__(self):
        super().__init__("talker")
        self.declare_parameter("rate_hz", 20.0)   # bounds: 1.0, 100.0
        self.declare_parameter("kp", 0.5)          # never set in any config

        # best-effort publisher: a RELIABLE subscriber will get nothing
        self.scan_pub = self.create_publisher(Float64, "/scan", qos_profile_sensor_data)
        # type mismatch: listener subscribes /cmd as Int32
        self.cmd_pub = self.create_publisher(String, "/cmd", 10)
        # nobody subscribes to this one (warning)
        self.debug_pub = self.create_publisher(Float64, "/debug", 10)

        self.js_pub = self.create_publisher(JointState, "/joint_states", 10)

    def tick(self):
        angle_deg = 90.0                 # unit: deg
        q_rad = angle_deg                # UNIT BUG: deg assigned into a rad name
        js = JointState()
        js.position = [q_rad]            # JointState.position is radians
        self.js_pub.publish(js)

        x_mm = 250.0
        reach_m = 0.4
        total_m = x_mm + reach_m         # UNIT BUG: mm + m in one expression
        return total_m, q_rad


def main():
    rclpy.init()
    node = Talker()
    rclpy.spin(node)


if __name__ == "__main__":
    main()
