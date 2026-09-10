"""Patient Portal account provisioning — staff-triggered, patient-facing.

Mirrors care/client_management.py's invitation pattern exactly (same
`ClientInvitation` model, same hashed-token/expiry/activation flow via
`care/api/super_admin.py:activate_invitation`, which is role-agnostic and
needs no changes to work for a patient account). The only new piece is
*issuing* the invitation against a `User(role=PATIENT)` linked to a
`Patient` chart via `Patient.portal_user`, instead of an org administrator.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from .client_management import invitation_activation_url, issue_invitation
from .models import Patient, User
from .notifications import send_patient_portal_invitation_email
from .services import record_audit_event


@dataclass(frozen=True)
class PortalInvitation:
    user: User
    activation_url: str
    reissued: bool


def invite_patient_to_portal(patient: Patient, email: str, actor: User, request=None) -> PortalInvitation:
    """Create (or reuse) this patient's portal account and issue a fresh
    activation invitation. Never creates a second `User`/duplicate chart
    link for a patient who already has one — reissuing just invalidates the
    old invitation and sends a new one to the same linked account."""
    email = email.strip().lower()
    reissued = patient.portal_user_id is not None

    with transaction.atomic():
        if reissued:
            user = patient.portal_user
            if user.email != email:
                user.email = email
                user.save(update_fields=["email"])
        else:
            if User.objects.filter(username=email).exists():
                raise ValueError("An account with this email already exists.")
            user = User.objects.create(
                username=email,
                email=email,
                first_name=patient.first_name,
                last_name=patient.last_name,
                organization=patient.organization,
                role=User.Role.PATIENT,
                is_active=True,
            )
            user.set_unusable_password()
            user.save(update_fields=["password"])
            patient.portal_user = user
            patient.full_clean()
            patient.save(update_fields=["portal_user"])

        token = issue_invitation(patient.organization, user, email_sender=send_patient_portal_invitation_email)

    record_audit_event(
        actor=actor,
        action="patient_portal.invitation_reissued" if reissued else "patient_portal.invited",
        obj=user,
        patient=patient,
        request=request,
        metadata={"email": email},
    )
    return PortalInvitation(user=user, activation_url=invitation_activation_url(patient.organization, token), reissued=reissued)
