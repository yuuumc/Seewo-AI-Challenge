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

# ---------------------------------------------------------------------------
# 多学科/多题型 prompt 注册表（Sprint 1 · 提示词工程师线）。
# 与 _PROMPT_NAMES 分离，保证 list_prompts() 原有 3-prompt 契约不变
# （test_prompts_and_eval.py 断言 list_prompts() 恰好返回 3 个）。
# ---------------------------------------------------------------------------
_MULTI_SUBJECT_PROMPT_NAMES: tuple[str, ...] = (
    "math_application_grading",
    "chinese_essay_grading",
    "english_cloze_grading",
    "english_essay_grading",
    "physics_short_grading",
    "chemistry_short_grading",
)

# subject_type → prompt name 映射（外部按学科/题型取 prompt 的统一入口）
_SUBJECT_TYPE_MAP: dict[str, str] = {
    "math_calculation": "math_step_grading",
    "math_application": "math_application_grading",
    "chinese_essay": "chinese_essay_grading",
    "english_cloze": "english_cloze_grading",
    "english_essay": "english_essay_grading",
    "physics_short": "physics_short_grading",
    "chemistry_short": "chemistry_short_grading",
}


def _read_prompt_file(name: str) -> str:
    """Read a prompt .md file as UTF-8 text.

    Args:
        name: prompt name without .md suffix (e.g. "math_step_grading").
              支持原 3 个 + 多学科 6 个。

    Returns:
        Full file content as a string (the system prompt verbatim).

    Raises:
        FileNotFoundError: if the .md file does not exist in this package.
    """
    _all = _PROMPT_NAMES + _MULTI_SUBJECT_PROMPT_NAMES
    if name not in _all:
        raise ValueError(
            f"Unknown prompt name: {name!r}. Valid: {_all}"
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


def list_multi_subject_prompts() -> List[Dict[str, str]]:
    """列出所有多学科/多题型 prompt 的元信息。"""
    out: List[Dict[str, str]] = []
    for name in _MULTI_SUBJECT_PROMPT_NAMES:
        path = Path(__file__).parent / f"{name}.md"
        size = path.stat().st_size if path.exists() else 0
        out.append({
            "name": name,
            "path": str(path),
            "size_bytes": str(size),
            "version": PROMPTS_VERSION,
        })
    return out


def load_prompt_by_name(name: str) -> str:
    """按 prompt name 加载（通用入口，覆盖原 3 + 多学科 6）。"""
    return _read_prompt_file(name)


def get_prompt(subject_type: str) -> str:
    """按 subject_type 取 system prompt（统一入口）。

    Args:
        subject_type: math_calculation | math_application | chinese_essay
            | english_cloze | english_essay | physics_short | chemistry_short

    Raises:
        KeyError: 未知 subject_type。
    """
    if subject_type not in _SUBJECT_TYPE_MAP:
        raise KeyError(
            f"未知 subject_type={subject_type!r}，可选: {list(_SUBJECT_TYPE_MAP)}"
        )
    return _read_prompt_file(_SUBJECT_TYPE_MAP[subject_type])


def list_subject_types() -> List[str]:
    """列出所有已注册学科/题型。"""
    return list(_SUBJECT_TYPE_MAP)


__all__ = [
    "PROMPTS_VERSION",
    "load_math_step_grading",
    "load_correction_validation",
    "load_comment_generation",
    "list_prompts",
    "list_multi_subject_prompts",
    "load_prompt_by_name",
    "get_prompt",
    "list_subject_types",
]
