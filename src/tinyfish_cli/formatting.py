from __future__ import annotations

import json
import sys
from typing import Any, TextIO


def emit_json(data: Any, *, pretty: bool = False, stream: TextIO = sys.stdout) -> None:
    if pretty:
        json.dump(data, stream, indent=2)
    else:
        json.dump(data, stream, separators=(",", ":"))
    stream.write("\n")
    stream.flush()


def emit_pretty_sse_event(event: Any, *, show_heartbeats: bool = False, stream: TextIO = sys.stdout) -> None:
    if not isinstance(event, dict):
        emit_json(event, pretty=True, stream=stream)
        return

    event_type = event.get("type", "UNKNOWN")
    if event_type == "HEARTBEAT" and not show_heartbeats:
        return

    if event_type == "STARTED":
        stream.write(f"[started] run_id={event.get('run_id')} timestamp={event.get('timestamp')}\n")
    elif event_type == "STREAMING_URL":
        stream.write(f"[live] {event.get('streaming_url')}\n")
    elif event_type == "PROGRESS":
        stream.write(f"[progress] {event.get('purpose')}\n")
    elif event_type == "HEARTBEAT":
        stream.write(f"[heartbeat] {event.get('timestamp')}\n")
    elif event_type == "COMPLETE":
        stream.write(f"[complete] status={event.get('status')} run_id={event.get('run_id')}\n")
        emit_json(event, pretty=True, stream=stream)
        return
    else:
        emit_json(event, pretty=True, stream=stream)
        return

    stream.flush()
