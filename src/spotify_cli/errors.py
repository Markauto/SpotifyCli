"""Exception types used throughout the CLI, each carrying its own process exit code.

Agents invoking this CLI can branch on exit code alone without parsing text:
  0 = success
  1 = generic/unexpected error
  2 = requested resource not found (playlist, track, device, ...)
  3 = ambiguous match — see the `candidates` field in --json output
  4 = not authenticated / re-auth required
  5 = Spotify API error (rate limit exhausted, premium required, no active device, ...)
"""


class ExitCode:
    OK = 0
    ERROR = 1
    NOT_FOUND = 2
    AMBIGUOUS = 3
    AUTH_REQUIRED = 4
    API_ERROR = 5


class SpotifyCliError(Exception):
    """Base class for all errors this CLI raises deliberately."""

    exit_code = ExitCode.ERROR

    def __init__(self, message: str, **extra):
        super().__init__(message)
        self.message = message
        self.extra = extra


class ConfigError(SpotifyCliError):
    exit_code = ExitCode.ERROR


class AuthError(SpotifyCliError):
    exit_code = ExitCode.AUTH_REQUIRED


class AuthRequiredError(SpotifyCliError):
    exit_code = ExitCode.AUTH_REQUIRED


class NotFoundError(SpotifyCliError):
    exit_code = ExitCode.NOT_FOUND


class AmbiguousMatchError(SpotifyCliError):
    exit_code = ExitCode.AMBIGUOUS

    def __init__(self, message: str, candidates: list):
        super().__init__(message, candidates=candidates)
        self.candidates = candidates


class ApiError(SpotifyCliError):
    exit_code = ExitCode.API_ERROR

    def __init__(self, message: str, status_code: int | None = None, response_body: str | None = None):
        super().__init__(message, status_code=status_code)
        self.status_code = status_code
        self.response_body = response_body
