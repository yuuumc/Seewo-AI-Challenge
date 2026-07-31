"""V2.0 Sprint 7 (7.1): Multi-Factor Authentication (MFA) via TOTP.

Implements Google Authenticator-compatible TOTP using ``pyotp``.

Login flow:
    1. User submits username + password → ``login_user()`` validates creds
    2. If MFA is enabled for the user → redirect to /mfa-verify
    3. User enters 6-digit TOTP code → verified here
    4. On success → session promoted to fully authenticated

Setup flow:
    1. Admin/staff visits /admin/mfa-setup
    2. System generates a TOTP secret, displays QR code + secret string
    3. User scans QR with Google Authenticator (or compatible app)
    4. User enters a 6-digit code to confirm setup
    5. On success → secret saved, mfa_enabled=True

Demo mode (DEMO_AUTH_OPEN=1): MFA is skipped entirely (backward compat).
"""
from __future__ import annotations

import os
import time
from typing import Optional, Tuple

import pyotp
from flask import (
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from security import (
    audit_log,
    get_current_user,
    _demo_open,
    login_required,
    roles_required,
    csrf_protect,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MFA_SESSION_KEY = "_mfa_pending"  # session key for pending MFA verification
MFA_SECRET_SESSION_KEY = "_mfa_setup_secret"  # temp secret during setup
MFA_ISSUER = "Seewo-AI-Challenge"


# ---------------------------------------------------------------------------
# MFA state helpers — works with both DEMO_USERS (in-memory) and PG (via db_store)
# ---------------------------------------------------------------------------
def _get_user_mfa_secret(username: str) -> Optional[str]:
    """Get the MFA TOTP secret for a user.

    Returns None if MFA is not set up. Tries PG first, falls back to DEMO_USERS.
    """
    # PG path
    try:
        from db_store import get_user
        user = get_user(username)
        if user and user.get("mfa_secret"):
            return user["mfa_secret"]
    except Exception:
        pass

    # DEMO_USERS path
    from security import DEMO_USERS
    user = DEMO_USERS.get(username)
    if user and user.get("mfa_secret"):
        return user["mfa_secret"]
    return None


def _is_mfa_enabled(username: str) -> bool:
    """Check if MFA is enabled for a user."""
    # PG path
    try:
        from db_store import get_user
        user = get_user(username)
        if user:
            return bool(user.get("mfa_enabled", False))
    except Exception:
        pass

    # DEMO_USERS path
    from security import DEMO_USERS
    user = DEMO_USERS.get(username)
    if user:
        return bool(user.get("mfa_enabled", False))
    return False


def _save_mfa_secret(username: str, secret: str) -> bool:
    """Save the MFA secret and enable MFA for the user.

    Tries PG first, falls back to DEMO_USERS (in-memory, not persistent).
    """
    # PG path
    try:
        from infra.pg.orm import User
        from sqlalchemy import update
        from db_store import _get_sync_db_url
        from sqlalchemy.orm import Session as SASession
        from sqlalchemy import create_engine

        engine = create_engine(_get_sync_db_url())
        with SASession(engine) as s:
            s.execute(
                update(User)
                .where(User.username == username)
                .values(mfa_secret=secret, mfa_enabled=True)
            )
            s.commit()
        return True
    except Exception:
        pass

    # DEMO_USERS fallback (in-memory only, resets on restart)
    from security import DEMO_USERS
    user = DEMO_USERS.get(username)
    if user:
        user["mfa_secret"] = secret
        user["mfa_enabled"] = True
        return True
    return False


# ---------------------------------------------------------------------------
# TOTP operations
# ---------------------------------------------------------------------------
def generate_totp_secret() -> str:
    """Generate a new base32-encoded TOTP secret."""
    return pyotp.random_base32()


def get_totp(secret: str) -> pyotp.TOTP:
    """Get a TOTP instance for the given secret."""
    return pyotp.TOTP(secret)


def verify_totp(secret: str, code: str) -> bool:
    """Verify a 6-digit TOTP code against the secret.

    Uses a ±1 time step window to allow for clock drift (30s each direction).
    """
    if not secret or not code:
        return False
    code = code.strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return False
    totp = get_totp(secret)
    return totp.verify(code, valid_window=1)


def get_provisioning_uri(secret: str, username: str) -> str:
    """Get the otpauth:// provisioning URI for QR code generation."""
    return pyotp.TOTP(secret).provisioning_uri(
        name=username,
        issuer_name=MFA_ISSUER,
    )


def get_qr_code_data_uri(secret: str, username: str) -> str:
    """Generate a QR code as a data URI for inline display.

    Uses the ``qrcode`` library if available; otherwise returns the
    provisioning URI as a plain string (frontend can render it).
    """
    uri = get_provisioning_uri(secret, username)
    try:
        import qrcode
        import io
        import base64

        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except ImportError:
        # qrcode library not installed — return provisioning URI
        # Frontend can use a JS QR library to render it
        return uri


# ---------------------------------------------------------------------------
# MFA check during login
# ---------------------------------------------------------------------------
def mfa_check_after_login(username: str, user: dict) -> Tuple[bool, Optional[str]]:
    """Check if MFA is required after successful password verification.

    Returns (mfa_required, redirect_url).
    - If MFA not enabled or demo mode: (False, None)
    - If MFA enabled: (True, url_for('mfa_verify'))
    """
    if _demo_open():
        return False, None

    if not _is_mfa_enabled(username):
        return False, None

    # Set pending MFA state in session (not fully authenticated yet)
    session[MFA_SESSION_KEY] = {
        "username": username,
        "role": user.get("role"),
        "name": user.get("name"),
        "school_id": user.get("school_id", 1),
        "timestamp": time.time(),
    }
    # Remove the full session markers — user must complete MFA first
    session.pop("user_id", None)
    session.pop("user_role", None)
    session.pop("user_name", None)

    return True, url_for("mfa_verify")


def is_mfa_pending() -> bool:
    """Check if the current session has a pending MFA verification."""
    pending = session.get(MFA_SESSION_KEY)
    if not pending:
        return False
    # Expire pending state after 5 minutes
    ts = pending.get("timestamp", 0)
    if time.time() - ts > 300:
        session.pop(MFA_SESSION_KEY, None)
        return False
    return True


def complete_mfa_verification(code: str) -> Tuple[bool, Optional[str]]:
    """Complete MFA verification with a 6-digit code.

    Returns (success, error_message).
    On success, promotes the pending session to fully authenticated.
    """
    pending = session.get(MFA_SESSION_KEY)
    if not pending:
        return False, "MFA 会话已过期，请重新登录"

    username = pending.get("username", "")
    secret = _get_user_mfa_secret(username)
    if not secret:
        return False, "MFA 未绑定，请联系管理员"

    if not verify_totp(secret, code):
        audit_log("mfa_verify_failed", user_id=username)
        return False, "验证码错误，请重试"

    # Promote session to fully authenticated
    session.pop(MFA_SESSION_KEY, None)
    session["user_id"] = username
    session["user_role"] = pending.get("role")
    session["user_name"] = pending.get("name")
    session["school_id"] = pending.get("school_id", 1)

    audit_log("mfa_verify_success", user_id=username)
    return True, None


# ---------------------------------------------------------------------------
# Flask route handlers
# ---------------------------------------------------------------------------
def register_mfa_routes(app) -> None:
    """Register MFA-related routes on the Flask app."""

    @app.route("/mfa-verify", methods=["GET", "POST"])
    @csrf_protect
    def mfa_verify():
        """MFA verification page — prompts for 6-digit TOTP code."""
        if _demo_open():
            # Demo mode: MFA skipped, redirect to index
            return redirect(url_for("index"))

        if not is_mfa_pending():
            flash("无需 MFA 验证，请先登录。", "info")
            return redirect(url_for("login"))

        if request.method == "POST":
            code = request.form.get("mfa_code", "").strip()
            success, err = complete_mfa_verification(code)
            if success:
                flash("MFA 验证成功！", "success")
                return redirect(url_for("index"))
            return render_template("mfa_verify.html", error=err or "验证码错误"), 401

        return render_template("mfa_verify.html")

    @app.route("/admin/mfa-setup", methods=["GET", "POST"])
    @login_required
    @roles_required("admin", "head", "teacher")
    @csrf_protect
    def mfa_setup():
        """MFA setup page — generate QR code, verify first code, save secret."""
        if _demo_open():
            return render_template(
                "mfa_setup.html",
                demo_mode=True,
                message="演示模式已开启，MFA 功能在演示模式下不生效。生产环境请设置 DEMO_AUTH_OPEN=0。",
            )

        user = get_current_user()
        username = user.get("user_id", "") if user else ""

        # Check if MFA is already enabled
        if _is_mfa_enabled(username) and request.method == "GET":
            return render_template(
                "mfa_setup.html",
                already_enabled=True,
                message="MFA 已启用。如需重新绑定，请先禁用后再设置。",
            )

        if request.method == "POST":
            action = request.form.get("action", "")

            if action == "generate":
                # Generate new secret and store in session temporarily
                secret = generate_totp_secret()
                session[MFA_SECRET_SESSION_KEY] = secret
                qr_data = get_qr_code_data_uri(secret, username)
                provisioning_uri = get_provisioning_uri(secret, username)
                return render_template(
                    "mfa_setup.html",
                    secret=secret,
                    qr_data=qr_data,
                    provisioning_uri=provisioning_uri,
                    show_verify=True,
                )

            if action == "verify":
                secret = session.get(MFA_SECRET_SESSION_KEY)
                if not secret:
                    return render_template(
                        "mfa_setup.html",
                        error="会话已过期，请重新生成密钥",
                    ), 400

                code = request.form.get("mfa_code", "").strip()
                if verify_totp(secret, code):
                    # Save the secret permanently
                    if _save_mfa_secret(username, secret):
                        session.pop(MFA_SECRET_SESSION_KEY, None)
                        audit_log("mfa_setup_success", user_id=username)
                        return render_template(
                            "mfa_setup.html",
                            success=True,
                            message="MFA 绑定成功！下次登录时请使用 Google Authenticator 输入验证码。",
                        )
                    return render_template(
                        "mfa_setup.html",
                        error="保存密钥失败，请重试或联系管理员",
                    ), 500
                else:
                    return render_template(
                        "mfa_setup.html",
                        secret=secret,
                        qr_data=get_qr_code_data_uri(secret, username),
                        provisioning_uri=get_provisioning_uri(secret, username),
                        show_verify=True,
                        error="验证码错误，请重试",
                    ), 401

            if action == "disable":
                # Disable MFA
                if _save_mfa_secret(username, "") or True:
                    # For DEMO_USERS, clear the secret
                    from security import DEMO_USERS
                    if username in DEMO_USERS:
                        DEMO_USERS[username]["mfa_secret"] = None
                        DEMO_USERS[username]["mfa_enabled"] = False
                    # For PG, set mfa_enabled=False
                    try:
                        from infra.pg.orm import User
                        from sqlalchemy import update
                        from db_store import _get_sync_db_url
                        from sqlalchemy.orm import Session as SASession
                        from sqlalchemy import create_engine

                        engine = create_engine(_get_sync_db_url())
                        with SASession(engine) as s:
                            s.execute(
                                update(User)
                                .where(User.username == username)
                                .values(mfa_secret=None, mfa_enabled=False)
                            )
                            s.commit()
                    except Exception:
                        pass
                    audit_log("mfa_disabled", user_id=username)
                    return render_template(
                        "mfa_setup.html",
                        disabled=True,
                        message="MFA 已禁用。",
                    )

        # GET: show setup page with generate button
        return render_template("mfa_setup.html")
