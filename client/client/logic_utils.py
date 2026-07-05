"""
逻辑工具函数模块 (RK3399Pro 版)
===============================
提供出入库操作所需的纯工具函数:

  - compute_inventory_changes: 计算操作前后物资变化
  - build_inventory_payload: 构造出入库记录负载
  - summarize_items / summarize_counts: 格式化 UI 显示

由于人脸识别和物资检测都在本地运行, 不再需要从服务器解析结果。
"""


def compute_inventory_changes(pre_counts, post_counts):
    """计算出入库前后的物资数量变化

    比较两次检测结果, 生成新增/移除的物资列表。
    新增 = post - pre (入库); 移除 = pre - post (出库).

    Args:
        pre_counts: 操作前物资计数 dict {"cboard": 2, "m3508": 3}
        post_counts: 操作后物资计数 dict {"cboard": 1, "m3508": 5}

    Returns:
        (added_items: list, removed_items: list)
        每个 item 为: {"name": "cboard", "quantity": 2}
    """
    added_items = []
    removed_items = []

    all_names = sorted(set(pre_counts) | set(post_counts))

    for name in all_names:
        pre_value = int(pre_counts.get(name, 0))
        post_value = int(post_counts.get(name, 0))
        delta = post_value - pre_value

        if delta > 0:
            added_items.append({"name": name, "quantity": delta})
        elif delta < 0:
            removed_items.append({"name": name, "quantity": -delta})

    return added_items, removed_items


def build_inventory_payload(record_time, person, action, items):
    """构造出入库记录负载 (与服务器协议兼容)

    格式兼容 server/server/tcp_protocol.py 中的 validate_inventory_payload() 验证逻辑:
      {
        "time": "2026-07-05T10:30:00+08:00",
        "person": "张三",
        "action": "入库",   # "入库" 或 "出库"
        "items": [
          {"name": "cboard", "quantity": 2},
        ],
      }

    Args:
        record_time: 操作时间 (ISO 8601 格式字符串)
        person: 操作人姓名
        action: 操作类型 ("入库" 或 "出库")
        items: 物资变化列表 [{"name": str, "quantity": int}, ...]

    Returns:
        dict: 出入库记录负载 (可直接发送给服务器)
    """
    return {
        "time": record_time,
        "person": person,
        "action": action,
        "items": items,
    }


def summarize_items(items):
    """将物资变化列表格式化为 UI 可读字符串

    Args:
        items: [{"name": "cboard", "quantity": 2}, ...]

    Returns:
        str: "cboard x2, m3508 x1" 或 "None"
    """
    if not items:
        return "None"
    return ", ".join(f"{item['name']} x{item['quantity']}" for item in items)


def summarize_counts(counts):
    """将物资计数字典格式化为 UI 可读字符串

    Args:
        counts: {"cboard": 2, "m3508": 0}

    Returns:
        str: "cboard: 2, m3508: 0" 或 "None"
    """
    if not counts:
        return "None"
    return ", ".join(f"{name}: {quantity}" for name, quantity in sorted(counts.items()))
