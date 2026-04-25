from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client"))

from logic_utils import (  # noqa: E402
    FrameStabilityTracker,
    compute_inventory_changes,
    extract_material_counts,
    extract_single_known_person,
    parse_server_response,
)


class LogicUtilsTests(unittest.TestCase):
    def test_parse_server_response_rejects_invalid_json(self) -> None:
        with self.assertRaises(ValueError):
            parse_server_response("not-json")

    def test_extract_single_known_person(self) -> None:
        payload = {
            "ok": True,
            "data": {
                "total_faces": 1,
                "results": [{"name": "cells"}],
            },
        }
        self.assertEqual(extract_single_known_person(payload), "cells")

    def test_extract_single_known_person_rejects_unknown_or_multiple(self) -> None:
        unknown_payload = {
            "ok": True,
            "data": {
                "total_faces": 1,
                "results": [{"name": "unknown"}],
            },
        }
        multi_payload = {
            "ok": True,
            "data": {
                "total_faces": 2,
                "results": [{"name": "cells"}, {"name": "other"}],
            },
        }
        self.assertIsNone(extract_single_known_person(unknown_payload))
        self.assertIsNone(extract_single_known_person(multi_payload))

    def test_extract_material_counts_normalizes(self) -> None:
        payload = {
            "ok": True,
            "data": {
                "counts": {
                    "m3508": 1.0,
                    "cboard": 2,
                }
            },
        }
        self.assertEqual(extract_material_counts(payload), {"cboard": 2, "m3508": 1})

    def test_compute_inventory_changes(self) -> None:
        added, removed = compute_inventory_changes(
            {"cboard": 2, "m3508": 1},
            {"cboard": 1, "m3508": 3, "dmj4310": 1},
        )
        self.assertEqual(added, [{"name": "dmj4310", "quantity": 1}, {"name": "m3508", "quantity": 2}])
        self.assertEqual(removed, [{"name": "cboard", "quantity": 1}])

    def test_frame_stability_tracker(self) -> None:
        tracker = FrameStabilityTracker(threshold=3.0, hold_duration_sec=1.0)
        self.assertFalse(tracker.update(10.0, 0.0))
        self.assertFalse(tracker.update(11.0, 0.2))
        self.assertFalse(tracker.update(10.5, 0.8))
        self.assertTrue(tracker.update(10.8, 1.3))

    def test_frame_stability_tracker_resets_on_large_delta(self) -> None:
        tracker = FrameStabilityTracker(threshold=3.0, hold_duration_sec=1.0)
        tracker.update(10.0, 0.0)
        tracker.update(11.0, 0.2)
        tracker.update(20.0, 0.5)
        self.assertFalse(tracker.update(20.5, 0.9))


if __name__ == "__main__":
    unittest.main()
