from __future__ import annotations

from typing import Any, Dict, Optional


class CliError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "CLI_ERROR",
        exit_code: int = 1,
        details: Any = None,
        status: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.exit_code = exit_code
        self.details = details
        self.status = status

    def to_payload(self) -> Dict[str, Any]:
        error: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.status is not None:
            error["status"] = self.status
        if self.details is not None:
            error["details"] = self.details
        return {"error": error}


class ApiError(CliError):
    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        payload: Optional[Dict[str, Any]] = None,
        code: str = "API_ERROR",
        details: Any = None,
    ) -> None:
        super().__init__(message, code=code, status=status, details=details)
        self.payload = payload

    def to_payload(self) -> Dict[str, Any]:
        if isinstance(self.payload, dict) and isinstance(self.payload.get("error"), dict):
            payload = dict(self.payload)
            error = dict(payload["error"])
            if self.status is not None and "status" not in error:
                error["status"] = self.status
            payload["error"] = error
            return payload
        return super().to_payload()
