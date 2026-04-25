# Dataset Structure and Labeling

Use YOLO detection labels, because you need multi-object counting in one frame.

## Folder layout

```text
dataset/
  images/
    train/
    val/
    test/
  labels/
    train/
    val/
    test/
```

Each image must have a same-name `.txt` label file under the corresponding labels folder.

## Label format

One object per line:

```text
<class_id> <x_center> <y_center> <width> <height>
```

- Values are normalized to `[0, 1]`
- `class_id` starts from 0 and maps to `configs/classes.txt` and `configs/data.yaml`

## Example

If image is `images/train/frame_0001.jpg`, label file is:

`labels/train/frame_0001.txt`

```text
0 0.512 0.487 0.210 0.180
1 0.232 0.611 0.145 0.120
```

## Labeling tips

- Draw one box for each visible material instance.
- Do not label material ID, only material class.
- Include crowded scenes and partial occlusion to improve counting robustness.
- Keep train/val/test split by scene/time to avoid leakage.
