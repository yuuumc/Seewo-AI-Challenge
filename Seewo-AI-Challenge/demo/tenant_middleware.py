"""V2.0 Sprint 5 (5.5): Multi-tenant request middleware.

Injects ``g.school_id`` into every Flask request and sets the PG
session variable ``app.current_school_id`` for RLS.

Usage in app.py:
    from tenant_middleware import TenantMiddleware
    TenantMiddleware(app)
"""
from __future__ import annotations

import os

from flask import g, request, session


class TenantMiddleware:
    """Flask before/after request hooks for multi-tenant isolation.

    Before request:
    - Resolves the current user's school_id from session
    - Sets ``g.school_id`` for application-level filtering
    - On PG, executes ``SET LOCAL app.current_school_id = <school_id>``
      and ``SET LOCAL app.current_role = <role>`` for RLS

    After request:
    - No cleanup needed (SET LOCAL is transaction-scoped)
    """

    def __init__(self, app):
        self.app = app
        app.before_request(self._before_request)

    def _before_request(self):
        """Resolve and inject school_id + role into request context."""
        # Default: school_id=1 (for demo mode / unauthenticated requests)
        school_id = 1
        role = None

        # Try to get from session
        if session and session.get("user_id"):
            role = session.get("user_role")
            # school_id would be stored in session at login time
            school_id = session.get("school_id", 1)

        # super_admin: no school filter (sees all)
        if role == "super_admin":
            g.school_id = None  # None = no filter
        else:
            g.school_id = school_id

        g.current_role = role

        # Set PG session variables for RLS (if PG is available)
        self._set_pg_tenant_context(school_id, role)

    def _set_pg_tenant_context(self, school_id: int, role: str | None):
        """Set PG session variables for RLS.

        Uses ``SET LOCAL`` which is transaction-scoped — the setting
        automatically resets when the current transaction commits/rolls back.
        """
        if not school_id or school_id < 1:
            school_id = 1

        try:
            from flask import current_app
            db_engine = current_app.config.get("PG_ENGINE")
            if db_engine is None:
                return

            from sqlalchemy import text
            with db_engine.connect() as conn:
                conn.execute(text(f"SET LOCAL app.current_school_id = '{school_id}'"))
                if role:
                    conn.execute(text(f"SET LOCAL app.current_role = '{role}'"))
                conn.commit()
        except Exception:
            # PG not available or not connected — application-level filtering handles it
            pass


def get_current_school_id() -> int:
    """Return the current request's school_id (default 1)."""
    try:
        return g.school_id or 1
    except (RuntimeError, AttributeError):
        return 1
