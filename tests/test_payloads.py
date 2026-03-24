import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tinyfish_cli.cli import build_batch_run_payload, build_single_run_payload, resolve_run_ids


class PayloadTests(unittest.TestCase):
    def test_single_run_payload_merges_flags_with_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "run.json"
            input_path.write_text(
                """
                {
                  "url": "https://example.com",
                  "goal": "Extract data",
                  "feature_flags": {
                    "enable_agent_memory": false
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            args = Namespace(
                input=str(input_path),
                url=None,
                goal=None,
                browser_profile="stealth",
                proxy_enabled=None,
                proxy_country="US",
                api_integration="openclaw",
                enable_agent_memory=True,
                use_vault=None,
                credential_item_ids=["item_123"],
            )
            payload = build_single_run_payload(args)
            self.assertEqual(payload["browser_profile"], "stealth")
            self.assertEqual(payload["proxy_config"]["enabled"], True)
            self.assertEqual(payload["proxy_config"]["country_code"], "US")
            self.assertEqual(payload["feature_flags"]["enable_agent_memory"], True)
            self.assertEqual(payload["use_vault"], True)
            self.assertEqual(payload["credential_item_ids"], ["item_123"])

    def test_batch_run_payload_accepts_array(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "batch.json"
            input_path.write_text(
                '[{"url":"https://example.com","goal":"Extract title"}]',
                encoding="utf-8",
            )
            payload = build_batch_run_payload(Namespace(input=str(input_path)))
            self.assertEqual(len(payload["runs"]), 1)

    def test_resolve_run_ids_accepts_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "run_ids.json"
            input_path.write_text('{"run_ids":["run_1","run_2"]}', encoding="utf-8")
            run_ids = resolve_run_ids(Namespace(run_ids=[], input=str(input_path)))
            self.assertEqual(run_ids, ["run_1", "run_2"])
