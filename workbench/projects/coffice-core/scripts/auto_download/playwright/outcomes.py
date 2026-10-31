"""Recoverable automation outcomes; never include verification answers."""


class NeedsHumanError(RuntimeError):
    requires_human = True


class NeedsHumanTimeout(TimeoutError):
    requires_human = True
