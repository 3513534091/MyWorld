"""世界管理的单元测试（纯标准库）。

运行：python tests/test_worlds.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from myworld import worlds  # noqa: E402


class ValidateNameTests(unittest.TestCase):
    def test_accepts_normal_names(self) -> None:
        for name in ("第一个世界", "World 1", "世界-2026", "a_b.c"):
            with self.subTest(name=name):
                self.assertEqual(worlds.validate_name(name), name)

    def test_strips_surrounding_space(self) -> None:
        self.assertEqual(worlds.validate_name("  世界  "), "世界")

    def test_rejects_empty(self) -> None:
        for name in ("", "   ", None):
            with self.subTest(name=name):
                with self.assertRaises(worlds.WorldError):
                    worlds.validate_name(name)  # type: ignore[arg-type]

    def test_rejects_path_characters(self) -> None:
        for name in ("../escape", "a/b", "a\\b", "C:world", "a|b", "a*b"):
            with self.subTest(name=name):
                with self.assertRaises(worlds.WorldError):
                    worlds.validate_name(name)

    def test_rejects_windows_reserved(self) -> None:
        for name in ("CON", "nul", "COM1", "lpt9"):
            with self.subTest(name=name):
                with self.assertRaises(worlds.WorldError):
                    worlds.validate_name(name)

    def test_rejects_leading_dot_and_trailing_dot(self) -> None:
        for name in (".hidden", "世界."):
            with self.subTest(name=name):
                with self.assertRaises(worlds.WorldError):
                    worlds.validate_name(name)

    def test_rejects_too_long(self) -> None:
        with self.assertRaises(worlds.WorldError):
            worlds.validate_name("世" * (worlds.NAME_MAX + 1))


class CreateListTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_writes_directory_and_metadata(self) -> None:
        created = worlds.create_world(self.root, "第一个世界")
        directory = self.root / "第一个世界"
        self.assertTrue(directory.is_dir())
        meta = json.loads((directory / "world.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["name"], "第一个世界")
        self.assertEqual(meta["format"], worlds.FORMAT_VERSION)
        self.assertEqual(created["path"], "data/第一个世界")

    def test_duplicate_rejected(self) -> None:
        worlds.create_world(self.root, "世界")
        with self.assertRaises(worlds.WorldError) as ctx:
            worlds.create_world(self.root, "世界")
        self.assertEqual(ctx.exception.status, 409)

    def test_list_sorted_and_metadata_fallback(self) -> None:
        worlds.create_world(self.root, "b世界")
        worlds.create_world(self.root, "A世界")
        (self.root / "手工目录").mkdir()  # 没有 world.json 的目录也要能列出来

        names = [item["name"] for item in worlds.list_worlds(self.root)]
        self.assertEqual(names, ["A世界", "b世界", "手工目录"])
        manual = next(item for item in worlds.list_worlds(self.root) if item["name"] == "手工目录")
        self.assertTrue(manual["created_at"])

    def test_list_ignores_files(self) -> None:
        (self.root / "not-a-world.txt").write_text("x", encoding="utf-8")
        self.assertEqual(worlds.list_worlds(self.root), [])

    def test_world_dir_missing_raises_404(self) -> None:
        with self.assertRaises(worlds.WorldError) as ctx:
            worlds.world_dir(self.root, "不存在的世界")
        self.assertEqual(ctx.exception.status, 404)

    def test_find_thumbnail_defaults_to_none(self) -> None:
        worlds.create_world(self.root, "世界")
        self.assertIsNone(worlds.find_thumbnail(self.root, "世界"))

    def test_find_thumbnail_picks_existing_image(self) -> None:
        worlds.create_world(self.root, "世界")
        (self.root / "世界" / "thumbnail.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        found = worlds.find_thumbnail(self.root, "世界")
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "thumbnail.png")

    def test_find_thumbnail_rejects_traversal(self) -> None:
        with self.assertRaises(worlds.WorldError):
            worlds.find_thumbnail(self.root, "../x")


if __name__ == "__main__":
    unittest.main(verbosity=2)
