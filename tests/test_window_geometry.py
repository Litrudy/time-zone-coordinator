import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "时差协调器.py"
SPEC = importlib.util.spec_from_file_location("time_coordinator", MODULE_PATH)
APP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APP)


class DpiConversionTests(unittest.TestCase):
    def test_logical_and_physical_conversion(self):
        self.assertEqual(APP.logical_to_physical(320, 1.0), 320)
        self.assertEqual(APP.logical_to_physical(320, 1.25), 400)
        self.assertEqual(APP.logical_to_physical(320, 1.5), 480)
        self.assertEqual(APP.logical_to_physical(220, 2.0), 440)
        self.assertEqual(APP.physical_to_logical(480, 1.5), 320)


class ResizeGeometryTests(unittest.TestCase):
    def test_resize_from_south_east_corner(self):
        result = APP.calculate_resize_geometry(
            (100, 80, 320, 220), (40, 30), "se", (320, 220)
        )
        self.assertEqual(result, (100, 80, 360, 250))

    def test_resize_from_north_west_corner(self):
        result = APP.calculate_resize_geometry(
            (100, 80, 400, 300), (20, 30), "nw", (320, 220)
        )
        self.assertEqual(result, (120, 110, 380, 270))

    def test_minimum_size_keeps_opposite_edge_fixed(self):
        west = APP.calculate_resize_geometry(
            (100, 80, 400, 300), (200, 0), "w", (320, 220)
        )
        north = APP.calculate_resize_geometry(
            (100, 80, 400, 300), (0, 200), "n", (320, 220)
        )
        self.assertEqual(west, (180, 80, 320, 300))
        self.assertEqual(north, (100, 160, 400, 220))

    def test_geometry_is_clamped_to_secondary_monitor_work_area(self):
        result = APP.clamp_geometry_to_work_area(
            (-2100, -50, 900, 800),
            (-1920, 0, 0, 1040),
            (320, 220),
        )
        self.assertEqual(result, (-1920, 0, 900, 800))

    def test_oversized_geometry_fits_work_area(self):
        result = APP.clamp_geometry_to_work_area(
            (0, 0, 2400, 1400),
            (0, 0, 1920, 1040),
            (320, 220),
        )
        self.assertEqual(result, (0, 0, 1920, 1040))


class ConfigCompatibilityTests(unittest.TestCase):
    def _load(self, saved):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
            with mock.patch.object(APP, "get_config_path", return_value=path):
                return APP.load_config()

    def test_old_config_gets_default_window_size(self):
        config = self._load(
            {
                "local_city": "北京/上海",
                "target_city": "东京",
                "theme": "机械",
            }
        )
        self.assertEqual(config["window_width"], 320)
        self.assertEqual(config["window_height"], 220)

    def test_saved_logical_size_is_preserved(self):
        config = self._load({"window_width": 480, "window_height": 360})
        self.assertEqual(config["window_width"], 480)
        self.assertEqual(config["window_height"], 360)

    def test_invalid_or_too_small_size_uses_minimum(self):
        config = self._load({"window_width": True, "window_height": 100})
        self.assertEqual(config["window_width"], 320)
        self.assertEqual(config["window_height"], 220)


if __name__ == "__main__":
    unittest.main()
