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


def send_patient_portal_invitation_email(user, organization, invitation_url: str) -> bool:
    """Email a new or reissued patient-portal activation link. Same
    best-effort, never-raises contract as send_client_admin_invitation_email
    — the on-screen invitation link staff see after issuing it is the
    reliable fallback if delivery fails."""
    subject = f"Set up your {organization.name} patient portal account"
    greeting = user.first_name or user.email
    body = (
        f"Hi {greeting},\n\n"
        f"{organization.name} has set up online portal access for you on Source Motion PT. "
        "Use the link below to set your password and sign in:\n\n"
        f"{invitation_url}\n\n"
        "This link expires in 7 days and can only be used once. If you weren't "
        "expecting this, you can ignore this email.\n"
    )
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
        return True
    except Exception:
        logger.warning("Failed to send patient-portal invitation email to %s", user.email, exc_info=True)
        return False


def send_secure_message_notification_email(recipient, organization) -> bool:
    """Alert a recipient (staff or a patient portal user) that a new secure
    message is waiting — deliberately content-free: no subject, no body, not
    even the category. The recipient must sign in to read it. Same
    best-effort, never-raises contract as the invitation emails above.

    Honors a patient recipient's own notification preference — this is the
    single enforcement point, so every caller (staff composing a message,
    the portal's own send) gets it automatically without having to
    remember to check."""
    if not recipient.email:
        return False
    patient_profile = getattr(recipient, "patient_profile", None)
    if patient_profile is not None and not patient_profile.email_notifications_enabled:
        return False
    subject = f"You have a new secure message in {organization.name}"
    greeting = recipient.first_name or recipient.email
    body = (
        f"Hi {greeting},\n\n"
        f"You have a new secure message in {organization.name}'s Source Motion PT account. "
        "Sign in to read it:\n\n"
        f"{settings.FRONTEND_BASE_URL}\n\n"
        "This email intentionally does not include the message itself — sign in to view it.\n"
    )
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [recipient.email], fail_silently=False)
        return True
    except Exception:
        logger.warning("Failed to send secure-message notification email to %s", recipient.email, exc_info=True)
        return False
