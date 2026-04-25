# client

`client` is a ROS 2 package that provides a unified operator workflow for:

- face recognition before the operation
- material counting before and after the operation
- diff calculation
- inventory submission to the existing `server` TCP bridge

## Nodes

- `camera_node`
- `tcp_client_node`
- `logic_node`
- `ui_node`

## Build

```bash
conda activate alg
source /opt/ros/humble/setup.bash
colcon build --packages-select client
source install/setup.bash
```

## Run

```bash
ros2 launch client client.launch.py
```
