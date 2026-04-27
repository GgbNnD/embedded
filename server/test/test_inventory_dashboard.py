from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from inventory_dashboard import build_dashboard_data, build_material_key  # noqa: E402


class InventoryDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.csv_path = Path(__file__).resolve().parents[1] / "assets" / "inventory_records.csv"

    def test_build_dashboard_data_aggregates_current_quantity(self) -> None:
        payload, _ = build_dashboard_data(self.csv_path)

        materials_by_name = {item["material_name"]: item for item in payload["materials"]}
        self.assertEqual(payload["stats"]["material_types"], 17)
        self.assertEqual(payload["stats"]["total_quantity"], 107)
        self.assertEqual(materials_by_name["Jetson Orin Nano"]["current_quantity"], 1)
        self.assertEqual(materials_by_name["ODrive S1"]["current_quantity"], 3)
        self.assertEqual(materials_by_name["工业继电器"]["current_quantity"], 16)

    def test_build_dashboard_data_exposes_detail_history(self) -> None:
        _, details_map = build_dashboard_data(self.csv_path)

        odrive_detail = details_map[build_material_key("ODrive S1")]
        self.assertEqual(odrive_detail["summary"]["last_person"], "黄鹤翔")
        self.assertEqual(odrive_detail["summary"]["last_action"], "出库")
        self.assertEqual(odrive_detail["summary"]["last_time"], "2026-04-27 16:18:44")
        self.assertEqual(len(odrive_detail["history"]), 5)
        self.assertEqual(odrive_detail["history"][0]["running_quantity_after"], 3)

    def test_build_dashboard_data_marks_low_stock(self) -> None:
        payload, _ = build_dashboard_data(self.csv_path)

        materials_by_name = {item["material_name"]: item for item in payload["materials"]}
        self.assertEqual(materials_by_name["Jetson Orin Nano"]["status_tone"], "low")
        self.assertEqual(materials_by_name["Jetson Orin Nano"]["status_label"], "偏低")


if __name__ == "__main__":
    unittest.main()
