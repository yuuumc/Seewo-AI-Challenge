"""Student ID pseudonymization for LLM-bound payloads (Sprint 4 P0-1).

All student identifiers that flow toward an external LLM provider
(request body, trace records, logs) MUST pass through
:func:`pseudonymize_student_id` first. The function uses HMAC-SHA256
with a salt sourced from the ``STUDENT_ID_SALT`` environment variable,
producing an irreversible, deterministic token.

Design notes
------------
* **Irreversible**: HMAC-SHA256 is a one-way function; the raw
  ``student_id`` cannot be recovered from the pseudonym without the
  salt (which never leaves the server).
* **Deterministic**: the same ``student_id`` + salt always yields the
  same pseudonym, so cross-request correlation for analytics remains
  possible without exposing the real ID.
* **Salt from env**: ``STUDENT_ID_SALT`` must be set in production.
  A dev fallback is provided so tests and local demos work zero-config,
  but a warning is logged if the fallback is used.
* **Prefix**: pseudonyms are prefixed with ``pseudo_`` so they are
  visually distinguishable from raw IDs in logs and traces.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os

logger = logging.getLogger(__name__)

_SALT_WARNED = False


def _get_salt() -> bytes:
    """Return the pseudonymization salt from env, with a dev fallback."""
    global _SALT_WARNED
    salt = os.environ.get("STUDENT_ID_SALT", "")
    if salt:
        return salt.encode("utf-8")
    # Dev fallback — deterministic so tests are reproducible, but
    # production MUST set STUDENT_ID_SALT.
    if not _SALT_WARNED:
        logger.warning(
            "STUDENT_ID_SALT not set — using insecure dev fallback. "
            "Set STUDENT_ID_SALT in production for student_id anonymization."
        )
        _SALT_WARNED = True
    return b"seewo-dev-salt-do-not-use-in-prod"


def pseudonymize_student_id(student_id: str) -> str:
    """Return an irreversible HMAC-SHA256 pseudonym for ``student_id``.

    Parameters
    ----------
    student_id:
        Raw student identifier, e.g. ``"s01"``.

    Returns
    -------
    str
        Pseudonym like ``"pseudo_a1b2c3d4e5f6..."`` (16-char hex prefix
        for readability; full digest used internally).

    The pseudonym is safe to include in LLM request payloads, trace
    records, and logs — it cannot be reversed to the original ID
    without the server-side salt.
    """
    if not student_id:
        return "pseudo_empty"
    digest = hmac.new(_get_salt(), student_id.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"pseudo_{digest[:16]}"


def pseudonymize_dict(data: dict, keys: tuple[str, ...] = ("student_id",)) -> dict:
    """Return a shallow copy of ``data`` with specified keys pseudonymized.

    Useful for sanitizing trace ``input_payload`` dicts in bulk.
    Non-matching keys are passed through unchanged.
    """
    result = dict(data)
    for key in keys:
        if key in result and isinstance(result[key], str):
            result[key] = pseudonymize_student_id(result[key])
    return result
