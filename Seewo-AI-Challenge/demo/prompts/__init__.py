"""prompts package — system prompts for LLM providers (math_step_grading, correction_validation, comment_generation).

This package exists so that the engine/llm/openai_provider.py can replace its 3 inline system
prompts with file-loaded strings (drop-in replacement, no provider interface change).

Public API:
    load_math_step_grading() -> str   # 高数大题步骤级批改
    load_correction_validation() -> str  # 订正语义校验
    load_comment_generation() -> str    # 苏格拉底式个性化评语
    list_prompts() -> list[dict]        # 全部 prompt 元信息(name, path, size, version)

Conventions:
    * Each .md file IS the system prompt verbatim (no frontmatter, no wrapper).
    * Each .md is plain UTF-8 markdown readable as text.
    * Loader uses importlib.resources for stdlib-only file access (no extra deps).
    * If a .md is missing, loader raises FileNotFoundError with the absolute path.
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path
from typing import List, Dict

# Package version (bump on prompt-content breaking changes)
PROMPTS_VERSION = "1.0.0"

# Canonical prompt registry — order matters for list_prompts()
_PROMPT_NAMES: tuple[str, ...] = (
    "math_step_grading",
    "correction_validation",
    "comment_generation",
)


def _read_prompt_file(name: str) -> str:
    """Read a prompt .md file as UTF-8 text.

    Args:
        name: prompt name without .md suffix (e.g. "math_step_grading").

    Returns:
        Full file content as a string (the system prompt verbatim).

    Raises:
        FileNotFoundError: if the .md file does not exist in this package.
    """
    if name not in _PROMPT_NAMES:
        raise ValueError(
            f"Unknown prompt name: {name!r}. Valid: {_PROMPT_NAMES}"
        )
    try:
        # Python 3.9+: importlib.resources.files()
        resource = importlib.resources.files(__name__).joinpath(f"{name}.md")
        return resource.read_text(encoding="utf-8")
    except (AttributeError, FileNotFoundError):
        # Fallback: read via __file__-relative path
        path = Path(__file__).parent / f"{name}.md"
        if not path.exists():
            raise FileNotFoundError(
                f"Prompt file not found: {path}. "
                f"Expected one of: {', '.join(n + '.md' for n in _PROMPT_NAMES)}"
            )
        return path.read_text(encoding="utf-8")


def load_math_step_grading() -> str:
    """Load the system prompt for step-level math answer grading.

    Used by engine.llm.openai_provider.OpenAIProvider.grade_step() to replace
    the inline _INLINE_PROMPT_MATH_STEP_GRADING constant.

    Returns:
        System prompt string (verbatim from math_step_grading.md).
    """
    return _read_prompt_file("math_step_grading")


def load_correction_validation() -> str:
    """Load the system prompt for correction-loop validation.

    Replaces inline _INLINE_PROMPT_CORRECTION_VALIDATION. Validates whether
    a student's correction actually addresses the original error (not just
    keyword matching).

    Returns:
        System prompt string (verbatim from correction_validation.md).
    """
    return _read_prompt_file("correction_validation")


def load_comment_generation() -> str:
    """Load the system prompt for Socratic personalized comment generation.

    Replaces inline _INLINE_PROMPT_COMMENT_GENERATION. Generates 3-tier
    comments (excellent / needs_correction / severe_weakness).

    Returns:
        System prompt string (verbatim from comment_generation.md).
    """
    return _read_prompt_file("comment_generation")


def list_prompts() -> List[Dict[str, str]]:
    """List all available prompts with metadata.

    Returns:
        List of dicts with keys: name, path, size_bytes, version.
    """
    out: List[Dict[str, str]] = []
    for name in _PROMPT_NAMES:
        path = Path(__file__).parent / f"{name}.md"
        size = path.stat().st_size if path.exists() else 0
        out.append({
            "name": name,
            "path": str(path),
            "size_bytes": str(size),
            "version": PROMPTS_VERSION,
        })
    return out


__all__ = [
    "PROMPTS_VERSION",
    "load_math_step_grading",
    "load_correction_validation",
    "load_comment_generation",
    "list_prompts",
]
