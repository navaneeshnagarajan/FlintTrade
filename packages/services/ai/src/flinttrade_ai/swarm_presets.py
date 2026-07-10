"""Compatibility exports for the legacy swarm preset API.

The canonical dataclasses, registry, and raw catalogue live in
``flinttrade_ai._team_presets``.  These aliases keep existing imports working
without maintaining a second copy of the preset definitions.
"""

from __future__ import annotations

from ._team_presets import (
    TeamPreset as SwarmPreset,
    TeamPresetAgent as SwarmAgentDef,
    get_all_presets,
    get_preset,
    list_presets,
)

__all__ = [
    "SwarmAgentDef",
    "SwarmPreset",
    "get_all_presets",
    "get_preset",
    "list_presets",
]
