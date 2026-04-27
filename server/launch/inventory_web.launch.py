from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            DeclareLaunchArgument("host", default_value="127.0.0.1"),
            DeclareLaunchArgument("port", default_value="8600"),
            DeclareLaunchArgument("inventory_csv_path", default_value="auto"),
            DeclareLaunchArgument("refresh_interval_sec", default_value="1.0"),
            Node(
                package="server",
                executable="inventory_web_node",
                name="inventory_web_server",
                output="screen",
                parameters=[
                    {
                        "host": LaunchConfiguration("host"),
                        "port": LaunchConfiguration("port"),
                        "inventory_csv_path": LaunchConfiguration("inventory_csv_path"),
                        "refresh_interval_sec": LaunchConfiguration("refresh_interval_sec"),
                    }
                ],
            ),
        ]
    )
