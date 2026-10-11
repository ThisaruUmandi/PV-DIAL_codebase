"""Inverter-library routing for SharedInputs (KT §7.4 D6 hardware sharing).

A single physical inverter can be loaded from two databases (CECInverter,
ADRInverter), and SharedInputs.inverter is tagged with exactly one library
(Step 5/6 design constraint). Since a coalition/derived/re-execution config
can land on 'sandia' (needs CECInverter) or 'adr' (needs ADRInverter) for
the same underlying hardware, callers that build both a shared_cec and a
shared_adr variant use shared_inputs_for() to pick the one matching a given
config's ac_model, rather than duplicating this routing per module.
"""

from __future__ import annotations

from pvdials.physics.pipeline import SharedInputs
from pvdials.types import PipelineConfig


def shared_inputs_for(
    config: PipelineConfig, shared_cec: SharedInputs, shared_adr: SharedInputs
) -> SharedInputs:
    """'adr' needs the ADRInverter-tagged SharedInputs; everything else
    (sandia, pvwatts) uses the CEC one.
    """
    return shared_adr if config.ac_model == "adr" else shared_cec
