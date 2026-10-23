"""Domain errors. The FastAPI layer maps these to HTTP responses."""


class AgentrumError(Exception):
    """Base class for domain errors."""


class NotFoundError(AgentrumError):
    pass


class PermissionDeniedError(AgentrumError):
    pass


class ConflictError(AgentrumError):
    pass


class ValidationError(AgentrumError):
    pass
