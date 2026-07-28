"""prompts.loader — convenience facade for engine.llm integration.

This is an alias module that re-exports the public loader functions from
the prompts package root, so that providers can do:

    from prompts.loader import load_math_step_grading, load_correction_validation, load_comment_generation

instead of:

    from prompts import load_math_step_grading, load_correction_validation, load_comment_generation

Both work; this module exists for readability in the engine/llm layer.
"""

from . import (
    load_math_step_grading,
    load_correction_validation,
    load_comment_generation,
    list_prompts,
    PROMPTS_VERSION,
)

__all__ = [
    "load_math_step_grading",
    "load_correction_validation",
    "load_comment_generation",
    "list_prompts",
    "PROMPTS_VERSION",
]
