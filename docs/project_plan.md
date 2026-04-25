# YOLO 物资检测项目计划

## 1. 项目目标

项目目标是完成一个基于 YOLO 的物资检测系统，输入单张图片，输出：

- 每个物资的检测框
- 每个类别的数量统计
- 可视化结果图

第一版聚焦离线图片检测与计数，适用于固定类别的物资，不包含实时视频流检测。

## 2. 环境与设备

- Python 环境：`alg`
- 训练框架：`ultralytics`
- 深度学习框架：`torch`
- 用户交互终端状态：`nvidia-smi` 可以识别 RTX4060，驱动版本 `580.126.09`，CUDA 版本 `13.0`
- Codex 工具执行环境状态：可能因为沙箱隔离无法访问 GPU，因此工具内的 `nvidia-smi` 或 `torch.cuda.is_available()` 结果不一定代表真实终端状态
- 风险说明：正式训练前请在你自己的终端中确认 PyTorch 能看到 CUDA

建议先执行：

```bash
conda run -n alg python scripts/check_env.py
conda run -n alg python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no cuda')"
```

如果结果显示 CUDA 不可用：

- 若只是在 Codex 工具环境里不可用，但你的终端可用，以你的终端结果为准
- 若你的终端里 PyTorch 也不可用，可以先在 CPU 上验证脚本和数据格式
- 正式训练建议等 PyTorch 在你的终端中能识别 RTX4060 后再开始

## 3. 数据采集策略

数据以现场拍摄为主，要求覆盖实际使用场景。每个类别都应采集以下变化：

- 不同距离：近景、中景、远景
- 不同角度：俯视、平视、侧视、斜视
- 不同光照：自然光、弱光、强反光、阴影
- 不同背景：桌面、地面、杂乱背景、相近颜色背景
- 不同摆放方式：单个、多个分散、局部遮挡、密集摆放

建议第一轮先保证每个类别至少有一个可训练的基础样本量，再逐步补困难样本。与其先追求超多类别，不如先把固定类别做准。

## 4. 数据标注策略

标注工具默认使用 `labelImg`，并导出为 YOLO 检测格式。类别定义以 `configs/classes.yaml` 为准。

标注时遵循以下原则：

- 每个独立物资标一个框
- 框尽量紧贴物体外接边界
- 遮挡但仍可辨认的目标继续标注
- 完全无法确定类别的不标，或放入待复核图片
- 同一个物资只能标一次，避免重复框
- 类别命名必须统一，不允许同义词或大小写混用

详细操作见 [docs/annotation_guide.md](/home/cells/embedded/docs/annotation_guide.md)。

## 5. 训练流程

建议训练流程分四步：

1. 数据集整理：检查图片和标签是否一一对应，确认类别 id 正确。
2. 首轮训练：使用小模型和较温和训练参数跑通基线。
3. 验证分析：查看 mAP、Precision、Recall，并人工检查漏检和误检案例。
4. 迭代优化：优先补充困难样本和修正错误标注，再考虑调参。

默认命令：

```bash
conda run -n alg python scripts/train.py
```

如果要明确使用 RTX4060：

```bash
conda run -n alg python scripts/train.py --device 0
```

## 6. 评估与验收

首轮验收至少包括：

- 环境检查脚本正常运行
- 训练脚本能读到数据配置并启动训练
- 验证脚本能输出 mAP、Precision、Recall
- 推理脚本能对单张图片输出可视化结果和计数结果
- 人工抽检若干图片时，计数结果格式正确

如果第一轮模型表现不好，优先检查：

- 是否存在漏标、错标、重复标注
- 是否某些类别样本过少
- 是否训练集与验证集场景差异过大
- 是否图片中存在强反光、模糊或严重遮挡
