from __future__ import annotations

import csv
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any


INBOUND_ACTIONS = {"入库", "in", "inbound"}
OUTBOUND_ACTIONS = {"出库", "out", "outbound"}
INTEGER_EPSILON = 1e-9


def parse_timestamp(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None

    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def parse_quantity(value: Any) -> int | float:
    text = str(value).strip()
    if not text:
        return 0

    quantity = float(text)
    if abs(quantity - round(quantity)) < INTEGER_EPSILON:
        return int(round(quantity))
    return round(quantity, 3)


def normalize_number(value: int | float) -> int | float:
    number = float(value)
    if abs(number - round(number)) < INTEGER_EPSILON:
        return int(round(number))
    return round(number, 3)


def normalize_action(action: str) -> tuple[str, int]:
    raw = (action or "").strip()
    lowered = raw.lower()
    if raw in INBOUND_ACTIONS or lowered in INBOUND_ACTIONS:
        return "入库", 1
    if raw in OUTBOUND_ACTIONS or lowered in OUTBOUND_ACTIONS:
        return "出库", -1
    return raw or "未知", 0


def build_material_key(material_name: str) -> str:
    text = (material_name or "").strip()
    slug = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "-", text.casefold()).strip("-")
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
    return f"{slug or 'material'}-{digest}"


def get_stock_status(quantity: int | float) -> tuple[str, str]:
    amount = float(quantity)
    if amount <= 0:
        return "待补货", "empty"
    if amount <= 2:
        return "偏低", "low"
    if amount <= 5:
        return "平稳", "steady"
    return "充足", "good"


def to_sort_value(timestamp: datetime | None, row_index: int) -> tuple[float, int]:
    if timestamp is None:
        return float(row_index), row_index
    return timestamp.timestamp(), row_index


def build_dashboard_data(csv_path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    csv_path = Path(csv_path)
    events: list[dict[str, Any]] = []

    if csv_path.exists() and csv_path.stat().st_size > 0:
        with csv_path.open("r", newline="", encoding="utf-8") as csv_file:
            for row_index, row in enumerate(csv.DictReader(csv_file), start=1):
                material_name = (row.get("material_name") or "").strip()
                if not material_name:
                    continue

                quantity = parse_quantity(row.get("quantity", "0"))
                action_label, direction = normalize_action(str(row.get("action", "")))
                record_time = (row.get("record_time") or "").strip()
                received_at = (row.get("received_at") or "").strip()
                timestamp = parse_timestamp(record_time) or parse_timestamp(received_at)
                delta = normalize_number(float(quantity) * direction)

                events.append(
                    {
                        "row_index": row_index,
                        "request_id": (row.get("request_id") or "").strip() or f"row-{row_index}",
                        "record_time": record_time,
                        "received_at": received_at,
                        "display_time": record_time or received_at or "-",
                        "timestamp": timestamp,
                        "sort_value": to_sort_value(timestamp, row_index),
                        "person": (row.get("person") or "").strip() or "未知人员",
                        "action": action_label,
                        "material_name": material_name,
                        "quantity": normalize_number(quantity),
                        "delta": delta,
                    }
                )

    events.sort(key=lambda item: item["sort_value"])

    materials_map: dict[str, dict[str, Any]] = {}
    details_map: dict[str, dict[str, Any]] = {}
    people: set[str] = set()

    for event in events:
        people.add(event["person"])
        material_key = build_material_key(event["material_name"])

        if material_key not in materials_map:
            materials_map[material_key] = {
                "material_key": material_key,
                "material_name": event["material_name"],
                "current_quantity": 0.0,
                "total_inbound": 0.0,
                "total_outbound": 0.0,
                "transaction_count": 0,
                "last_person": "-",
                "last_action": "-",
                "last_time": "-",
                "last_sort_value": float("-inf"),
            }
            details_map[material_key] = {"summary": {}, "history": []}

        material_state = materials_map[material_key]
        material_state["current_quantity"] = float(material_state["current_quantity"]) + float(event["delta"])
        if float(event["delta"]) > 0:
            material_state["total_inbound"] = float(material_state["total_inbound"]) + float(event["quantity"])
        elif float(event["delta"]) < 0:
            material_state["total_outbound"] = float(material_state["total_outbound"]) + float(event["quantity"])
        material_state["transaction_count"] += 1
        material_state["last_person"] = event["person"]
        material_state["last_action"] = event["action"]
        material_state["last_time"] = event["display_time"]
        material_state["last_sort_value"] = event["sort_value"][0]

        running_quantity = normalize_number(material_state["current_quantity"])
        details_map[material_key]["history"].append(
            {
                "request_id": event["request_id"],
                "record_time": event["record_time"],
                "received_at": event["received_at"],
                "display_time": event["display_time"],
                "person": event["person"],
                "action": event["action"],
                "material_name": event["material_name"],
                "quantity": event["quantity"],
                "delta": event["delta"],
                "running_quantity_after": running_quantity,
            }
        )

    materials: list[dict[str, Any]] = []
    total_quantity = 0.0
    low_stock_types = 0

    for material_key, material_state in materials_map.items():
        current_quantity = normalize_number(material_state["current_quantity"])
        total_inbound = normalize_number(material_state["total_inbound"])
        total_outbound = normalize_number(material_state["total_outbound"])
        status_label, status_tone = get_stock_status(current_quantity)
        if float(current_quantity) <= 2:
            low_stock_types += 1

        total_quantity += float(current_quantity)
        summary = {
            "material_key": material_key,
            "material_name": material_state["material_name"],
            "current_quantity": current_quantity,
            "total_inbound": total_inbound,
            "total_outbound": total_outbound,
            "transaction_count": material_state["transaction_count"],
            "last_person": material_state["last_person"],
            "last_action": material_state["last_action"],
            "last_time": material_state["last_time"],
            "status_label": status_label,
            "status_tone": status_tone,
            "last_sort_value": material_state["last_sort_value"],
        }
        materials.append(summary)
        details_map[material_key]["summary"] = {
            key: value for key, value in summary.items() if key != "last_sort_value"
        }
        details_map[material_key]["history"] = list(reversed(details_map[material_key]["history"]))

    materials.sort(
        key=lambda item: (
            {"empty": 0, "low": 1, "steady": 2, "good": 3}.get(item["status_tone"], 4),
            -float(item["last_sort_value"]),
            item["material_name"].casefold(),
        )
    )
    for item in materials:
        item.pop("last_sort_value", None)

    recent_events = [
        {
            "request_id": event["request_id"],
            "display_time": event["display_time"],
            "person": event["person"],
            "action": event["action"],
            "material_name": event["material_name"],
            "quantity": event["quantity"],
            "delta": event["delta"],
        }
        for event in reversed(events[-12:])
    ]

    latest_event_time = recent_events[0]["display_time"] if recent_events else "-"
    payload = {
        "source_csv": str(csv_path),
        "stats": {
            "material_types": len(materials),
            "total_quantity": normalize_number(total_quantity),
            "active_people": len(people),
            "low_stock_types": low_stock_types,
            "total_transactions": len(events),
            "latest_event_time": latest_event_time,
        },
        "materials": materials,
        "recent_events": recent_events,
    }
    return payload, details_map
