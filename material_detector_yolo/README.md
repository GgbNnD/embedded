# YOLO Material Detector (Standalone)

This folder provides a standalone YOLO workflow for **multi-object material detection and counting** in one frame.

- Input: one image/frame (from Raspberry Pi or local file)
- Output: material class counts + detection details
- Scope: class and quantity only, no material ID tracking

## 1. Folder Overview

- `detector.py`: reusable inference class (`MaterialDetector`)
- `detect_server.py`: TCP inference server
- `pi_capture_client.py`: Raspberry Pi capture + request client
- `train.py`: model training wrapper
- `val.py`: model validation wrapper
- `export_onnx.py`: export `.pt` to `.onnx`
- `smoke_test.py`: local single-image test
- `configs/data.yaml`: YOLO dataset config
- `configs/classes.txt`: class name list
- `dataset/README.md`: labeling guide
- `PLAN.md`: project execution plan

## 2. Install (Conda env: ai)

```bash
conda run -n ai python -m pip install --upgrade pip
conda run -n ai python -m pip install -r material_detector_yolo/requirements.txt
conda run -n ai python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
```

If you use another CUDA version, replace `cu124` accordingly.

## 3. Dataset Labeling

Please follow `material_detector_yolo/dataset/README.md`.

Quick points:
- Label format is YOLO detection format.
- One object per line.
- Each image has same-name `.txt` label file.
- Only class labels are needed, no instance ID labels.

## 4. Configure Classes and Data

1. Edit `material_detector_yolo/configs/classes.txt`
2. Edit `material_detector_yolo/configs/data.yaml` names mapping to match class IDs

Example:

```yaml
names:
  0: c620
  1: m3508
  2: jetson_nano
```

## 5. Train

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

Best model is usually:

`material_detector_yolo/artifacts/yolov8n_material/weights/best.pt`

## 6. Validate

```bash
conda run -n ai python material_detector_yolo/val.py \
  --model material_detector_yolo/artifacts/yolov8n_material/weights/best.pt \
  --data material_detector_yolo/configs/data.yaml \
  --imgsz 640 \
  --device 0
```

## 7. Export ONNX (Optional)

```bash
conda run -n ai python material_detector_yolo/export_onnx.py \
  --model material_detector_yolo/artifacts/yolov8n_material/weights/best.pt \
  --imgsz 640 \
  --device 0
```

## 8. Local Inference Test

```bash
conda run -n ai python material_detector_yolo/smoke_test.py \
  --model material_detector_yolo/artifacts/yolov8n_material/weights/best.pt \
  --image /path/to/test.jpg \
  --classes material_detector_yolo/configs/classes.txt \
  --device 0 \
  --out material_detector_yolo/artifacts/debug/test_out.jpg
```

## 9. Start Detection Server

```bash
conda run -n ai python material_detector_yolo/detect_server.py \
  --host 0.0.0.0 \
  --port 8090 \
  --model material_detector_yolo/artifacts/yolov8n_material/weights/best.pt \
  --classes material_detector_yolo/configs/classes.txt \
  --device 0 \
  --conf 0.35 \
  --iou 0.45 \
  --imgsz 640
```

## 10. Raspberry Pi Client Call

### 10.1 Use camera capture

```bash
conda run -n ai python material_detector_yolo/pi_capture_client.py \
  --host <server_ip> \
  --port 8090 \
  --backend rpicam \
  --width 640 \
  --height 480
```

### 10.2 Use an existing image file

```bash
conda run -n ai python material_detector_yolo/pi_capture_client.py \
  --host <server_ip> \
  --port 8090 \
  --image /path/to/frame.jpg
```

## 11. How to Load Model in Other Modules

```python
from material_detector_yolo.detector import MaterialDetector

detector = MaterialDetector(
    model_path="material_detector_yolo/artifacts/yolov8n_material/weights/best.pt",
    class_names="material_detector_yolo/configs/classes.txt",
    conf_threshold=0.35,
    iou_threshold=0.45,
    device=0,
    imgsz=640,
)

result = detector.predict(frame_bgr)
print(result["counts"])         # {'c620': 2, 'm3508': 1}
print(result["detections"])     # full detection list with bbox/conf
```

## 12. Notes

- `device=0` uses GPU 0 (recommended on your 4060 server).
- If GPU dependencies are not ready, temporarily set `device=cpu`.
- For better counting in crowded scenes, prioritize data quality and occlusion samples.

## 13. Integrated Server/Client Framework

The main project has been integrated with this workflow:

- `server/integrated_server.py` adds:
  - `DETECT_MATERIALS,<len>` command for YOLO detection
  - `DATA_JSON,<len>` command for structured transaction storage
  - detector runtime options:
    - `--material-model`
    - `--material-classes`
    - `--material-device`
    - `--material-conf`
    - `--material-iou`
    - `--material-imgsz`

- `client/smart_client.py` flow becomes:
  1. face recognition
  2. before snapshot detection
  3. open door and user operation
  4. after snapshot detection
  5. delta calculation (`after-before`)
  6. send `DATA_JSON` to server

### Start integrated server example

```bash
conda run -n ai python server/integrated_server.py \
  --type cli \
  --material-model material_detector_yolo/artifacts/yolov8n_material/weights/best.pt \
  --material-classes material_detector_yolo/configs/classes.txt \
  --material-device 0 \
  --material-conf 0.35 \
  --material-iou 0.45 \
  --material-imgsz 640
```

The transaction log is saved to `material_transaction_log.csv`.
