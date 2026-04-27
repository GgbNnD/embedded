from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            DeclareLaunchArgument("host", default_value="0.0.0.0"),
            DeclareLaunchArgument("port", default_value="9000"),
            DeclareLaunchArgument("inventory_csv_path", default_value="auto"),
            DeclareLaunchArgument("web_enabled", default_value="true"),
            DeclareLaunchArgument("web_host", default_value="127.0.0.1"),
            DeclareLaunchArgument("web_port", default_value="8600"),
            DeclareLaunchArgument("web_refresh_interval_sec", default_value="1.0"),
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
                parameters=[
                    {
                        "host": LaunchConfiguration("host"),
                        "port": LaunchConfiguration("port"),
                        "inventory_csv_path": LaunchConfiguration("inventory_csv_path"),
                    }
                ],
            ),
            Node(
                condition=IfCondition(LaunchConfiguration("web_enabled")),
                package="server",
                executable="inventory_web_node",
                name="inventory_web_server",
                output="screen",
                parameters=[
                    {
                        "host": LaunchConfiguration("web_host"),
                        "port": LaunchConfiguration("web_port"),
                        "inventory_csv_path": LaunchConfiguration("inventory_csv_path"),
                        "refresh_interval_sec": LaunchConfiguration("web_refresh_interval_sec"),
                    }
                ],
            ),
        ]
    )
