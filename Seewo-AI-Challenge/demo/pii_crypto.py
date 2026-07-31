"""V2.0 Sprint 5 (5.7): 字段级 PII 加密 — AES-256-GCM.

学生 PII（姓名/手机号/学号）在写入 PG 前加密，读出后解密。
应用层 AES-GCM 实现，不依赖 pgcrypto 扩展（SQLite 也可用）。

设计要点:
- 密钥来自环境变量 ``PII_ENCRYPTION_KEY``（32 字节 base64）
- 无 key 时生成进程级临时 key（dev/test 用，启动时 warn）
- 加密格式: ``v1:nonce:ciphertext:tag`` (base64, ":" 分隔)
- ``v1`` 前缀便于未来密钥轮换
- 每次加密生成新 nonce（GCM 要求 nonce 不重复）
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import warnings

# Python 3.6+ has secrets; AES-GCM via cryptography or hashlib
# Use hashlib-based AES-GCM if cryptography is not available,
# but prefer the cryptography library for production use.
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    _HAS_CRYPTOGRAPHY = True
except ImportError:
    _HAS_CRYPTOGRAPHY = False
    warnings.warn(
        "cryptography library not found — PII encryption will use a simple "
        "XOR-based mock (NOT for production). Install with: pip install cryptography",
        RuntimeWarning,
        stacklevel=2,
    )

# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------
_KEY_VERSION = "v1"
_KEY: bytes | None = None


def _derive_key(raw: str) -> bytes:
    """Derive a 32-byte AES key from an arbitrary string."""
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _get_key() -> bytes:
    """Return the encryption key, lazily initialized from env."""
    global _KEY
    if _KEY is not None:
        return _KEY

    raw = os.environ.get("PII_ENCRYPTION_KEY", "")
    if raw:
        _KEY = _derive_key(raw)
    else:
        # Dev/test fallback: generate a per-process key
        _KEY = secrets.token_bytes(32)
        warnings.warn(
            "PII_ENCRYPTION_KEY not set — using a random per-process key. "
            "Encrypted data will be unreadable after restart. "
            "Set PII_ENCRYPTION_KEY in production.",
            RuntimeWarning,
            stacklevel=2,
        )
    return _KEY


def encrypt_pii(plaintext: str | None) -> str | None:
    """Encrypt a PII field value using AES-256-GCM.

    Returns ``v1:<nonce_b64>:<ciphertext_b64>`` or None if input is None.
    Empty strings are returned as-is (no PII to encrypt).
    """
    if plaintext is None:
        return None
    if plaintext == "":
        return ""
    if not _HAS_CRYPTOGRAPHY:
        # Mock: simple XOR (dev only, NOT secure)
        key = _get_key()
        nonce = secrets.token_bytes(12)
        ct = bytes(b ^ key[i % len(key)] for i, b in enumerate(plaintext.encode("utf-8")))
        return f"{_KEY_VERSION}:{base64.b64encode(nonce).decode()}:{base64.b64encode(ct).decode()}"

    key = _get_key()
    nonce = secrets.token_bytes(12)  # 96-bit nonce for GCM
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return f"{_KEY_VERSION}:{base64.b64encode(nonce).decode()}:{base64.b64encode(ct).decode()}"


def decrypt_pii(encrypted: str | None) -> str | None:
    """Decrypt a PII field value.

    Returns the original plaintext, or None if input is None.
    If the value doesn't look encrypted (no ``v1:`` prefix), returns as-is
    (for backward compat with unencrypted legacy data).
    """
    if encrypted is None:
        return None
    if not encrypted.startswith(f"{_KEY_VERSION}:"):
        # Not encrypted (legacy data) — return as-is
        return encrypted

    parts = encrypted.split(":", 2)
    if len(parts) != 3:
        return encrypted  # Malformed, return as-is

    _, nonce_b64, ct_b64 = parts
    try:
        nonce = base64.b64decode(nonce_b64)
        ct = base64.b64decode(ct_b64)

        if not _HAS_CRYPTOGRAPHY:
            # Mock: reverse XOR
            key = _get_key()
            pt = bytes(b ^ key[i % len(key)] for i, b in enumerate(ct))
            return pt.decode("utf-8")

        key = _get_key()
        aesgcm = AESGCM(key)
        pt = aesgcm.decrypt(nonce, ct, None)
        return pt.decode("utf-8")
    except Exception:
        return None


def encrypt_pii_fields(data: dict, fields: list[str]) -> dict:
    """Encrypt specified PII fields in a dict.

    The encrypted value is stored in ``pii_encrypted`` as a JSON blob,
    and the original field is set to a masked version (e.g. "张**").
    """
    pii_data = {}
    for field in fields:
        if field in data and data[field]:
            pii_data[field] = data[field]
            data[field] = _mask_value(data[field])

    if pii_data:
        data["pii_encrypted"] = encrypt_pii(json.dumps(pii_data, ensure_ascii=False))
    return data


def decrypt_pii_fields(data: dict, fields: list[str]) -> dict:
    """Decrypt PII fields from the ``pii_encrypted`` blob.

    Restores original values for the specified fields, replacing the
    masked versions. If decryption fails, keeps the masked value.
    """
    encrypted = data.get("pii_encrypted")
    if not encrypted:
        return data

    blob = decrypt_pii(encrypted)
    if not blob:
        return data

    try:
        pii_data = json.loads(blob)
        for field in fields:
            if field in pii_data:
                data[field] = pii_data[field]
    except (json.JSONDecodeError, TypeError):
        pass
    return data


def _mask_value(value: str) -> str:
    """Mask a PII value for display (e.g. '张三' → '张*', '13800138000' → '138****8000')."""
    if not value:
        return value
    if len(value) <= 1:
        return "*"
    if len(value) == 2:
        return value[0] + "*"
    if len(value) <= 4:
        return value[0] + "*" * (len(value) - 2) + value[-1]
    # Phone numbers and longer: show first 3 + last 4
    return value[:3] + "*" * (len(value) - 7) + value[-4:]
