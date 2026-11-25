"""角色管理的单元测试（纯标准库）。

运行：python tests/test_characters.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from myworld import characters, worlds  # noqa: E402


class CharacterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.worlds_root = Path(self.tmp.name) / "data"
        self.worlds_root.mkdir()
        worlds.create_world(self.worlds_root, "山与海")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_and_list(self) -> None:
        created = characters.create_character(self.worlds_root, "山与海", "阿澈")
        self.assertEqual(created["path"], "data/山与海/role/阿澈")

        meta_path = self.worlds_root / "山与海" / "role" / "阿澈" / "character.json"
        self.assertTrue(meta_path.is_file())
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(meta["name"], "阿澈")
        self.assertEqual(meta["format"], characters.FORMAT_VERSION)

        names = [item["name"] for item in characters.list_characters(self.worlds_root, "山与海")]
        self.assertEqual(names, ["阿澈"])

    def test_duplicate_rejected(self) -> None:
        characters.create_character(self.worlds_root, "山与海", "阿澈")
        with self.assertRaises(worlds.WorldError) as ctx:
            characters.create_character(self.worlds_root, "山与海", "阿澈")
        self.assertEqual(ctx.exception.status, 409)

    def test_name_rules_shared(self) -> None:
        for bad in ("", "../x", "a/b", "CON", ".hidden"):
            with self.subTest(bad=bad):
                with self.assertRaises(worlds.WorldError):
                    characters.create_character(self.worlds_root, "山与海", bad)

    def test_missing_world_raises_404(self) -> None:
        with self.assertRaises(worlds.WorldError) as ctx:
            characters.list_characters(self.worlds_root, "不存在的世界")
        self.assertEqual(ctx.exception.status, 404)

    def test_portrait_default_none_then_saved(self) -> None:
        characters.create_character(self.worlds_root, "山与海", "阿澈")
        self.assertIsNone(characters.find_portrait(self.worlds_root, "山与海", "阿澈"))

        target = characters.save_portrait(self.worlds_root, "山与海", "阿澈", b"\x89PNG\r\n\x1a\n", ".png")
        self.assertEqual(target.name, "portrait.png")
        found = characters.find_portrait(self.worlds_root, "山与海", "阿澈")
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "portrait.png")

    def test_missing_character_portrait_404(self) -> None:
        with self.assertRaises(worlds.WorldError) as ctx:
            characters.find_portrait(self.worlds_root, "山与海", "阿澈")
        self.assertEqual(ctx.exception.status, 404)

    def test_delete_removes_character(self) -> None:
        characters.create_character(self.worlds_root, "山与海", "阿澈")
        result = characters.delete_character(self.worlds_root, "山与海", "阿澈")
        self.assertTrue(result["deleted"])
        self.assertFalse((self.worlds_root / "山与海" / "role" / "阿澈").exists())
        self.assertEqual(characters.list_characters(self.worlds_root, "山与海"), [])

    def test_delete_missing_character_404(self) -> None:
        with self.assertRaises(worlds.WorldError) as ctx:
            characters.delete_character(self.worlds_root, "山与海", "阿澈")
        self.assertEqual(ctx.exception.status, 404)

    def test_delete_rejects_traversal(self) -> None:
        for bad in ("../x", "a/b", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(worlds.WorldError):
                    characters.delete_character(self.worlds_root, "山与海", bad)

    def test_order_is_saved_and_listed(self) -> None:
        for name in ("甲", "乙", "丙"):
            characters.create_character(self.worlds_root, "山与海", name)

        # 没保存顺序时按名字（码位）排序：丙 < 乙 < 甲
        names = [item["name"] for item in characters.list_characters(self.worlds_root, "山与海")]
        self.assertEqual(names, ["丙", "乙", "甲"])

        saved = characters.save_order(self.worlds_root, "山与海", ["甲", "丙", "乙"])
        self.assertEqual(saved["order"], ["甲", "丙", "乙"])

        names = [item["name"] for item in characters.list_characters(self.worlds_root, "山与海")]
        self.assertEqual(names, ["甲", "丙", "乙"])

    def test_order_ignores_unknown_and_dedupes(self) -> None:
        characters.create_character(self.worlds_root, "山与海", "阿澈")
        characters.create_character(self.worlds_root, "山与海", "小满")

        saved = characters.save_order(self.worlds_root, "山与海", ["小满", "不存在", "小满"])
        # 未知的忽略、重复的去重、没提到的补在末尾
        self.assertEqual(saved["order"], ["小满", "阿澈"])

    def test_order_rejects_invalid_name(self) -> None:
        with self.assertRaises(worlds.WorldError):
            characters.save_order(self.worlds_root, "山与海", ["../x"])

    def test_read_and_update_attributes(self) -> None:
        characters.create_character(self.worlds_root, "山与海", "阿澈")
        detail = characters.read_character(self.worlds_root, "山与海", "阿澈")
        self.assertEqual(detail["attributes"], [])

        updated = characters.update_character(
            self.worlds_root,
            "山与海",
            "阿澈",
            attributes=[
                {"label": "年龄", "value": "17"},
                {"label": "", "value": ""},
                {"label": "身份", "value": "旅人"},
            ],
        )
        self.assertEqual([item["label"] for item in updated["attributes"]], ["年龄", "身份"])

        again = characters.read_character(self.worlds_root, "山与海", "阿澈")
        self.assertEqual(len(again["attributes"]), 2)
        self.assertEqual(again["attributes"][1]["value"], "旅人")

    def test_rename_character_keeps_order(self) -> None:
        characters.create_character(self.worlds_root, "山与海", "阿澈")
        characters.save_order(self.worlds_root, "山与海", ["阿澈"])

        updated = characters.update_character(self.worlds_root, "山与海", "阿澈", new_name="白鹭")
        self.assertEqual(updated["name"], "白鹭")
        self.assertTrue((self.worlds_root / "山与海" / "role" / "白鹭").is_dir())
        self.assertFalse((self.worlds_root / "山与海" / "role" / "阿澈").exists())

        names = [item["name"] for item in characters.list_characters(self.worlds_root, "山与海")]
        self.assertEqual(names, ["白鹭"])

    def test_delete_portrait_restores_default(self) -> None:
        characters.create_character(self.worlds_root, "山与海", "阿澈")
        path = characters.save_portrait(self.worlds_root, "山与海", "阿澈", b"fake-image", ".jpg")
        self.assertTrue(path.is_file())

        result = characters.delete_portrait(self.worlds_root, "山与海", "阿澈")
        self.assertEqual(result["removed"], ["portrait.jpg"])
        self.assertFalse(path.exists())

        # 再删一次是幂等的，不报错
        again = characters.delete_portrait(self.worlds_root, "山与海", "阿澈")
        self.assertEqual(again["removed"], [])

    def test_rename_conflict(self) -> None:
        characters.create_character(self.worlds_root, "山与海", "阿澈")
        characters.create_character(self.worlds_root, "山与海", "小满")
        with self.assertRaises(worlds.WorldError) as ctx:
            characters.update_character(self.worlds_root, "山与海", "阿澈", new_name="小满")
        self.assertEqual(ctx.exception.status, 409)

    def test_characters_stay_inside_world(self) -> None:
        characters.create_character(self.worlds_root, "山与海", "阿澈")
        # 角色目录应该在世界的 role/ 下，而不是散落在别处
        base = self.worlds_root / "山与海"
        entries = {p.name for p in base.iterdir()}
        self.assertEqual(entries, {"world.json", "role"})

    def test_legacy_characters_dir_is_migrated(self) -> None:
        legacy = self.worlds_root / "山与海" / "characters"
        (legacy / "旧角色").mkdir(parents=True)
        (legacy / "旧角色" / "character.json").write_text('{"name": "旧角色"}', encoding="utf-8")

        names = [item["name"] for item in characters.list_characters(self.worlds_root, "山与海")]
        self.assertEqual(names, ["旧角色"])
        self.assertFalse(legacy.exists())
        self.assertTrue((self.worlds_root / "山与海" / "role" / "旧角色").is_dir())


if __name__ == "__main__":
    unittest.main(verbosity=2)
