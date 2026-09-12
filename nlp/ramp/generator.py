"""Compatibility module for the evidence-first Ramp planner.

Ramp intelligence now lives in :mod:`ramp.generator_v2` and is deliberately
not implemented by the historical module-first generator.
"""

from .generator_v2 import RampPlanner

__all__ = ["RampPlanner"]
