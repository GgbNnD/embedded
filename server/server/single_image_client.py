from __future__ import annotations

import json
from pathlib import Path

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String

from server.image_utils import bgr_to_image_msg, load_bgr_image


class SingleImageClient(Node):
    def __init__(self) -> None:
        super().__init__("single_image_client")

        self.declare_parameter("image_path", "")
        self.declare_parameter("frame_id", "camera")
        self.declare_parameter("timeout_sec", 10.0)

        image_path_value = str(self.get_parameter("image_path").value).strip()
        if not image_path_value:
            raise ValueError("Parameter 'image_path' is required")
        image_path = Path(image_path_value).expanduser()
        if not image_path.exists():
            raise FileNotFoundError(f"Image path not found: {image_path}")

        self.image_path = image_path.resolve()
        self.frame_id = self.get_parameter("frame_id").value
        self.timeout_sec = float(self.get_parameter("timeout_sec").value)
        self.exit_code = 0
        self.completed = False

        self.publisher = self.create_publisher(Image, "/material_counter/image", 10)
        self.subscription = self.create_subscription(String, "/material_counter/counts", self.result_callback, 10)
        self.publish_timer = self.create_timer(0.5, self.publish_once)
        self.timeout_timer = self.create_timer(self.timeout_sec, self.handle_timeout)
        self.timeout_timer.cancel()
        self.sent = False

        self.get_logger().info(f"Waiting to publish material image: {self.image_path}")

    def publish_once(self) -> None:
        if self.sent:
            return

        if self.publisher.get_subscription_count() == 0:
            return

        image = load_bgr_image(str(self.image_path))
        message = bgr_to_image_msg(image, frame_id=self.frame_id)
        message.header.stamp = self.get_clock().now().to_msg()
        self.publisher.publish(message)
        self.sent = True
        self.publish_timer.cancel()
        self.timeout_timer.reset()
        self.get_logger().info(f"Published image to material counter node: {self.image_path}")

    def result_callback(self, msg: String) -> None:
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warn(f"Received non-JSON result: {msg.data}")
            return

        self.get_logger().info(f"Received material count result: {payload}")
        self.timeout_timer.cancel()
        self.exit_code = 0
        self.completed = True

    def handle_timeout(self) -> None:
        self.get_logger().error("Timed out waiting for material count result")
        self.exit_code = 1
        self.completed = True


def main() -> None:
    rclpy.init()
    node = SingleImageClient()
    try:
        while rclpy.ok() and not node.completed:
            rclpy.spin_once(node, timeout_sec=0.1)
    except KeyboardInterrupt:
        node.exit_code = node.exit_code or 130
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

    if node.exit_code != 0:
        raise SystemExit(node.exit_code)


if __name__ == "__main__":
    main()
