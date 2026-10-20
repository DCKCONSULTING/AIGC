class MissingAPIKeyError(Exception):
    """Raised when a required provider credential is not configured."""


class ProviderError(Exception):
    """Raised when a provider API call fails."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        code: str = "",
        status_code: int = 0,
        provider: str = "",
        request_id: str = "",
        category: str = "",
        retry_after: str = "",
    ):
        super().__init__(message)
        self.retryable = retryable
        self.code = code
        self.status_code = status_code
        self.provider = provider
        self.request_id = request_id
        self.category = category or ("transient" if retryable else "provider_rejection")
        self.retry_after = retry_after


class GoogleProviderError(ProviderError):
    """Backward-compatible alias for Google provider failures."""


class ProductTruthError(Exception):
    """Raised when generated content violates approved product facts."""
