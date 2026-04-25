# Material Detector YOLO Plan

## 1. Goals

- Build a standalone YOLO-based module for multi-object material counting per frame.
- Ignore material ID and only detect class + quantity.
- Support deployment flow: Raspberry Pi capture -> server inference -> JSON result back.
- Keep all implementation out of `system/` directory.

## 2. Current Environment

- Conda env: `ai`
- Python: 3.13
- Existing in `ai`: `opencv-python`, `numpy`
- To install: `ultralytics`, `torch`, `onnxruntime-gpu`
- Server has NVIDIA RTX 4060, so default inference/training device is GPU (`device=0`).

## 3. Deliverables

- New folder: `material_detector_yolo/`
- Reusable detector module: `detector.py`
- TCP inference server: `detect_server.py`
- Raspberry Pi capture client: `pi_capture_client.py`
- Training script: `train.py`
- Validation script: `val.py`
- ONNX export script: `export_onnx.py`
- Local smoke test: `smoke_test.py`
- Full docs: `README.md`, `dataset/README.md`

## 4. Network Protocol

Request:
1. Client -> Server: `DETECT_MATERIALS,<byte_len>`
2. Server -> Client: `ok`
3. Client -> Server: JPEG bytes

Response:
4. Server -> Client: `RESULT,<json_len>`
5. Client -> Server: `ok`
6. Server -> Client: JSON bytes

Why this protocol:
- Avoid truncation risks from fixed 1024-byte text payloads.
- Supports larger JSON responses with many detections.

## 5. Dataset Labeling Plan (YOLO Detection)

- Use bounding-box labels (not classification folders).
- Label each material instance in frame with class only.
- YOLO txt format per object:

```text
<class_id> <x_center> <y_center> <width> <height>
```

- Suggested split: train/val/test = 70/20/10.
- Suggested minimum per class: 300+ instances, covering angle, light, occlusion.

## 6. Training Plan

Install (in `ai`):

```bash
conda run -n ai python -m pip install --upgrade pip
conda run -n ai python -m pip install -r material_detector_yolo/requirements.txt
conda run -n ai python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
```

Train:

```bash
conda run -n ai python material_detector_yolo/train.py \
  --data material_detector_yolo/configs/data.yaml \
  --model yolov8n.pt \
  --epochs 100 \
  --imgsz 640 \
  --batch 16 \
  --device 0 \
  --project material_detector_yolo/artifacts \
  --name yolov8n_material
```

Validate:

```bash
conda run -n ai python material_detector_yolo/val.py \
  --model material_detector_yolo/artifacts/yolov8n_material/weights/best.pt \
  --data material_detector_yolo/configs/data.yaml \
  --imgsz 640 \
  --device 0
```

Export ONNX:

```bash
conda run -n ai python material_detector_yolo/export_onnx.py \
  --model material_detector_yolo/artifacts/yolov8n_material/weights/best.pt \
  --imgsz 640 \
  --device 0
```

## 7. Inference Return Contract

Server JSON response (success):

```json
{
  "ok": true,
  "counts": {"c620": 2, "m3508": 1},
  "total_objects": 3,
  "detections": [
    {"class_id": 0, "label": "c620", "conf": 0.92, "bbox": [10, 20, 100, 140]}
  ],
  "latency_ms": 21.35,
  "device": 0
}
```

Server JSON response (error):

```json
{
  "ok": false,
  "error": "Image decode failed"
}
```

## 8. Integration Plan for Existing System

- Keep this project independent for now.
- Later integration point in existing server/client flow:
  - Add command branch `DETECT_MATERIALS` in main server loop.
  - Reuse `MaterialDetector.predict_jpeg_bytes()`.
  - Return class counts and detections to client UI.

## 9. Validation Checklist

- `python -m py_compile material_detector_yolo/*.py` passes.
- Local image smoke test returns non-empty detections on sample data.
- Pi client can send image and receive JSON result from server.
- Continuous request loop remains stable under repeated calls.
