"""Boundary values shared by Brain's domain services."""

from dataclasses import dataclass


OPERATIONS = frozenset(
    {
        "read",
        "import",
        "propose",
        "review",
        "record_outcome",
        "verify_outcome",
        "manage_access",
        "delete",
        "export",
        "restore",
    }
)


class BrainError(Exception):
    """A stable, sanitized domain failure suitable for transport translation."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def bounded_text(value: str, *, maximum: int = 256) -> str:
    """Validate without normalizing exact identifiers or echoing private input."""
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise BrainError("invalid_input", "Expected bounded nonempty text.")
    return value


def _grants(value, *, operations: bool = False) -> frozenset[str] | None:
    if value is None:
        return None
    if not isinstance(value, (set, frozenset, list, tuple)):
        raise BrainError("invalid_input", "Invalid principal grant.")
    result = frozenset(bounded_text(item) for item in value)
    if operations and not result <= OPERATIONS:
        raise BrainError("invalid_input", "Invalid principal grant.")
    return result


@dataclass(frozen=True)
class Principal:
    """Trusted in-process identity, never accepted from an untrusted payload.

    Token restrictions only narrow live membership and source permissions.
    Mutable input collections are copied so callers cannot widen a grant later.
    """

    identity: str
    kind: str = "human"
    brain_ids: frozenset[str] | None = None
    operations: frozenset[str] | None = None

    def __post_init__(self):
        bounded_text(self.identity)
        if self.kind not in ("human", "agent"):
            raise BrainError("invalid_input", "Invalid principal kind.")
        object.__setattr__(self, "brain_ids", _grants(self.brain_ids))
        object.__setattr__(
            self, "operations", _grants(self.operations, operations=True)
        )
        if self.kind == "agent" and (not self.brain_ids or not self.operations):
            raise BrainError(
                "invalid_input", "Agent grants must be explicit and nonempty."
            )
