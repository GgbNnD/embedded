from __future__ import annotations

import json
from pathlib import Path

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String
from ultralytics import YOLO

from server.image_utils import bgr_to_image_msg, image_msg_to_bgr, resolve_default_model_path


def summarize_counts(result) -> dict[str, int]:
    names = result.names
    class_ids = result.boxes.cls.tolist() if result.boxes is not None else []
    counts: dict[str, int] = {}
    for class_id in class_ids:
        class_name = names[int(class_id)]
        counts[class_name] = counts.get(class_name, 0) + 1
    return dict(sorted(counts.items()))


class MaterialCounterNode(Node):
    def __init__(self) -> None:
        super().__init__("material_counter_node")

        default_model_path = str(resolve_default_model_path())
        self.declare_parameter("model_path", default_model_path)
        self.declare_parameter("device", "")
        self.declare_parameter("conf_threshold", 0.25)
        self.declare_parameter("image_topic", "/material_counter/image")
        self.declare_parameter("counts_topic", "/material_counter/counts")
        self.declare_parameter("annotated_image_topic", "/material_counter/annotated_image")
        self.declare_parameter("publish_annotated_image", False)

        model_path = Path(self.get_parameter("model_path").value).expanduser().resolve()
        if not model_path.exists():
            raise FileNotFoundError(f"Model weights not found: {model_path}")

        self.device = self.get_parameter("device").value or None
        self.conf_threshold = float(self.get_parameter("conf_threshold").value)
        self.publish_annotated_image = bool(self.get_parameter("publish_annotated_image").value)

        self.model = YOLO(str(model_path))
        image_topic = self.get_parameter("image_topic").value
        counts_topic = self.get_parameter("counts_topic").value
        annotated_topic = self.get_parameter("annotated_image_topic").value

        self.counts_publisher = self.create_publisher(String, counts_topic, 10)
        self.image_subscription = self.create_subscription(Image, image_topic, self.image_callback, 10)
        self.annotated_publisher = None
        if self.publish_annotated_image:
            self.annotated_publisher = self.create_publisher(Image, annotated_topic, 10)

        self.get_logger().info(f"Loaded model from: {model_path}")
        self.get_logger().info(f"Listening on image topic: {image_topic}")
        self.get_logger().info(f"Publishing counts on topic: {counts_topic}")
        if self.annotated_publisher is not None:
            self.get_logger().info(f"Publishing annotated images on topic: {annotated_topic}")

    def image_callback(self, msg: Image) -> None:
        try:
            image = image_msg_to_bgr(msg)
            predictions = self.model.predict(
                source=image,
                conf=self.conf_threshold,
                device=self.device,
                verbose=False,
            )
            result = predictions[0]
            counts = summarize_counts(result)

            payload = {
                "frame_id": msg.header.frame_id,
                "stamp_sec": int(msg.header.stamp.sec),
                "stamp_nanosec": int(msg.header.stamp.nanosec),
                "counts": counts,
                "total_detections": int(sum(counts.values())),
            }
            self.counts_publisher.publish(String(data=json.dumps(payload, ensure_ascii=False)))
            self.get_logger().info(f"Inference result: {payload['counts']}")

            if self.annotated_publisher is not None:
                annotated = result.plot()
                annotated_msg = bgr_to_image_msg(annotated, frame_id=msg.header.frame_id)
                annotated_msg.header.stamp = msg.header.stamp
                self.annotated_publisher.publish(annotated_msg)
        except Exception as exc:
            self.get_logger().error(f"Inference failed: {exc}")


def main() -> None:
    rclpy.init()
    node = MaterialCounterNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
