"""Multi-channel element fusion: spatial match, semantic merge, conflict detection."""


def fuse(channel_results: list[list[dict]]) -> list[dict]:
    """Conflicting matches must be returned as conflict entries, never resolved by guessing."""
    raise NotImplementedError("S1")