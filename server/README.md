# server

`server` is a ROS 2 package that wraps the trained YOLO material-counting model as ROS 2 nodes.

## Nodes

- `material_counter_node`
  - subscribes to `sensor_msgs/msg/Image`
  - runs YOLO inference
  - publishes counts as a JSON string on a `std_msgs/msg/String` topic
  - can optionally publish an annotated image

- `single_image_client`
  - loads one image from disk
  - only targets the material counting node
  - publishes to `/material_counter/image`
  - listens on `/material_counter/counts`

- `face_recognize_node`
  - subscribes to `sensor_msgs/msg/Image`
  - preloads known face encodings from `server/assets/known_face/` at startup
  - publishes face recognition results as a JSON string on a `std_msgs/msg/String` topic
  - can optionally publish an annotated image

- `face_recognize_client`
  - only targets the face recognition node
  - publishes to `/face_recognize/image`
  - listens on `/face_recognize/result`

## Default topics

- input image: `/material_counter/image`
- output counts: `/material_counter/counts`
- annotated image: `/material_counter/annotated_image`
- face input image: `/face_recognize/image`
- face result: `/face_recognize/result`
- face annotated image: `/face_recognize/annotated_image`

## Build

```bash
conda activate alg
source /opt/ros/humble/setup.bash
colcon build --packages-select server
source install/setup.bash
export ROS_LOCALHOST_ONLY=1
```

## Run

Start the server:

```bash
ros2 run server material_counter_node
```

Start the face recognition node:

```bash
ros2 run server face_recognize_node
```

Send one image and print the result:

```bash
ros2 run server single_image_client --ros-args -p image_path:=/absolute/path/to/image.jpg
```

Send one image to the face recognition node:

```bash
ros2 run server face_recognize_client --ros-args \
  -p image_path:=/absolute/path/to/image.jpg
```

Example output topic payload:

```json
{
  "frame_id": "camera",
  "stamp_sec": 1777119153,
  "stamp_nanosec": 0,
  "counts": {
    "cboard": 2,
    "m3508": 1
  },
  "total_detections": 3
}
```

Example face recognition payload:

```json
{
  "frame_id": "camera",
  "stamp_sec": 1777123000,
  "stamp_nanosec": 0,
  "results": [
    {
      "name": "huanghexiang",
      "distance": 0.37,
      "box": {
        "top": 120,
        "right": 280,
        "bottom": 280,
        "left": 110
      }
    }
  ],
  "counts": {
    "huanghexiang": 1
  },
  "total_faces": 1
}
```
