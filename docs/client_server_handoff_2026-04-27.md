# Client / Server Handoff

Date: 2026-04-27

## Goal Summary

This handoff captures the work completed across the current conversation so a later session can continue without re-reading the full thread.

Main requests covered:

1. Make `client` use `rpicam` on Raspberry Pi instead of relying on OpenCV camera device access.
2. Remove ROS2-based build/install requirements from `client` and turn it into a standalone Python package with a clear file structure.
3. Fix `client` installation issues caused by `PyQt5` by replacing the UI toolkit with `tkinter`.
4. Change UI-facing Chinese text to English to avoid garbled display like `/u578`.
5. Raise/parameterize preview FPS, with default adjusted to `5`.
6. Add a manual UI button to capture material images because the previous automatic material-capture decision was inaccurate.
7. Change the default `server` CSV output path from `~/.ros/...` to `server/assets/...`.

## What Changed

### 1. `client` camera backend

`client` camera capture now supports backend selection and prefers `rpicam` when available.

Key files:

- `client/client/camera_backend.py`
- `client/client/camera_node.py`

Behavior:

- `camera_backend=auto` prefers `rpicam-still`, otherwise falls back to OpenCV.
- `rpicam-still` is invoked via stdout JPEG output and decoded in memory.
- OpenCV backend is still available for USB cameras.

### 2. `client` is no longer a ROS2 package

Removed ROS2 package/build artifacts from `client`:

- `client/CMakeLists.txt`
- `client/package.xml`
- `client/launch/client.launch.py`
- `client/srv/*`
- old ROS2 script entrypoints under `client/scripts/`

Added standard Python packaging:

- `client/pyproject.toml`
- `client/scripts/run_client`

Current install/run model:

```bash
cd /home/cells/embedded/client
pip install -e .
embedded-client
```

or:

```bash
python scripts/run_client
```

### 3. `client` UI toolkit changed from `PyQt5` to `tkinter`

Reason:

- On the target environment, `pip` attempted to build `PyQt5` from source and failed because `qmake` was missing.

Fix:

- Removed `PyQt5` from `client/pyproject.toml`
- Reimplemented the UI in `client/client/ui_node.py` using `tkinter`

Current dependency notes:

- `opencv-python`
- `numpy`
- Python with `tkinter` support
- On conda, `conda install tk` may still be needed if `tkinter` is missing

### 4. UI English-only text

All user-facing UI/status text in `client` was changed to English to avoid Chinese rendering/encoding issues.

Key files:

- `client/client/ui_node.py`
- `client/client/logic_node.py`
- `client/client/logic_utils.py`

Note:

- Chinese action labels `"入库"` / `"出库"` are still kept inside the inventory payload sent to `server`.
- Those two strings are intentionally preserved for protocol compatibility and are not directly shown in the UI.

### 5. FPS handling

Default FPS was reduced from `15` to `5` and exposed as a clear runtime parameter.

Key file:

- `client/client/config.py`

Current behavior:

- `--fps` controls camera capture target FPS
- UI refresh also follows the same FPS-derived interval

Examples:

```bash
embedded-client --fps 5
embedded-client --fps 8
```

### 6. Manual material capture

The previous pre-material capture flow relied on automatic timing/stability logic and was reported as inaccurate.

Current flow:

1. Click `Start`
2. Face recognition runs
3. After a valid known face is recognized, user moves camera to materials
4. User clicks `Capture Materials`
5. Pre-operation material snapshot is sent to `server`
6. UI enters waiting state
7. User performs the real-world operation
8. User clicks `Finish`
9. Post-operation material snapshot is sent to `server`
10. Diff is computed and inventory is uploaded

Key files:

- `client/client/ui_node.py`
- `client/client/logic_node.py`

Important implementation detail:

- `LogicNode.capture_material_now()` was added for manual pre-capture.
- Automatic stable-preview-triggered pre-capture was removed from the live workflow path.

### 7. `server` CSV default path

The default inventory CSV path was changed from:

```text
~/.ros/server/inventory_records.csv
```

to auto-resolution under:

```text
server/assets/inventory_records.csv
```

Key files:

- `server/server/image_utils.py`
- `server/server/tcp_bridge_node.py`
- `server/launch/tcp_bridge.launch.py`
- `server/README.md`

Implementation detail:

- `inventory_csv_path` parameter now defaults to `"auto"`
- `"auto"` resolves to `server/assets/inventory_records.csv`
- explicit custom paths are still supported

## Current Important Files

### Client

- `client/pyproject.toml`
- `client/client/config.py`
- `client/client/camera_backend.py`
- `client/client/camera_node.py`
- `client/client/tcp_client_node.py`
- `client/client/logic_node.py`
- `client/client/ui_node.py`
- `client/client/logic_utils.py`
- `client/README.md`

### Server

- `server/server/tcp_bridge_node.py`
- `server/server/image_utils.py`
- `server/launch/tcp_bridge.launch.py`
- `server/README.md`

## Validation Already Run

Client-side checks run successfully:

```bash
python3 -m unittest discover -s client/test -v
python3 -m compileall client/client client/test
```

Server-side checks run successfully:

```bash
python3 -m unittest discover -s server/test -v
python3 -m compileall server/server
```

`client` install flow was also verified:

```bash
cd client
python3 -m pip install -e .
```

## Known Remaining Notes

### 1. `client/README.md` still has some Chinese prose

The UI text and runtime status messages were converted to English, but the README itself still contains some Chinese explanatory sections. This is not a runtime bug, only a documentation consistency issue.

### 2. Old compatibility parameters remain in `client`

These parameters still exist but are currently compatibility leftovers from the old auto-capture flow:

- `--settle-delay-sec`
- `--stable-hold-sec`
- `--stability-threshold`
- `--stable-timeout-sec`

They no longer drive the main manual pre-capture path and may be removable in a future cleanup.

### 3. `waiting_camera_stable` state label still exists in UI mappings

The old state label remains defined for compatibility, but the main pre-capture flow is now manual via `Capture Materials`.

### 4. Inventory payload action language

The values `"入库"` and `"出库"` are still emitted toward `server`. Do not change them casually unless the server-side protocol is updated at the same time.

## Recommended Next Steps

If a future session continues this work, likely useful follow-ups are:

1. Clean up unused legacy workflow parameters and obsolete state names in `client`.
2. Finish converting `client/README.md` to fully English or fully consistent bilingual documentation.
3. Consider adding a visible confirmation thumbnail or timestamp after `Capture Materials` is pressed.
4. Add a small unit/integration test around the new manual pre-capture workflow if needed.
5. If CSV post-processing will be important, consider also exposing a dedicated `server/assets/exports/` directory structure.

## Quick Start Snapshot

### Client

```bash
cd /home/cells/embedded/client
pip install -e .
embedded-client --camera-backend rpicam --fps 5 --server-host <server_ip> --server-port 9100
```

### Server

```bash
ros2 launch server tcp_bridge.launch.py
```

By default, inventory CSV should now land at:

```text
server/assets/inventory_records.csv
```
