"""semantic_id -> live element resolution. Relocate on every execution; never reuse cached coordinates."""

from __future__ import annotations

from semantic.element import GUIElement

MIN_CONFIDENCE = 0.5


class ResolveError(RuntimeError):
    code = "resolve_error"


class LocatorMissing(ResolveError):
    code = "locator_missing"


class ResolveConflict(ResolveError):
    code = "conflict"


class IdentityMismatch(ResolveError):
    code = "identity_mismatch"


class Resolver:
    def __init__(self, registry: dict, providers: dict,
                 window_checker=None, min_confidence: float = MIN_CONFIDENCE):
        self.registry = registry
        self.providers = providers
        self.window_checker = window_checker
        self.min_confidence = min_confidence

    async def resolve(self, window_id: str, semantic_id: str) -> GUIElement:
        locator = self.registry.get(semantic_id)
        if locator is None:
            raise LocatorMissing(f"semantic_id not registered: {semantic_id}")

        if self.window_checker is not None:
            try:
                self.window_checker(window_id)
            except IdentityMismatch:
                raise
            except Exception as e:
                raise IdentityMismatch(f"{window_id}: {e}") from e

        attempted = []
        for step in locator.chain:
            if not step:
                continue
            kind = next(iter(step))
            provider = self.providers.get(kind)
            if provider is None:
                attempted.append(f"{kind}: no provider")
                continue
            elements = await provider.find(window_id, step)
            viable = [e for e in elements if e.confidence >= self.min_confidence]
            if len(viable) > 1:
                raise ResolveConflict(
                    f"{semantic_id}: {len(viable)} candidates via {kind}; refusing to guess")
            if len(viable) == 1:
                return viable[0]
            attempted.append(f"{kind}: 0 candidates")

        raise LocatorMissing(f"{semantic_id}: chain exhausted ({'; '.join(attempted) or 'empty chain'})")

    def heal(self, window_id: str, semantic_id: str):
        """Unique verified candidate only; >=2 similar candidates must stop for human confirmation."""
        raise NotImplementedError("S4")