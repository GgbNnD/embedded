from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String

from server.face_database import annotate_faces, load_known_face_database, recognize_faces
from server.image_utils import bgr_to_image_msg, image_msg_to_bgr, resolve_default_known_face_dir


class FaceRecognizeNode(Node):
    def __init__(self) -> None:
        super().__init__("face_recognize_node")

        default_known_face_dir = str(resolve_default_known_face_dir())
        self.declare_parameter("known_face_dir", default_known_face_dir)
        self.declare_parameter("tolerance", 0.45)
        self.declare_parameter("detection_model", "hog")
        self.declare_parameter("unknown_label", "unknown")
        self.declare_parameter("image_topic", "/face_recognize/image")
        self.declare_parameter("result_topic", "/face_recognize/result")
        self.declare_parameter("annotated_image_topic", "/face_recognize/annotated_image")
        self.declare_parameter("publish_annotated_image", False)

        self.known_face_dir = Path(self.get_parameter("known_face_dir").value).expanduser().resolve()
        self.tolerance = float(self.get_parameter("tolerance").value)
        self.detection_model = str(self.get_parameter("detection_model").value)
        self.unknown_label = str(self.get_parameter("unknown_label").value)
        self.publish_annotated_image = bool(self.get_parameter("publish_annotated_image").value)

        self.known_encodings, self.known_names = load_known_face_database(self.known_face_dir, self.get_logger())
        self.get_logger().info(
            f"Loaded {len(self.known_encodings)} known face encodings from: {self.known_face_dir}"
        )

        image_topic = self.get_parameter("image_topic").value
        result_topic = self.get_parameter("result_topic").value
        annotated_topic = self.get_parameter("annotated_image_topic").value

        self.result_publisher = self.create_publisher(String, result_topic, 10)
        self.image_subscription = self.create_subscription(Image, image_topic, self.image_callback, 10)
        self.annotated_publisher = None
        if self.publish_annotated_image:
            self.annotated_publisher = self.create_publisher(Image, annotated_topic, 10)

        self.get_logger().info(f"Listening on image topic: {image_topic}")
        self.get_logger().info(f"Publishing recognition result on topic: {result_topic}")
        if self.annotated_publisher is not None:
            self.get_logger().info(f"Publishing annotated images on topic: {annotated_topic}")

    def image_callback(self, msg: Image) -> None:
        try:
            image = image_msg_to_bgr(msg)
            results = recognize_faces(
                image,
                self.known_encodings,
                self.known_names,
                tolerance=self.tolerance,
                detection_model=self.detection_model,
                unknown_label=self.unknown_label,
            )
            counts = dict(sorted(Counter(str(item["name"]) for item in results).items()))
            payload = {
                "frame_id": msg.header.frame_id,
                "stamp_sec": int(msg.header.stamp.sec),
                "stamp_nanosec": int(msg.header.stamp.nanosec),
                "results": results,
                "counts": counts,
                "total_faces": len(results),
            }
            self.result_publisher.publish(String(data=json.dumps(payload, ensure_ascii=False)))
            self.get_logger().info(f"Face recognition result: {payload['counts']}")

            if self.annotated_publisher is not None:
                annotated = annotate_faces(image, results)
                annotated_msg = bgr_to_image_msg(annotated, frame_id=msg.header.frame_id)
                annotated_msg.header.stamp = msg.header.stamp
                self.annotated_publisher.publish(annotated_msg)
        except Exception as exc:
            self.get_logger().error(f"Face recognition failed: {exc}")


def main() -> None:
    rclpy.init()
    node = FaceRecognizeNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
