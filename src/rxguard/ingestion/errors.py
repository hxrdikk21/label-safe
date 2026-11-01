"""
Failure states shared by every external source adapter.
Callers must distinguish a genuine "not found" from an upstream outage:
only the former may be negatively cached, and neither may be read as "safe".
"""


class SourceAdapterError(Exception):
    """Base class for external source adapter failures."""

    def __init__(self, source: str, message: str) -> None:
        super().__init__(f"[{source}] {message}")
        self.source = source


class UpstreamNotFoundError(SourceAdapterError):
    """The upstream source answered authoritatively that the entity does not exist."""


class UpstreamUnavailableError(SourceAdapterError):
    """The upstream source failed (5xx, 429 after retries, timeout, or malformed payload)."""
