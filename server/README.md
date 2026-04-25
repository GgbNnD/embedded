# server

`server` is a ROS 2 package that provides:

- YOLO-based material counting
- face recognition against a local face database
- a TCP bridge node for remote clients

## Nodes

- `material_counter_node`
  - subscribes to `sensor_msgs/msg/Image`
  - runs YOLO inference
  - publishes counts as JSON on `std_msgs/msg/String`
  - can optionally publish an annotated image

- `face_recognize_node`
  - subscribes to `sensor_msgs/msg/Image`
  - preloads known face encodings from `server/assets/known_face/`
  - publishes recognition results as JSON on `std_msgs/msg/String`
  - can optionally publish an annotated image

- `tcp_bridge_node`
  - serves TCP clients on `0.0.0.0:9000` by default
  - accepts length-prefixed JSON requests
  - forwards material/face image requests into ROS topics
  - waits for existing ROS result topics and returns them to the TCP client
  - stores inventory in/out records into a CSV file

- `single_image_client`
  - publishes one image to `/material_counter/image`
  - listens on `/material_counter/counts`

- `face_recognize_client`
  - publishes one image to `/face_recognize/image`
  - listens on `/face_recognize/result`

## Default Topics

- material input image: `/material_counter/image`
- material output counts: `/material_counter/counts`
- material annotated image: `/material_counter/annotated_image`
- face input image: `/face_recognize/image`
- face output result: `/face_recognize/result`
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

Start the material counting node:

```bash
ros2 run server material_counter_node
```

Start the face recognition node:

```bash
ros2 run server face_recognize_node
```

Start only the TCP bridge node:

```bash
ros2 run server tcp_bridge_node
```

Start all three together:

```bash
ros2 launch server tcp_bridge.launch.py
```

Send one image and print the material result:

```bash
ros2 run server single_image_client --ros-args -p image_path:=/absolute/path/to/image.jpg
```

Send one image to the face recognition node:

```bash
ros2 run server face_recognize_client --ros-args \
  -p image_path:=/absolute/path/to/image.jpg
```

## ROS Result Payloads

Material counting result:

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

Face recognition result:

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

## TCP Protocol

The TCP bridge uses:

- one TCP connection can carry multiple requests
- each message is `4-byte big-endian length prefix + UTF-8 JSON body`
- every request has:
  - `type`
  - optional `request_id`
  - `payload`

Supported request types:

- `material_image`
- `face_image`
- `inventory_record`

### Image Request

```json
{
  "type": "material_image",
  "request_id": "req-001",
  "payload": {
    "image_base64": "<base64>",
    "image_format": "jpg"
  }
}
```

`face_image` uses the same payload shape.

### Inventory Request

```json
{
  "type": "inventory_record",
  "request_id": "req-002",
  "payload": {
    "time": "2026-04-25T21:30:00+08:00",
    "person": "huanghexiang",
    "action": "出库",
    "items": [
      {"name": "cboard", "quantity": 2},
      {"name": "m3508", "quantity": 1}
    ]
  }
}
```

`action` accepts `入库`, `出库`, `in`, or `out`. It is normalized to Chinese before writing the CSV.

### Success Response

```json
{
  "ok": true,
  "type": "material_image_result",
  "request_id": "req-001",
  "data": {
    "frame_id": "req-001",
    "stamp_sec": 1777119153,
    "stamp_nanosec": 0,
    "counts": {
      "cboard": 2
    },
    "total_detections": 2
  }
}
```

`face_image_result` wraps the face recognition ROS JSON. `inventory_record_result` returns the CSV path, rows written, and server receive time.

### Error Response

```json
{
  "ok": false,
  "type": "error",
  "request_id": "req-001",
  "error": {
    "code": "TIMEOUT",
    "message": "Timed out waiting for material_image_result"
  }
}
```

Common error codes include:

- `INVALID_JSON`
- `INVALID_REQUEST`
- `INVALID_PAYLOAD`
- `INVALID_IMAGE`
- `INVALID_IMAGE_FORMAT`
- `INVALID_INVENTORY`
- `UNKNOWN_TYPE`
- `DUPLICATE_REQUEST_ID`
- `TIMEOUT`

## Inventory CSV

Default CSV path:

```text
~/.ros/server/inventory_records.csv
```

CSV columns:

- `request_id`
- `record_time`
- `person`
- `action`
- `material_name`
- `quantity`
- `received_at`

Each material item is written as one CSV row so a single request may expand into multiple rows.

## Minimal Python TCP Client Example

```python
import base64
import json
import socket
import struct
from pathlib import Path

body = {
    "type": "inventory_record",
    "request_id": "demo-001",
    "payload": {
        "time": "2026-04-25T21:30:00+08:00",
        "person": "huanghexiang",
        "action": "入库",
        "items": [
            {"name": "cboard", "quantity": 2},
        ],
    },
}

encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")

with socket.create_connection(("127.0.0.1", 9000)) as sock:
    sock.sendall(struct.pack("!I", len(encoded)) + encoded)
    header = sock.recv(4)
    length = struct.unpack("!I", header)[0]
    response = sock.recv(length)
    print(json.loads(response.decode("utf-8")))
```
