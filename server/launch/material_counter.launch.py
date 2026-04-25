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
            )
        ]
    )
