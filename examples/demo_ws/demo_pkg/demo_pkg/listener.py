"""A deliberately buggy subscriber node, for the linter's demo.

Every bug in this file is intentional; see the repo README.
"""
import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64, Int32
from example_interfaces.srv import AddTwoInts


class Listener(Node):
    def __init__(self):
        super().__init__("listener")
        self.declare_parameter("frame", "base_link")

        # RELIABLE subscriber (default QoS) against a BEST_EFFORT publisher
        self.create_subscription(Float64, "/scan", self.on_scan, 10)
        # type mismatch: talker publishes /cmd as String
        self.create_subscription(Int32, "/cmd", self.on_cmd, 10)
        # nobody publishes this topic
        self.create_subscription(Float64, "/sensor_temp", self.on_temp, 10)

        # a client for a service no node advertises
        self.cli = self.create_client(AddTwoInts, "/do_thing")

    def on_scan(self, msg):
        pass

    def on_cmd(self, msg):
        pass

    def on_temp(self, msg):
        pass


def main():
    rclpy.init()
    rclpy.spin(Listener())


if __name__ == "__main__":
    main()
