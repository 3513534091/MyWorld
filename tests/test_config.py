"""配置解析单元测试（只用标准库）。

运行：python tests/test_config.py
"""

from __future__ import annotations

import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from myworld.config import (  # noqa: E402
    DEFAULT_HOST,
    DEFAULT_PORT,
    ConfigError,
    find_free_port,
    is_port_free,
    resolve,
)


def occupy(host: str = "127.0.0.1") -> socket.socket:
    """占住一个随机端口，返回仍处于监听状态的 socket。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((host, 0))
    sock.listen(1)
    return sock


class ResolveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_defaults(self) -> None:
        settings = resolve(cwd=self.cwd, env={})
        self.assertEqual(settings.host, DEFAULT_HOST)
        self.assertEqual(settings.port, DEFAULT_PORT)
        self.assertEqual(settings.sources["port"], "default")
        self.assertFalse(settings.port_shifted)

    def test_env_overrides_default(self) -> None:
        settings = resolve(cwd=self.cwd, env={"MYWORLD_HOST": "0.0.0.0", "MYWORLD_PORT": "9100"})
        self.assertEqual(settings.host, "0.0.0.0")
        self.assertEqual(settings.port, 9100)
        self.assertEqual(settings.sources["port"], "env:MYWORLD_PORT")

    def test_cli_overrides_env(self) -> None:
        settings = resolve(
            cwd=self.cwd,
            env={"MYWORLD_PORT": "9100"},
            cli={"port": 9200},
        )
        self.assertEqual(settings.port, 9200)
        self.assertEqual(settings.sources["port"], "cli")

    def test_file_overrides_default_but_not_env(self) -> None:
        (self.cwd / "myworld.config.json").write_text(
            json.dumps({"port": 9300, "host": "127.0.0.1"}), encoding="utf-8"
        )
        from_file = resolve(cwd=self.cwd, env={})
        self.assertEqual(from_file.port, 9300)
        self.assertEqual(from_file.sources["port"], "file:myworld.config.json")

        from_env = resolve(cwd=self.cwd, env={"MYWORLD_PORT": "9400"})
        self.assertEqual(from_env.port, 9400)

    def test_invalid_port_rejected(self) -> None:
        for bad in (0, 70000, "abc"):
            with self.subTest(bad=bad):
                with self.assertRaises(ConfigError):
                    resolve(cwd=self.cwd, env={}, cli={"port": bad})

    def test_broken_json_rejected(self) -> None:
        (self.cwd / "myworld.config.json").write_text("{ nope", encoding="utf-8")
        with self.assertRaises(ConfigError):
            resolve(cwd=self.cwd, env={})

    def test_occupied_port_shifts(self) -> None:
        sock = occupy()
        try:
            busy = sock.getsockname()[1]
            settings = resolve(cwd=self.cwd, env={}, cli={"port": busy})
            self.assertTrue(settings.port_shifted)
            self.assertEqual(settings.requested_port, busy)
            self.assertNotEqual(settings.port, busy)
            self.assertTrue(is_port_free("127.0.0.1", settings.port))
            self.assertIn("+auto-shift", settings.sources["port"])
        finally:
            sock.close()

    def test_strict_port_raises(self) -> None:
        sock = occupy()
        try:
            busy = sock.getsockname()[1]
            with self.assertRaises(ConfigError):
                resolve(cwd=self.cwd, env={}, cli={"port": busy, "strict_port": True})
        finally:
            sock.close()

    def test_find_free_port_respects_limit(self) -> None:
        sock = occupy()
        try:
            busy = sock.getsockname()[1]
            # limit=1 时只允许探测 busy 本身，而它被占用，因此必须是 None
            self.assertIsNone(find_free_port("127.0.0.1", busy, limit=1))
        finally:
            sock.close()

    def test_data_dir_defaults_to_none(self) -> None:
        self.assertIsNone(resolve(cwd=self.cwd, env={}).data_dir)

    def test_data_dir_from_env(self) -> None:
        target = self.cwd / "worlds"
        settings = resolve(cwd=self.cwd, env={"MYWORLD_DATA_DIR": str(target)})
        self.assertEqual(settings.data_dir, str(target))


if __name__ == "__main__":
    unittest.main(verbosity=2)
