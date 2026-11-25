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
        self.assertEqual(created["path"], "data/山与海/characters/阿澈")

        meta_path = self.worlds_root / "山与海" / "characters" / "阿澈" / "character.json"
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

    def test_characters_stay_inside_world(self) -> None:
        characters.create_character(self.worlds_root, "山与海", "阿澈")
        # 角色目录应该在世界的 characters/ 下，而不是散落在别处
        base = self.worlds_root / "山与海"
        entries = {p.name for p in base.iterdir()}
        self.assertEqual(entries, {"world.json", "characters"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
