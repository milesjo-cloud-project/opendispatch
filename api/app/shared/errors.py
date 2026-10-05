"""Errors raised by the domain layer. The API layer catches these and turns them into HTTP errors."""


class DomainError(Exception):
    """Base class for every rule the domain enforces."""


class IllegalTransition(DomainError):
    """A job was asked to move to a status its current status can't reach."""

    def __init__(self, current, target):
        super().__init__(f"Cannot move job from '{current.value}' to '{target.value}'")
        self.current = current
        self.target = target


class DomainRuleViolation(DomainError):
    """A transition is allowed in general, but a business rule blocks it right now."""
