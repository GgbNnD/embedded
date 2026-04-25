# 最终物资管理框架（Client-Server + 人脸 + YOLO计数）

## 1. 目标

基于现有 `client` 与 `server` 代码，形成一套可落地的端到端流程：

1. Client 拍摄人脸并发送到 Server。
2. Server 人脸识别成功后，Client 触发门禁流程。
3. 开门前后各做一次物资检测（种类+数量）。
4. 通过前后计数差异得到本次出入库详情。
5. 将交易详情发送到 Server 持久化存储。

此框架不依赖物资 ID，仅依赖 YOLO 检测的类别与数量。

---

## 2. 结合现有代码的职责划分

## Client 侧（基于 `client/smart_client.py`）

- 采集摄像头画面（树莓派 `rpicam-still` 或 OpenCV）。
- 调用 `RECOGNIZE` 完成人脸认证。
- 在认证成功后，调用物资检测接口获取“开门前快照”。
- 本地控制舵机开门/关门。
- 用户完成放入/拿出后，再次调用物资检测获取“关门后快照”。
- 计算差异（delta）并构建交易记录。
- 将交易记录发送给 Server 存储。

## Server 侧（基于 `server/integrated_server.py` + `material_detector_yolo`）

- 复用现有人脸识别逻辑（`RECOGNIZE`）。
- 新增物资检测命令（`DETECT_MATERIALS`），内部调用 YOLO 模型。
- 新增结构化存储命令（建议 `DATA_JSON`），写入 CSV/数据库。
- 提供审计字段：操作人、时间、前后快照、差异明细、推理耗时。

---

## 3. 端到端时序（最终流程）

1. 用户在 Client 点击“开始操作”（可选选择预期行为：入库/出库/混合）。
2. Client 抓拍人脸，发送 `RECOGNIZE,<face_len>` + 人脸图像。
3. Server 返回识别结果：
   - 失败：流程结束，不开门。
   - 成功：进入步骤 4。
4. Client 抓拍当前货架图，发送 `DETECT_MATERIALS,<img_len>`（开门前快照）。
5. Server 返回前快照统计 `before_counts`。
6. Client 开门（本地舵机），用户执行放入/拿出。
7. 用户点击“完成操作”，Client 关门后再次抓拍并发送 `DETECT_MATERIALS,<img_len>`（开门后快照）。
8. Server 返回后快照统计 `after_counts`。
9. Client 计算 `delta = after_counts - before_counts`，得到本次出入库详情。
10. Client 发送 `DATA_JSON,<len>` + 交易 JSON。
11. Server 存储并返回 `Saved`。

---

## 4. 协议建议（兼容现有风格）

## 4.1 人脸识别（已存在）

- Request: `RECOGNIZE,<byte_len>`
- Ack: `ok`
- Body: JPEG bytes
- Response: `name` / `Unknown` / `No face detected`

## 4.2 物资检测（新增）

- Request: `DETECT_MATERIALS,<byte_len>`
- Ack: `ok`
- Body: JPEG bytes
- Response Header: `RESULT,<json_len>`
- Ack: `ok`
- Response Body(JSON):

```json
{
  "ok": true,
  "counts": {"c620": 2, "dm_j4310": 1},
  "total_objects": 3,
  "detections": [
    {"class_id": 0, "label": "c620", "conf": 0.91, "bbox": [120, 80, 260, 230]}
  ],
  "latency_ms": 18.4,
  "device": 0
}
```

## 4.3 交易入库（建议新增）

- Request: `DATA_JSON,<byte_len>`
- Ack: `ok`
- Body: transaction JSON bytes
- Response: `Saved` / `Error:<reason>`

---

## 5. 差异计算规则（核心）

给定：

- `before_counts: dict[str, int]`
- `after_counts: dict[str, int]`

计算：

```text
delta[class] = after_counts.get(class, 0) - before_counts.get(class, 0)
```

解释：

- `delta > 0`：入库 `delta` 个
- `delta < 0`：出库 `abs(delta)` 个
- `delta = 0`：该类无变化

### 示例 1（单类入库）

- before: `{c620: 2}`
- after: `{c620: 5}`
- delta: `{c620: +3}` -> 入库 C620 x3

### 示例 2（单类出库）

- before: `{dm_j4310: 4}`
- after: `{dm_j4310: 1}`
- delta: `{dm_j4310: -3}` -> 出库 DM-J4310 x3

### 示例 3（混合变化）

- before: `{c620: 2, dm_j4310: 1}`
- after: `{c620: 1, dm_j4310: 3, m3508: 2}`
- delta:
  - c620: `-1`（出库 1）
  - dm_j4310: `+2`（入库 2）
  - m3508: `+2`（入库 2）

最终可标记为 `operation_type = mixed`。

---

## 6. 交易记录结构（建议）

```json
{
  "tx_id": "20260421-143055-a8f1",
  "timestamp": "2026-04-21 14:30:55",
  "person": "ZhangSan",
  "client_id": "rpi-01",
  "expected_action": "inbound",
  "actual_action": "mixed",
  "before_counts": {"c620": 2, "dm_j4310": 1},
  "after_counts": {"c620": 1, "dm_j4310": 3, "m3508": 2},
  "delta": {"c620": -1, "dm_j4310": 2, "m3508": 2},
  "detail": {
    "inbound": [{"material": "dm_j4310", "qty": 2}, {"material": "m3508", "qty": 2}],
    "outbound": [{"material": "c620", "qty": 1}]
  },
  "face_result": "ZhangSan",
  "before_latency_ms": 19.2,
  "after_latency_ms": 21.1
}
```

---

## 7. Server 存储策略

可先沿用 CSV，再逐步升级数据库。

## CSV 字段建议

- `Timestamp`
- `Person`
- `Expected Action`
- `Actual Action`
- `Before Counts(JSON)`
- `After Counts(JSON)`
- `Delta(JSON)`
- `Inbound Detail(JSON)`
- `Outbound Detail(JSON)`
- `Client ID`

> 这样可以保持与现有 `material_log.csv` 思路一致，同时支持结构化回溯。

---

## 8. 稳定性与误差控制（强烈建议）

为降低“单帧偶然误检”对差异结果的影响：

1. 开门前和关门后各采集 `N=3~5` 帧。
2. 每个类别取中位数/众数作为最终计数。
3. 只统计 `conf >= 0.35` 且框面积超过最小阈值的目标。
4. 检测失败时允许 1~2 次重试。

这样差异计算稳定性会显著提升。

---

## 9. 与现有代码的最小改造点

## Client (`client/smart_client.py`)

- 保留：人脸抓拍、网络重试、舵机控制、UI 状态机。
- 替换：原 `RECOGNIZE_QR` 循环为两次 `DETECT_MATERIALS`（前后快照）。
- 新增：`compute_delta(before_counts, after_counts)`。
- 新增：`send_data_json(payload)`。

## Server (`server/integrated_server.py`)

- 保留：`RECOGNIZE`、人脸库加载、TCP 主循环。
- 新增：`DETECT_MATERIALS` 分支，调用 `material_detector_yolo/detector.py`。
- 新增：`DATA_JSON` 分支，解析并存储结构化交易。

---

## 10. 成功判定标准

1. 人脸匹配成功才允许开门。
2. 开门前后都能返回物资类别计数。
3. `delta` 能稳定反映真实放入/拿出数量。
4. Server 能持久化完整交易记录并可审计回放。

---

## 11. 一句话总结

这个最终框架把“人脸认证 + 门禁 + 开门前后YOLO计数 + 差异结算 + Server存储”串成一条闭环链路，能在不依赖物资 ID 的前提下完成可追溯的出入库管理。
