"""semantic_id -> live element resolution. Relocate on every execution; never reuse cached coordinates."""

from semantic.element import GUIElement, Locator


class Resolver:
    def __init__(self, registry: dict[str, Locator]):
        self.registry = registry

    def resolve(self, window_id: str, semantic_id: str) -> GUIElement:
        raise NotImplementedError("S1")

    def heal(self, window_id: str, semantic_id: str) -> Locator | None:
        """Unique verified candidate only; >=2 similar candidates must stop for human confirmation."""
        raise NotImplementedError("S4")