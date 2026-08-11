"""HTTP adapter for the frozen NationLabs Proposal Builder.

The adapter consumes the builder's existing session-authenticated API without
changing or copying its implementation.  ``httpx`` is imported lazily so the
contract can be unit-tested with an injected session in an offline environment.
"""
from typing import Any

from .schemas import QuoteContractError, QuoteExtractionResult


class BuilderError(RuntimeError):
    code = "BUILDER_ERROR"

    def __init__(self, message: str, *, http_status: int | None = None, details: Any = None):
        super().__init__(message)
        self.http_status = http_status
        self.details = details


class BuilderAuthError(BuilderError):
    code = "BUILDER_AUTH_FAILED"


class BuilderUnavailableError(BuilderError):
    code = "BUILDER_UNAVAILABLE"


class BuilderQuoteRejected(BuilderError):
    def __init__(
        self,
        message: str,
        *,
        rejection_code: str = "QUOTE_REJECTED",
        http_status: int | None = None,
        details: Any = None,
    ):
        super().__init__(message, http_status=http_status, details=details)
        self.code = rejection_code


class ProposalBuilderClient:
    """Small session-owning client for ``/api/extract-quote``."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        timeout_s: float = 120.0,
        session: Any = None,
    ):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.username = username
        self.password = password
        self.timeout_s = timeout_s
        if session is None:
            import httpx

            session = httpx.Client(timeout=timeout_s)
        self.session = session
        self._authenticated = False

    @staticmethod
    def _json(response: Any) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception as exc:
            raise BuilderUnavailableError(
                "Proposal Builder returned a non-JSON response",
                http_status=getattr(response, "status_code", None),
            ) from exc
        if not isinstance(payload, dict):
            raise BuilderUnavailableError(
                "Proposal Builder returned a non-object response",
                http_status=getattr(response, "status_code", None),
            )
        return payload

    def health(self) -> dict[str, Any]:
        if not self.base_url:
            raise BuilderUnavailableError("Proposal Builder URL is not configured")
        try:
            response = self.session.get(f"{self.base_url}/api/env", timeout=self.timeout_s)
        except Exception as exc:
            raise BuilderUnavailableError(f"Proposal Builder health check failed: {exc}") from exc
        payload = self._json(response)
        if response.status_code >= 400:
            raise BuilderUnavailableError(
                payload.get("error") or "Proposal Builder health check failed",
                http_status=response.status_code,
                details=payload,
            )
        return {"status": "ok", "environment": payload.get("env", "unknown")}

    def _login(self) -> None:
        if not self.base_url:
            raise BuilderUnavailableError("Proposal Builder URL is not configured")
        if not self.username or not self.password:
            raise BuilderAuthError("Proposal Builder service credentials are not configured")
        try:
            response = self.session.post(
                f"{self.base_url}/api/login",
                json={"username": self.username, "password": self.password},
                timeout=self.timeout_s,
            )
        except Exception as exc:
            raise BuilderUnavailableError(f"Proposal Builder login failed: {exc}") from exc
        payload = self._json(response)
        if response.status_code in (401, 403):
            raise BuilderAuthError(
                payload.get("error") or "Proposal Builder rejected service credentials",
                http_status=response.status_code,
                details=payload,
            )
        if response.status_code >= 400 or payload.get("ok") is not True:
            raise BuilderUnavailableError(
                payload.get("error") or "Proposal Builder login failed",
                http_status=response.status_code,
                details=payload,
            )
        self._authenticated = True

    def extract_quote(
        self,
        content: bytes,
        filename: str,
        content_type: str | None = None,
    ) -> QuoteExtractionResult:
        if not self._authenticated:
            self._login()
        try:
            response = self.session.post(
                f"{self.base_url}/api/extract-quote",
                files={"file": (filename, content, content_type or "application/octet-stream")},
                timeout=self.timeout_s,
            )
        except Exception as exc:
            raise BuilderUnavailableError(f"Proposal Builder quote extraction failed: {exc}") from exc
        payload = self._json(response)
        if response.status_code in (401, 403):
            self._authenticated = False
            raise BuilderAuthError(
                payload.get("error") or "Proposal Builder session was rejected",
                http_status=response.status_code,
                details=payload,
            )
        if response.status_code >= 500:
            raise BuilderUnavailableError(
                payload.get("error") or "Proposal Builder failed during quote extraction",
                http_status=response.status_code,
                details=payload,
            )
        if response.status_code >= 400 or payload.get("ok") is not True:
            raise BuilderQuoteRejected(
                payload.get("error") or "Proposal Builder requires human review",
                rejection_code=str(payload.get("code") or "QUOTE_REJECTED"),
                http_status=response.status_code,
                details=payload,
            )
        try:
            return QuoteExtractionResult.from_builder(payload)
        except QuoteContractError as exc:
            raise BuilderQuoteRejected(
                str(exc),
                rejection_code="BUILDER_CONTRACT_INVALID",
                http_status=response.status_code,
                details=payload,
            ) from exc

    def close(self) -> None:
        close = getattr(self.session, "close", None)
        if close:
            close()
