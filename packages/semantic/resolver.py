"""semantic_id -> live element resolution. Relocate on every execution; never reuse cached coordinates."""

from __future__ import annotations

from semantic.element import GUIElement
from semantic.heal import (
    HealAmbiguous,
    HealError,
    HealResult,
    build_locator,
    build_proposed_chain,
    extract_hints,
    match_candidates,
)

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
                 window_checker=None, min_confidence: float = MIN_CONFIDENCE,
                 scanner=None, verifier=None, patch_writer=None, app: str | None = None):
        self.registry = registry
        self.providers = providers
        self.window_checker = window_checker
        self.min_confidence = min_confidence
        self.scanner = scanner
        self.verifier = verifier
        self.patch_writer = patch_writer
        self.app = app

    def _check_window(self, window_id: str) -> None:
        if self.window_checker is None:
            return
        try:
            self.window_checker(window_id)
        except IdentityMismatch:
            raise
        except Exception as e:
            raise IdentityMismatch(f"{window_id}: {e}") from e

    async def resolve(self, window_id: str, semantic_id: str) -> GUIElement:
        locator = self.registry.get(semantic_id)
        if locator is None:
            raise LocatorMissing(f"semantic_id not registered: {semantic_id}")

        if self.window_checker is not None:
            self._check_window(window_id)

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

    async def heal(self, window_id: str, semantic_id: str,
                   expected_role: str | None = None) -> HealResult:
        """Rescan, match by old-chain hints, verify uniqueness, propose a pending patch.

        The registry is never mutated here; >=2 similar candidates stop with HealAmbiguous
        (code 'conflict') and no patch file is written.
        """
        locator = self.registry.get(semantic_id)
        if locator is None:
            raise LocatorMissing(f"semantic_id not registered: {semantic_id}")
        self._check_window(window_id)
        if self.scanner is None:
            raise HealError(f"{semantic_id}: heal scanner not configured")

        elements = await self.scanner(window_id)
        hints = extract_hints(locator.chain)
        candidates = match_candidates(elements, hints, expected_role)
        if not candidates:
            raise HealError(f"{semantic_id}: no candidate after rescan")
        if len(candidates) > 1:
            desc = "; ".join(f"{c.role}:{c.name}@{c.bounds}" for c in candidates[:4])
            raise HealAmbiguous(
                f"{semantic_id}: {len(candidates)} candidates after rescan; refusing to guess ({desc})")

        element = candidates[0]
        verified = False
        if self.verifier is not None:
            verified = bool(await self.verifier(window_id, element))
            if not verified:
                raise HealError(f"{semantic_id}: candidate {element.id} failed verification")

        proposed = build_proposed_chain(element, hints)
        patch_path = None
        if self.patch_writer is not None:
            patch_path = self.patch_writer(
                self.app or "", locator.app_version,
                build_locator(locator, proposed), list(locator.chain))
        return HealResult(
            semantic_id=semantic_id, element=element, previous_chain=list(locator.chain),
            proposed_chain=proposed, verification=locator.verification,
            patch_path=patch_path, verified=verified,
        )