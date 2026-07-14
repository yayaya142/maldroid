"""Application-specific exceptions with user-safe messages."""


class MalDroidError(Exception):
    """Base class for expected MalDroid failures."""


class ConfigurationError(MalDroidError):
    """Raised when configuration is missing or unsafe."""


class CaseError(MalDroidError):
    """Raised for invalid case operations."""


class SecurityError(MalDroidError):
    """Raised when a security boundary would be crossed."""


class ToolExecutionError(MalDroidError):
    """Raised for controlled tool execution failures."""


class ServerError(MalDroidError):
    """Raised when llama-server cannot be managed safely."""
