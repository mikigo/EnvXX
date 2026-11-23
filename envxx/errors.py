class EnvxxError(Exception):
    """Base class for all user-facing errors."""


class UsageError(EnvxxError):
    pass


class NetworkError(EnvxxError):
    pass


class VersionNotFound(EnvxxError):
    pass


class UnsupportedPlatform(EnvxxError):
    pass


class ChecksumError(EnvxxError):
    pass


class ArchiveError(EnvxxError):
    pass


class InstallError(EnvxxError):
    pass


class SelfUpdateError(EnvxxError):
    pass


class LockTimeout(EnvxxError):
    pass
