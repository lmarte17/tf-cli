import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tinyfish_cli.cli import normalize_argv


class NormalizeArgvTests(unittest.TestCase):
    def test_agent_run_alias_maps_to_sync_run(self) -> None:
        self.assertEqual(
            normalize_argv(["agent", "run", "--url", "https://example.com", "--goal", "x"]),
            ["run", "--url", "https://example.com", "--goal", "x"],
        )

    def test_agent_run_list_alias_maps_to_runs_list(self) -> None:
        self.assertEqual(normalize_argv(["agent", "run", "list"]), ["runs", "list"])

    def test_agent_run_async_alias_maps_to_run_async(self) -> None:
        self.assertEqual(
            normalize_argv(["agent", "run", "async", "--url", "https://example.com", "--goal", "x"]),
            ["run-async", "--url", "https://example.com", "--goal", "x"],
        )
