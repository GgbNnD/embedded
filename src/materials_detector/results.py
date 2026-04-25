from __future__ import annotations

from collections import Counter


def summarize_counts(result) -> dict[str, int]:
    names = result.names
    class_ids = result.boxes.cls.tolist() if result.boxes is not None else []
    counter = Counter(names[int(class_id)] for class_id in class_ids)
    return dict(sorted(counter.items()))
