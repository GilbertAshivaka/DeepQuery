"""
Deep Query — Agent Model Slots

Provider-agnostic model abstraction for the agent layer. Import the slot enum and
the resolver from here:

    from agents.models import Slot, get_model
    llm = get_model(Slot.ORCHESTRATION)
"""

from agents.models.slots import (
    ModelSlotError,
    Slot,
    clear_model_cache,
    describe_slots,
    get_model,
    probe_model,
)

__all__ = [
    "Slot",
    "get_model",
    "describe_slots",
    "ModelSlotError",
    "clear_model_cache",
    "probe_model",
]
