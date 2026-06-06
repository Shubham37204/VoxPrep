# exceptions.py — Custom application exceptions
# Using typed exceptions instead of generic ValueError/RuntimeError
# makes error handling explicit and avoids accidental catch-alls.

class VoxPrepError(Exception):
    """Base exception for all VoxPrep application errors."""
    pass


class InvalidStateTransitionError(VoxPrepError):
    """Raised when SessionService is asked to make a disallowed status transition."""
    # Example: attempting COMPLETED → ACTIVE
    pass


class SessionNotFoundError(VoxPrepError):
    """Raised when a session_id does not exist in the database."""
    pass


class UserNotFoundError(VoxPrepError):
    """Raised when a user_id or email does not exist in the database."""
    pass
