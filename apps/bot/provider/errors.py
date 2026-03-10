"""Provider error types — distinguish rate limits from other endpoint failures.

Used by the rotation layer in base.py to decide whether to cooldown or just skip.
"""


class RateLimitError(Exception):
    """Raised when an endpoint returns HTTP 429."""

    def __init__(self, retry_after: float = 60.0, message: str = ""):
        self.retry_after = retry_after
        super().__init__(message or f"Rate limited, retry after {retry_after}s")


class EndpointError(Exception):
    """Raised when an endpoint returns a non-success, non-429 response."""

    def __init__(self, status: int, message: str = ""):
        self.status = status
        super().__init__(message or f"Endpoint error: HTTP {status}")
