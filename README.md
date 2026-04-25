# YOLO 物资检测项目

本项目用于训练一个基于 YOLO 的物资检测模型，目标是在单张图片中识别不同物资并统计数量。第一版聚焦离线图片检测与计数，适用于 `dmj4310`、`cboard`、`m3508` 等固定类别。

## 目录结构

```text
configs/                  类别与训练配置
datasets/materials/       YOLO 数据集目录
docs/                     项目说明与标注说明
outputs/                  推理输出与统计结果
scripts/                  环境检查、训练、验证、推理入口
src/materials_detector/   最小公共逻辑
weights/                  训练权重与预训练权重
```

## 环境准备

使用已有 conda 环境 `alg`：

```bash
conda activate alg
python scripts/check_env.py
```

如果 `CUDA available: False`，说明当前系统还没有把显卡驱动和 PyTorch CUDA 路径打通，此时只能先做 CPU 验证。

如果你在自己的终端中运行 `nvidia-smi` 能看到 RTX4060，但 `check_env.py` 在 Codex 工具环境中看不到 GPU，以你的交互终端结果为准。正式训练前建议再确认 PyTorch：

```bash
conda run -n alg python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no cuda')"
```

## 数据集准备

1. 按 [docs/annotation_guide.md](/home/cells/embedded/docs/annotation_guide.md) 采图并标注。
2. 将图片放入：
   - `datasets/materials/images/train`
   - `datasets/materials/images/val`
   - `datasets/materials/images/test`
3. 将对应 YOLO 标签放入：
   - `datasets/materials/labels/train`
   - `datasets/materials/labels/val`
   - `datasets/materials/labels/test`
4. 确保标签类别 id 和 `configs/classes.yaml` 一致。
5. 确保 `datasets/materials/labels/*/classes.txt` 的类别顺序和 `datasets/materials/data.yaml` 完全一致。

## 常用命令

数据集检查：

```bash
conda run -n alg python scripts/check_dataset.py
```

训练：

```bash
conda run -n alg python scripts/train.py --device 0
```

断点续训：

```bash
conda run -n alg python scripts/train.py --resume --device 0
```

验证：

```bash
conda run -n alg python scripts/val.py --weights weights/materials_yolo/best.pt
```

单图推理并统计数量：

```bash
conda run -n alg python scripts/predict.py \
  --weights weights/materials_yolo/best.pt \
  --source path/to/image.jpg
```

导出 ONNX：

```bash
conda run -n alg python scripts/export.py \
  --weights weights/materials_yolo/best.pt \
  --format onnx
```

当前训练完成后整理出的主要产物位于：

```text
weights/materials_yolo/best.pt
weights/materials_yolo/last.pt
weights/materials_yolo/best.onnx
weights/materials_yolo/best.torchscript
```

## ROS2 节点

已经新增 ROS2 包 [server/README.md](/home/cells/embedded/server/README.md)，用于把当前 YOLO 推理能力封装成节点。

构建与运行：

```bash
conda activate alg
source /opt/ros/humble/setup.bash
colcon build --packages-select server
source install/setup.bash
export ROS_LOCALHOST_ONLY=1
ros2 run server material_counter_node
```

用一张本地图片测试：

```bash
ros2 run server single_image_client --ros-args -p image_path:=/absolute/path/to/image.jpg
```

同一个 `server` 包中还新增了人脸识别节点，默认会在启动时预加载 [server/assets/known_face](/home/cells/embedded/server/assets/known_face)。

启动人脸识别节点：

```bash
ros2 run server face_recognize_node
```

发一张图片并接收识别结果：

```bash
ros2 run server face_recognize_client --ros-args \
  -p image_path:=/absolute/path/to/image.jpg
```

## 默认训练策略

- 采用检测模型，不做实例分割。
- 从官方小模型预训练权重开始微调。
- 第一轮优先跑通流程，观察漏检和误检，再回到数据采集和标注质量优化。
