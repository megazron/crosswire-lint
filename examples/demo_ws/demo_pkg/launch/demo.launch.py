from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    params = "config/params.yaml"
    return LaunchDescription([
        Node(package="demo_pkg", executable="talker", name="talker",
             parameters=[params]),
        Node(package="demo_pkg", executable="listener", name="listener",
             parameters=[params]),
    ])
