"""Viewport and id lookup. Earth-zone entities only."""

from __future__ import annotations

from arelis.earth.entity import LAYER_IDS, Entity


class EntityStore:
    def __init__(self) -> None:
        self._by_id: dict[str, Entity] = {}

    def clear(self) -> None:
        self._by_id.clear()

    def upsert(self, entity: Entity) -> None:
        self._by_id[entity.id] = entity

    def remove(self, entity_id: str) -> None:
        self._by_id.pop(entity_id, None)

    def get(self, entity_id: str) -> Entity | None:
        return self._by_id.get(entity_id)

    def __len__(self) -> int:
        return len(self._by_id)

    def all(self) -> tuple[Entity, ...]:
        return tuple(self._by_id.values())

    def in_layer(self, layer: str) -> tuple[Entity, ...]:
        return tuple(e for e in self._by_id.values() if e.layer == layer)

    def counts(self) -> dict[str, int]:
        out = {lid: 0 for lid in LAYER_IDS}
        for e in self._by_id.values():
            if e.layer in out:
                out[e.layer] += 1
            else:
                out[e.layer] = out.get(e.layer, 0) + 1
        return out
