"""Transactional platform-client management services."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from secrets import token_urlsafe

from django.db import transaction
from django.utils.text import slugify
from django.utils import timezone

from .models import ClientInvitation, ClientNumberSequence, Organization, User
from .services import record_audit_event


@dataclass(frozen=True)
class ProvisionedClient:
    organization: Organization
    administrator: User
    development_invite_token: str


def issue_invitation(organization: Organization, administrator: User) -> str:
    """Issue one fresh development invitation and invalidate older ones."""
    token = token_urlsafe(32)
    ClientInvitation.objects.filter(user=administrator, used_at__isnull=True).update(
        used_at=timezone.now()
    )
    ClientInvitation.objects.create(
        organization=organization,
        user=administrator,
        token_hash=sha256(token.encode()).hexdigest(),
        expires_at=timezone.now() + timedelta(days=7),
    )
    return token


def unique_slug(name: str) -> str:
    base = slugify(name) or "client"
    slug = base
    suffix = 2
    while Organization.objects.filter(slug=slug).exists():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def next_client_number() -> int:
    sequence, _ = ClientNumberSequence.objects.select_for_update().get_or_create(pk=1, defaults={"next_number": 1000})
    existing_max = Organization.objects.exclude(client_number__isnull=True).order_by("-client_number").values_list("client_number", flat=True).first() or 999
    number = max(sequence.next_number, existing_max + 1)
    sequence.next_number = number + 1
    sequence.save(update_fields=["next_number"])
    return number


@transaction.atomic
def provision_client(payload: dict, actor: User) -> ProvisionedClient:
    name = str(payload["clientName"]).strip()
    admin_email = str(payload["adminEmail"]).strip().lower()
    slug = unique_slug(name)
    client = Organization.objects.create(
        client_number=next_client_number(),
        name=name,
        slug=slug,
        portal_url=f"http://localhost:5173/{slug}",
        support_email=str(payload["clientEmail"]).strip().lower(),
        support_phone=str(payload.get("clientPhone", "")).strip(),
        address_line_1=str(payload["addressLine1"]).strip(),
        address_line_2=str(payload.get("addressLine2", "")).strip(),
        city=str(payload["city"]).strip(),
        state=str(payload["state"]).strip(),
        zip_code=str(payload["zipCode"]).strip(),
        country=str(payload.get("country", "United States")).strip() or "United States",
        subscription_tier=payload["subscriptionTier"],
        timezone=payload["timezone"],
        status=payload.get("status", Organization.Status.ACTIVE),
        comments=str(payload.get("comments", "")).strip(),
        created_by=actor,
        updated_by=actor,
    )
    username = admin_email
    if User.objects.filter(username=username).exists():
        raise ValueError("An account with the administrator email already exists.")
    administrator = User.objects.create(
        username=username,
        email=admin_email,
        first_name=str(payload["adminFirstName"]).strip(),
        last_name=str(payload["adminLastName"]).strip(),
        organization=client,
        role=User.Role.ADMIN,
        is_active=True,
    )
    administrator.set_unusable_password()
    administrator.save(update_fields=["password"])
    token = issue_invitation(client, administrator)
    record_audit_event(actor=actor, action="client.created", obj=client, request=None, metadata={"client_number": client.client_number})
    record_audit_event(actor=actor, action="client_admin.created", obj=administrator, request=None, metadata={"client_number": client.client_number})
    return ProvisionedClient(client, administrator, token)


def suspend_client(client: Organization, actor: User, reason: str) -> Organization:
    client.status = Organization.Status.SUSPENDED
    client.is_active = False
    client.suspended_at = timezone.now()
    client.suspended_by = actor
    client.suspension_reason = reason.strip()
    client.save(update_fields=["status", "is_active", "suspended_at", "suspended_by", "suspension_reason", "updated_at"])
    record_audit_event(actor=actor, action="client.suspended", obj=client, request=None, metadata={"client_number": client.client_number})
    return client


def activate_client(client: Organization, actor: User) -> Organization:
    client.status = Organization.Status.ACTIVE
    client.is_active = True
    client.suspended_at = None
    client.suspended_by = None
    client.suspension_reason = ""
    client.save(update_fields=["status", "is_active", "suspended_at", "suspended_by", "suspension_reason", "updated_at"])
    record_audit_event(actor=actor, action="client.reactivated", obj=client, request=None, metadata={"client_number": client.client_number})
    return client


def archive_client(client: Organization, actor: User, reason: str) -> Organization:
    """Soft-delete a client. Data is never removed; access is blocked like suspension."""
    client.is_active = False
    client.archived_at = timezone.now()
    client.archived_by = actor
    if reason.strip():
        client.suspension_reason = reason.strip()
    client.save(update_fields=["is_active", "archived_at", "archived_by", "suspension_reason", "updated_at"])
    record_audit_event(actor=actor, action="client.archived", obj=client, request=None, metadata={"client_number": client.client_number})
    return client


def serialize_client(client: Organization) -> dict:
    administrator = client.users.filter(role=User.Role.ADMIN).order_by("last_name", "first_name").first()
    return {
        "id": str(client.pk),
        "clientNumber": client.client_number,
        "clientName": client.name,
        "slug": client.slug,
        "portalUrl": client.portal_url,
        "email": client.support_email,
        "phone": client.support_phone,
        "city": client.city,
        "state": client.state,
        "addressLine1": client.address_line_1,
        "addressLine2": client.address_line_2,
        "zipCode": client.zip_code,
        "country": client.country,
        "subscriptionTier": client.subscription_tier,
        "subscriptionTierLabel": client.get_subscription_tier_display(),
        "timezone": client.timezone,
        "status": client.status,
        "statusLabel": client.get_status_display(),
        "comments": client.comments,
        "userCount": client.users.count(),
        "primaryAdmin": ({"id": str(administrator.pk), "name": administrator.get_full_name(), "email": administrator.email} if administrator else None),
        "createdAt": client.created_at.isoformat(),
        "updatedAt": client.updated_at.isoformat(),
        "suspendedAt": client.suspended_at.isoformat() if client.suspended_at else None,
        "archivedAt": client.archived_at.isoformat() if client.archived_at else None,
    }
