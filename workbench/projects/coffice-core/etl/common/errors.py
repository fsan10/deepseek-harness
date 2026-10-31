"""Typed ETL outcomes that preserve strict validation and transaction rollback."""


class SourceNotReady(RuntimeError):
    """A required, verified source has not arrived; no metric may be committed."""
