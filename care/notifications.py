"""Outbound transactional email — thin wrapper over Django's mail backend.

`EMAIL_BACKEND` defaults to Django's console backend in development (prints
to the server log, no external account needed); set `EMAIL_BACKEND` /
`EMAIL_HOST` / ... via env vars to point at a real provider in production.
Sends are best-effort: a transport failure is logged, never raised, so a
misconfigured or temporarily-down email provider can't block account
provisioning — the on-screen invitation link remains the reliable fallback.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def send_client_admin_invitation_email(administrator, organization, invitation_url: str) -> bool:
    """Email a new or reissued activation link to a client's administrator.
    Returns whether the send succeeded (callers may ignore this — the
    invitation link is also always shown on-screen as a fallback)."""
    subject = f"Set up your Source Motion PT administrator account for {organization.name}"
    greeting = administrator.first_name or administrator.email
    body = (
        f"Hi {greeting},\n\n"
        f"An administrator account has been created for {organization.name} on Source Motion PT.\n"
        "Set your password to finish activating it:\n\n"
        f"{invitation_url}\n\n"
        "This link expires in 7 days and can only be used once. If you weren't "
        "expecting this, you can ignore this email.\n"
    )
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [administrator.email], fail_silently=False)
        return True
    except Exception:
        logger.warning("Failed to send client-admin invitation email to %s", administrator.email, exc_info=True)
        return False
