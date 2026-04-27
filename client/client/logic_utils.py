from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


def parse_server_response(response_json: str) -> dict[str, Any]:
    try:
        payload = json.loads(response_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid server JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Server response must be a JSON object")
    return payload


def extract_single_known_person(server_response: dict[str, Any], *, unknown_label: str = "unknown") -> str | None:
    data = server_response.get("data")
    if not isinstance(data, dict):
        raise ValueError("Server response missing data object")

    total_faces = data.get("total_faces")
    results = data.get("results")
    if total_faces != 1 or not isinstance(results, list) or len(results) != 1:
        return None

    result = results[0]
    if not isinstance(result, dict):
        return None

    name = result.get("name")
    if not isinstance(name, str) or not name or name == unknown_label:
        return None
    return name


def extract_material_counts(server_response: dict[str, Any]) -> dict[str, int]:
    data = server_response.get("data")
    if not isinstance(data, dict):
        raise ValueError("Server response missing data object")

    counts = data.get("counts")
    if not isinstance(counts, dict):
        raise ValueError("Server response missing counts object")

    normalized: dict[str, int] = {}
    for name, quantity in counts.items():
        if not isinstance(name, str):
            raise ValueError("Material name must be a string")
        if isinstance(quantity, bool) or not isinstance(quantity, (int, float)):
            raise ValueError("Material quantity must be numeric")
        normalized[name] = int(quantity)
    return dict(sorted(normalized.items()))


def build_inventory_payload(record_time: str, person: str, action: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "time": record_time,
        "person": person,
        "action": action,
        "items": items,
    }


def compute_inventory_changes(
    pre_counts: dict[str, int],
    post_counts: dict[str, int],
) -> tuple[list[dict[str, int | str]], list[dict[str, int | str]]]:
    added_items: list[dict[str, int | str]] = []
    removed_items: list[dict[str, int | str]] = []

    for name in sorted(set(pre_counts) | set(post_counts)):
        pre_value = int(pre_counts.get(name, 0))
        post_value = int(post_counts.get(name, 0))
        delta = post_value - pre_value
        if delta > 0:
            added_items.append({"name": name, "quantity": delta})
        elif delta < 0:
            removed_items.append({"name": name, "quantity": -delta})

    return added_items, removed_items


def summarize_items(items: list[dict[str, Any]]) -> str:
    if not items:
        return "None"
    return ", ".join(f"{item['name']} x{item['quantity']}" for item in items)


def summarize_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "None"
    return ", ".join(f"{name}: {quantity}" for name, quantity in sorted(counts.items()))


@dataclass
class FrameStabilityTracker:
    threshold: float
    hold_duration_sec: float
    last_mean: float | None = None
    stable_since: float | None = None

    def reset(self) -> None:
        self.last_mean = None
        self.stable_since = None

    def update(self, mean_value: float, now_sec: float) -> bool:
        if self.last_mean is None:
            self.last_mean = mean_value
            return False

        difference = abs(mean_value - self.last_mean)
        self.last_mean = mean_value
        if difference < self.threshold:
            if self.stable_since is None:
                self.stable_since = now_sec
            return (now_sec - self.stable_since) >= self.hold_duration_sec

        self.stable_since = None
        return False
