from __future__ import annotations

from http.client import RemoteDisconnected
import json
import socket
from typing import Any, Dict, Iterable, Iterator, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from tinyfish_cli.errors import ApiError, CliError


JSONDict = Dict[str, Any]


def parse_sse_lines(lines: Iterable[bytes]) -> Iterator[Any]:
    data_lines = []
    event_name = None

    for raw_line in lines:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line:
            if not data_lines:
                continue
            payload_text = "\n".join(data_lines)
            try:
                payload = json.loads(payload_text)
            except json.JSONDecodeError:
                payload = {"raw": payload_text}
            if event_name and isinstance(payload, dict) and "event" not in payload:
                payload["event"] = event_name
            yield payload
            data_lines = []
            event_name = None
            continue

        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line.split(":", 1)[1].lstrip()
            continue
        if line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].lstrip())

    if data_lines:
        payload_text = "\n".join(data_lines)
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            payload = {"raw": payload_text}
        if event_name and isinstance(payload, dict) and "event" not in payload:
            payload["event"] = event_name
        yield payload


class TinyFishClient:
    def __init__(self, *, base_url: str, api_key: str, timeout: float = 300.0) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self, *, accept: Optional[str] = None, json_body: bool = False) -> Dict[str, str]:
        headers = {"X-API-Key": self.api_key}
        if accept:
            headers["Accept"] = accept
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _make_url(self, path: str, query: Optional[Dict[str, Any]] = None) -> str:
        url = urljoin(self.base_url, path.lstrip("/"))
        if not query:
            return url
        filtered = {key: value for key, value in query.items() if value is not None}
        if not filtered:
            return url
        return f"{url}?{urlencode(filtered, doseq=True)}"

    def _decode_json(self, body: bytes) -> Any:
        if not body:
            return None
        return json.loads(body.decode("utf-8"))

    def _network_disconnect_error(self, *, method: str, path: str, reason: str) -> CliError:
        message = f"Connection to TinyFish was closed before a response was returned for {method.upper()} {path}."
        details: Dict[str, Any] = {"method": method.upper(), "path": path, "reason": reason}

        if path == "/v1/automation/run":
            message += " The run may still have executed server-side. Check the TinyFish dashboard, and prefer run-async or run-sse for longer jobs."
            details["hint"] = "use_run_async_or_run_sse"

        return CliError(message, code="REMOTE_DISCONNECTED", details=details)

    def _http_error(self, exc: HTTPError) -> ApiError:
        body = exc.read()
        content_type = exc.headers.get("Content-Type", "")
        try:
            payload = self._decode_json(body) if "json" in content_type else None
        except Exception:
            payload = None

        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            error = payload["error"]
            return ApiError(
                error.get("message", f"API request failed with status {exc.code}"),
                status=exc.code,
                payload=payload,
                code=error.get("code", "API_ERROR"),
                details=error.get("details"),
            )

        message = body.decode("utf-8", errors="replace").strip() or f"API request failed with status {exc.code}"
        return ApiError(message, status=exc.code)

    def request_json(
        self,
        method: str,
        path: str,
        *,
        payload: Optional[Any] = None,
        query: Optional[Dict[str, Any]] = None,
        expected_statuses: Tuple[int, ...] = (200,),
    ) -> Any:
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        request = Request(
            self._make_url(path, query),
            data=data,
            headers=self._headers(accept="application/json", json_body=payload is not None),
            method=method.upper(),
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read()
                status = response.getcode()
                parsed = self._decode_json(body)
        except HTTPError as exc:
            body = exc.read()
            try:
                parsed = self._decode_json(body)
            except Exception:
                parsed = None
            if exc.code in expected_statuses:
                return parsed
            if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
                error = parsed["error"]
                raise ApiError(
                    error.get("message", f"API request failed with status {exc.code}"),
                    status=exc.code,
                    payload=parsed,
                    code=error.get("code", "API_ERROR"),
                    details=error.get("details"),
                ) from exc
            message = (
                body.decode("utf-8", errors="replace").strip()
                or f"API request failed with status {exc.code}"
            )
            raise ApiError(message, status=exc.code, details=parsed) from exc
        except (RemoteDisconnected, ConnectionResetError, socket.timeout, TimeoutError) as exc:
            raise self._network_disconnect_error(
                method=method,
                path=path,
                reason=str(exc),
            ) from exc
        except URLError as exc:
            raise CliError(
                f"Failed to connect to TinyFish: {exc.reason}",
                code="NETWORK_ERROR",
                details={"reason": str(exc.reason)},
            ) from exc

        if status not in expected_statuses:
            raise ApiError(
                f"Unexpected TinyFish status code: {status}",
                status=status,
                details=parsed,
            )
        return parsed

    def stream_sse(self, path: str, *, payload: JSONDict) -> Iterator[Any]:
        request = Request(
            self._make_url(path),
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(accept="text/event-stream", json_body=True),
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                content_type = response.headers.get("Content-Type", "")
                if "text/event-stream" not in content_type:
                    body = response.read()
                    try:
                        parsed = self._decode_json(body)
                    except Exception:
                        parsed = {"body": body.decode("utf-8", errors="replace")}
                    raise ApiError(
                        "TinyFish did not return an SSE stream",
                        status=response.getcode(),
                        details=parsed,
                    )
                for event in parse_sse_lines(iter(response.readline, b"")):
                    yield event
        except HTTPError as exc:
            raise self._http_error(exc) from exc
        except (RemoteDisconnected, ConnectionResetError, socket.timeout, TimeoutError) as exc:
            raise self._network_disconnect_error(
                method="POST",
                path=path,
                reason=str(exc),
            ) from exc
        except URLError as exc:
            raise CliError(
                f"Failed to connect to TinyFish: {exc.reason}",
                code="NETWORK_ERROR",
                details={"reason": str(exc.reason)},
            ) from exc
