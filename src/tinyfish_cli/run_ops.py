from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

from tinyfish_cli.client import TinyFishClient
from tinyfish_cli.errors import CliError


TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}


def poll_run_until_terminal(
    client: TinyFishClient,
    run_id: str,
    *,
    interval: float,
    wait_timeout: float,
    on_poll: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    deadline = time.monotonic() + wait_timeout

    while True:
        response = client.request_json("GET", f"/v1/runs/{run_id}")
        if on_poll is not None:
            on_poll(response)

        status = response.get("status")
        if status in TERMINAL_STATUSES:
            return response

        if time.monotonic() >= deadline:
            raise CliError(
                f"Timed out waiting for run {run_id}",
                code="WAIT_TIMEOUT",
                details={"run_id": run_id, "last_status": status},
            )
        time.sleep(interval)
