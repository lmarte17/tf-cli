import sys
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from http.client import RemoteDisconnected

from tinyfish_cli.client import TinyFishClient, parse_sse_lines
from tinyfish_cli.errors import CliError


class ParseSseLinesTests(unittest.TestCase):
    def test_parses_multiple_events(self) -> None:
        raw_lines = [
            b"data: {\"type\":\"STARTED\",\"run_id\":\"run_1\",\"timestamp\":\"2026-01-01T00:00:00Z\"}\n",
            b"\n",
            b"data: {\"type\":\"PROGRESS\",\"run_id\":\"run_1\",\"purpose\":\"Clicking submit\",\"timestamp\":\"2026-01-01T00:00:01Z\"}\n",
            b"\n",
            b"data: {\"type\":\"COMPLETE\",\"run_id\":\"run_1\",\"status\":\"COMPLETED\",\"timestamp\":\"2026-01-01T00:00:02Z\"}\n",
            b"\n",
        ]
        events = list(parse_sse_lines(raw_lines))
        self.assertEqual([event["type"] for event in events], ["STARTED", "PROGRESS", "COMPLETE"])

    def test_ignores_comments(self) -> None:
        raw_lines = [
            b": keep-alive\n",
            b"data: {\"type\":\"HEARTBEAT\",\"timestamp\":\"2026-01-01T00:00:00Z\"}\n",
            b"\n",
        ]
        events = list(parse_sse_lines(raw_lines))
        self.assertEqual(events[0]["type"], "HEARTBEAT")


class RequestErrorTests(unittest.TestCase):
    def test_wraps_remote_disconnected_for_sync_run(self) -> None:
        client = TinyFishClient(base_url="https://agent.tinyfish.ai", api_key="test-key")
        with patch("tinyfish_cli.client.urlopen", side_effect=RemoteDisconnected("Remote end closed connection without response")):
            with self.assertRaises(CliError) as exc_info:
                client.request_json(
                    "POST",
                    "/v1/automation/run",
                    payload={"url": "https://example.com", "goal": "test"},
                )
        exc = exc_info.exception
        self.assertEqual(exc.code, "REMOTE_DISCONNECTED")
        self.assertIn("run-async", exc.message)
