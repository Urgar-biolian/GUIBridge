"""Bridge a heal proposal into the event store so the REST heal-review endpoint has rows.

resolver.heal already writes an audited patch FILE via LocatorCache.propose_heal_patch
and stops on ambiguity before any writer runs. This recorder additionally registers the
same proposal as a pending store.heal_patches row (schema.sql), keyed by the file's
patch_id, so desktop-agent's POST /locators/{semantic_id}/heal-review can approve/reject
it. Additive: does not mutate the registry, the frozen resolver/heal/cache, or the store.
"""

from __future__ import annotations

from pathlib import Path


def recording_patch_writer(cache, store):
    """Return a resolver patch_writer that writes the audit file AND registers a store row."""
    def write(app: str, app_version: str, locator, previous_chain=None) -> str:
        path = cache.propose_heal_patch(app, app_version, locator, previous_chain)
        patch_id = Path(path).stem
        store.register_heal_patch(patch_id, locator.semantic_id, app, app_version,
                                  list(locator.chain))
        return path
    return write