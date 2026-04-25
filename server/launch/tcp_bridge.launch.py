from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            Node(
                package="server",
                executable="material_counter_node",
                name="material_counter_server",
                output="screen",
                parameters=[
                    {
                        "device": "0",
                        "publish_annotated_image": False,
                    }
                ],
            ),
            Node(
                package="server",
                executable="face_recognize_node",
                name="face_recognize_server",
                output="screen",
                parameters=[
                    {
                        "publish_annotated_image": False,
                    }
                ],
            ),
            Node(
                package="server",
                executable="tcp_bridge_node",
                name="tcp_bridge_server",
                output="screen",
            ),
        ]
    )
