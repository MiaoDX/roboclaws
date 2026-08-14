"""Failure type shared by household SDK lifecycle owners."""

from roboclaws.agents.live_status import LiveAgentFailure


class LiveAgentRunFailure(RuntimeError):
    """Raised after the SDK runtime writes structured failure status."""

    def __init__(self, message: str, failure: LiveAgentFailure) -> None:
        super().__init__(message)
        self.failure = failure


class CheckerValidationError(RuntimeError):
    """Raised when product artifacts fail the post-run contract checker."""

    def __init__(self, status: int) -> None:
        super().__init__(f"cleanup checker exited with status {status}")
        self.status = status
