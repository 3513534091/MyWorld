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

    def test_create_with_keys(self) -> None:
        created = presets.create_preset(self.root, "角色模板", ["年龄", " 身份 ", ""])
        self.assertEqual(created["keys"], ["年龄", "身份"])

        meta = json.loads((self.root / "角色模板" / "preset.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["keys"], ["年龄", "身份"])
        self.assertNotIn("attributes", meta)

        listed = presets.list_presets(self.root)[0]
        self.assertEqual(listed["keys"], ["年龄", "身份"])

    def test_keys_default_to_empty(self) -> None:
        created = presets.create_preset(self.root, "空预设")
        self.assertEqual(created["keys"], [])
        self.assertEqual(presets.list_presets(self.root)[0]["keys"], [])

    def test_keys_dedupe_and_accept_legacy_dicts(self) -> None:
        created = presets.create_preset(
            self.root,
            "去重",
            ["标签", "标签", {"label": "年龄", "value": "17"}, {"key": "身份"}],
        )
        self.assertEqual(created["keys"], ["标签", "年龄", "身份"])

    def test_legacy_preset_file_is_read_as_keys(self) -> None:
        legacy = self.root / "老预设"
        legacy.mkdir()
        (legacy / "preset.json").write_text(
            json.dumps(
                {
                    "name": "老预设",
                    "format": 1,
                    "attributes": [{"label": "年龄", "value": "17"}, {"label": "身份", "value": "旅人"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.assertEqual(presets.list_presets(self.root)[0]["keys"], ["年龄", "身份"])

    def test_delete_removes_directory(self) -> None:
        presets.create_preset(self.root, "待删除", ["年龄"])
        result = presets.delete_preset(self.root, "待删除")
        self.assertTrue(result["deleted"])
        self.assertFalse((self.root / "待删除").exists())
        self.assertEqual(presets.list_presets(self.root), [])

    def test_delete_missing_returns_404(self) -> None:
        with self.assertRaises(worlds.WorldError) as ctx:
            presets.delete_preset(self.root, "不存在")
        self.assertEqual(ctx.exception.status, 404)

    def test_delete_rejects_traversal(self) -> None:
        for bad in ("../x", "a/b", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(worlds.WorldError):
                    presets.delete_preset(self.root, bad)

    def test_update_keys(self) -> None:
        presets.create_preset(self.root, "模板", ["年龄"])
        updated = presets.update_preset(self.root, "模板", keys=["身份", "年龄"])
        self.assertEqual(updated["keys"], ["身份", "年龄"])
        meta = json.loads((self.root / "模板" / "preset.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["keys"], ["身份", "年龄"])

    def test_update_rename(self) -> None:
        presets.create_preset(self.root, "旧名字", ["年龄"])
        updated = presets.update_preset(self.root, "旧名字", new_name="新名字")
        self.assertEqual(updated["name"], "新名字")
        self.assertTrue((self.root / "新名字").is_dir())
        self.assertFalse((self.root / "旧名字").exists())
        self.assertEqual([item["name"] for item in presets.list_presets(self.root)], ["新名字"])
        # 改名后键不丢
        self.assertEqual(updated["keys"], ["年龄"])

    def test_update_rename_conflict(self) -> None:
        presets.create_preset(self.root, "甲")
        presets.create_preset(self.root, "乙")
        with self.assertRaises(worlds.WorldError) as ctx:
            presets.update_preset(self.root, "甲", new_name="乙")
        self.assertEqual(ctx.exception.status, 409)

    def test_update_missing_returns_404(self) -> None:
        with self.assertRaises(worlds.WorldError) as ctx:
            presets.update_preset(self.root, "不存在", keys=[])
        self.assertEqual(ctx.exception.status, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
