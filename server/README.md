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
  - publishes it to the server input topic
  - listens for the JSON result and prints it

## Default topics

- input image: `/material_counter/image`
- output counts: `/material_counter/counts`
- annotated image: `/material_counter/annotated_image`

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

Send one image and print the result:

```bash
ros2 run server single_image_client --ros-args -p image_path:=/absolute/path/to/image.jpg
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
