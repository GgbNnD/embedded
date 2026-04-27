from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            DeclareLaunchArgument("camera_index", default_value="0"),
            DeclareLaunchArgument("camera_backend", default_value="auto"),
            DeclareLaunchArgument("width", default_value="1280"),
            DeclareLaunchArgument("height", default_value="720"),
            DeclareLaunchArgument("fps", default_value="15"),
            DeclareLaunchArgument("rpicam_executable", default_value="rpicam-still"),
            DeclareLaunchArgument("rpicam_timeout_ms", default_value="1"),
            DeclareLaunchArgument("server_host", default_value="127.0.0.1"),
            DeclareLaunchArgument("server_port", default_value="9000"),
            DeclareLaunchArgument("connect_timeout_sec", default_value="3.0"),
            DeclareLaunchArgument("request_timeout_sec", default_value="15.0"),
            DeclareLaunchArgument("jpeg_quality", default_value="90"),
            DeclareLaunchArgument("face_retry_interval_sec", default_value="1.0"),
            DeclareLaunchArgument("face_timeout_sec", default_value="60.0"),
            DeclareLaunchArgument("settle_delay_sec", default_value="3.5"),
            DeclareLaunchArgument("stable_hold_sec", default_value="1.0"),
            DeclareLaunchArgument("stability_threshold", default_value="3.0"),
            DeclareLaunchArgument("stable_timeout_sec", default_value="8.0"),
            Node(
                package="client",
                executable="camera_node",
                name="client_camera",
                output="screen",
                parameters=[
                    {
                        "camera_index": LaunchConfiguration("camera_index"),
                        "camera_backend": LaunchConfiguration("camera_backend"),
                        "width": LaunchConfiguration("width"),
                        "height": LaunchConfiguration("height"),
                        "fps": LaunchConfiguration("fps"),
                        "rpicam_executable": LaunchConfiguration("rpicam_executable"),
                        "rpicam_timeout_ms": LaunchConfiguration("rpicam_timeout_ms"),
                    }
                ],
            ),
            Node(
                package="client",
                executable="tcp_client_node",
                name="client_tcp",
                output="screen",
                parameters=[
                    {
                        "server_host": LaunchConfiguration("server_host"),
                        "server_port": LaunchConfiguration("server_port"),
                        "connect_timeout_sec": LaunchConfiguration("connect_timeout_sec"),
                        "request_timeout_sec": LaunchConfiguration("request_timeout_sec"),
                        "jpeg_quality": LaunchConfiguration("jpeg_quality"),
                    }
                ],
            ),
            Node(
                package="client",
                executable="logic_node",
                name="client_logic",
                output="screen",
                parameters=[
                    {
                        "face_retry_interval_sec": LaunchConfiguration("face_retry_interval_sec"),
                        "face_timeout_sec": LaunchConfiguration("face_timeout_sec"),
                        "settle_delay_sec": LaunchConfiguration("settle_delay_sec"),
                        "stable_hold_sec": LaunchConfiguration("stable_hold_sec"),
                        "stability_threshold": LaunchConfiguration("stability_threshold"),
                        "stable_timeout_sec": LaunchConfiguration("stable_timeout_sec"),
                    }
                ],
            ),
            Node(
                package="client",
                executable="ui_node",
                name="client_ui",
                output="screen",
            ),
        ]
    )
