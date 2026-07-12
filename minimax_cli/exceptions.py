"""Exception types used across minimax_cli."""


class MiniMaxError(Exception):
    """Base class for all minimax_cli errors."""


class AuthenticationError(MiniMaxError):
    """Raised when the API key is missing, invalid, or the region is wrong
    (typically surfaces as HTTP 401 from the upstream)."""


class QuotaExceededError(MiniMaxError):
    """Raised when the Token Plan quota is exhausted."""


class APIError(MiniMaxError):
    """Raised for non-2xx HTTP responses."""

    def __init__(self, status_code: int, message: str, payload: dict | None = None):
        super().__init__(f"[{status_code}] {message}")
        self.status_code = status_code
        self.message = message
        self.payload = payload or {}


class ValidationError(MiniMaxError):
    """Raised when client-side validation of arguments fails."""


class FileTooLargeError(APIError):
    """Raised when an upload exceeds the platform limit."""


class NetworkError(MiniMaxError):
    """Raised on transport-level failures (DNS, connection, timeout)."""
