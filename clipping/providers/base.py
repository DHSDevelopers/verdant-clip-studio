"""Provider errors."""


class ProviderConfigError(ValueError):
    """The operator configuration for a provider is unusable."""


class InvalidOutputError(ValueError):
    """The provider returned output that violates the clip contract."""
