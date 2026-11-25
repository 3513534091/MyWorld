"""预设管理的单元测试（纯标准库）。

运行：python tests/test_presets.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from myworld import presets, worlds  # noqa: E402


class PresetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.sandbox = Path(self.tmp.name)
        self.worlds_root = self.sandbox / "data"
        self.worlds_root.mkdir()
        self.root = presets.resolve_root(self.worlds_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_root_is_sibling_of_worlds(self) -> None:
        self.assertEqual(self.root, (self.sandbox / "presets").resolve())
        self.assertTrue(self.root.is_dir())

    def test_create_and_list(self) -> None:
        created = presets.create_preset(self.root, "快速出图")
        self.assertEqual(created["path"], "presets/快速出图")
        meta = json.loads((self.root / "快速出图" / "preset.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["name"], "快速出图")
        self.assertEqual(meta["format"], presets.FORMAT_VERSION)
        self.assertEqual([item["name"] for item in presets.list_presets(self.root)], ["快速出图"])

    def test_duplicate_rejected(self) -> None:
        presets.create_preset(self.root, "预设A")
        with self.assertRaises(worlds.WorldError) as ctx:
            presets.create_preset(self.root, "预设A")
        self.assertEqual(ctx.exception.status, 409)

    def test_name_rules_shared_with_worlds(self) -> None:
        for bad in ("", "../escape", "a/b", "CON", ".hidden"):
            with self.subTest(bad=bad):
                with self.assertRaises(worlds.WorldError):
                    presets.create_preset(self.root, bad)

    def test_presets_not_in_worlds_listing(self) -> None:
        worlds.create_world(self.worlds_root, "世界一")
        presets.create_preset(self.root, "预设B")
        names = [item["name"] for item in worlds.list_worlds(self.worlds_root)]
        self.assertEqual(names, ["世界一"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
