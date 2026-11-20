"""Regression tests for incomplete and complete display deployments."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend_scene3d.api import create_app
from backend_scene3d.config import Settings


class ReadinessTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="scene3d-ready-")
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.settings = Settings(
            root / "data", root / "runs", "synthetic-test-secret-" * 3
        )
        self.identifier = "s3d_" + "a" * 32

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def prepare_display(self):
        data, runs = self.settings.data, self.settings.runs
        files = {name: name + ".u16" for name in ("u", "v", "w", "height_agl")}
        self.write(
            data / "cesium_data/wrf3d/manifest.json",
            {
                "frames": [{"chunks": [{"files": files}]}],
            },
        )
        for name in files.values():
            self.write(data / "cesium_data/wrf3d" / name, [1])
        self.write(data / "cesium_data/wrf3d/terrain_height.f32", [0])
        self.write(
            data / "cesium_data/terrain_global/manifest.json", {"samples": 2}
        )
        self.write(data / "cesium-app/cesium/Cesium.js", "runtime fixture")
        self.write(
            data / "cesium-app/cesium/Widgets/widgets.css", "styles fixture"
        )
        self.write(runs / "baseline.json", {"run_id": self.identifier})
        self.write(
            runs / self.identifier / "result.json", {"frames": [{"index": 0}]}
        )
        self.write(runs / self.identifier / "geometry.json", {"towers": [{}]})
        self.write(runs / self.identifier / "frames/000.json", {"index": 0})

    def test_wrf_manifest_alone_is_not_ready(self):
        self.write(self.settings.data / "cesium_data/wrf3d/manifest.json", {})
        with TestClient(create_app(self.settings)) as client:
            response = client.get("/api/health")
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertFalse(body["data_ready"])
        self.assertIn("terrain_manifest", body["missing"])
        self.assertIn("cesium_script", body["missing"])
        self.assertIn("baseline_index", body["missing"])
        self.assertNotIn(str(self.settings.data), response.text)

    def test_complete_display_is_ready_without_submitting_work(self):
        self.prepare_display()
        with TestClient(create_app(self.settings)) as client:
            before = set(self.settings.runs.rglob("*"))
            with patch("backend_scene3d.jobs.Jobs.submit") as submit:
                response = client.get("/api/health")
                submit.assert_not_called()
            self.assertEqual(set(self.settings.runs.rglob("*")), before)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data_ready"])
        self.assertTrue(all(response.json()["checks"].values()))
        self.assertEqual(response.json()["missing"], [])

    def test_missing_display_assets_report_the_failed_check(self):
        self.prepare_display()
        data, runs = self.settings.data, self.settings.runs
        examples = {
            data / "cesium_data/wrf3d/manifest.json": "wrf_manifest",
            data / "cesium_data/wrf3d/u.u16": "wind_chunks",
            data
            / "cesium_data/wrf3d/terrain_height.f32": "wrf_terrain_height",
            data
            / "cesium_data/terrain_global/manifest.json": "terrain_manifest",
            data / "cesium-app/cesium/Cesium.js": "cesium_script",
            data / "cesium-app/cesium/Widgets/widgets.css": "cesium_styles",
            runs / "baseline.json": "baseline_index",
            runs / self.identifier / "result.json": "baseline_result",
            runs / self.identifier / "geometry.json": "baseline_geometry",
            runs / self.identifier / "frames/000.json": "baseline_frames",
        }
        with TestClient(create_app(self.settings)) as client:
            for path, key in examples.items():
                with self.subTest(check=key):
                    original = path.read_bytes()
                    try:
                        path.unlink()
                        response = client.get("/api/health")
                        self.assertEqual(response.status_code, 503)
                        self.assertFalse(response.json()["data_ready"])
                        self.assertIn(key, response.json()["missing"])
                    finally:
                        path.write_bytes(original)

    def test_corrupt_metadata_and_unsafe_baseline_index_are_not_ready(self):
        self.prepare_display()
        data, runs = self.settings.data, self.settings.runs
        with TestClient(create_app(self.settings)) as client:
            for relative in [
                "cesium_data/wrf3d/manifest.json",
                "cesium_data/terrain_global/manifest.json",
            ]:
                path = data / relative
                original = path.read_bytes()
                try:
                    path.write_text("{broken", encoding="utf-8")
                    self.assertEqual(
                        client.get("/api/health").status_code, 503
                    )
                finally:
                    path.write_bytes(original)
            self.write(runs / "baseline.json", {"run_id": "../outside"})
            response = client.get("/api/health")
            self.assertEqual(response.status_code, 503)
            self.assertIn("baseline_index", response.json()["missing"])


if __name__ == "__main__":
    unittest.main()
