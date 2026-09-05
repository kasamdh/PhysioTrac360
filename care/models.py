"""Tenant-scoped clinical data models for the PT EMR.

This application deliberately keeps clinical AI artifacts separate from signed
documentation. A therapist must review and sign any resulting note.
"""
from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


def generate_mrn() -> str:
    """Return a non-sequential MRN suitable for a demo environment."""
    return "SM-" + uuid.uuid4().hex[:10].upper()


def organization_logo_upload_path(instance, filename: str) -> str:
    """Keep facility logos isolated from clinical uploads and use opaque names."""
    extension = Path(filename).suffix.lower()
    return "organization_logos/%s/%s%s" % (
        instance.pk,
        uuid.uuid4().hex,
        extension,
    )


class UUIDTimeStampedModel(models.Model):
    """Base model for PHI-bearing records."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Organization(UUIDTimeStampedModel):
    """Tenant boundary for all patient data."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    class SubscriptionTier(models.TextChoices):
        STARTER = "starter", "Starter"
        PROFESSIONAL = "professional", "Professional"
        PREMIUM = "premium", "Premium"
        ENTERPRISE = "enterprise", "Enterprise"

    name = models.CharField(max_length=160)
    slug = models.SlugField(unique=True)
    client_number = models.PositiveBigIntegerField(unique=True, null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    subscription_tier = models.CharField(
        max_length=20, choices=SubscriptionTier.choices, default=SubscriptionTier.STARTER
    )
    timezone = models.CharField(max_length=64, default="America/New_York")
    portal_url = models.URLField(blank=True)
    logo = models.FileField(
        upload_to=organization_logo_upload_path,
        blank=True,
        validators=[FileExtensionValidator(allowed_extensions=["png", "jpg", "jpeg", "webp"])],
    )
    support_email = models.EmailField(blank=True)
    support_phone = models.CharField(max_length=32, blank=True)
    address = models.TextField(blank=True)
    address_line_1 = models.CharField(max_length=200, blank=True)
    address_line_2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=80, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=80, default="United States")
    comments = models.TextField(blank=True)
    onboarding_completed_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="suspended_organizations",
    )
    suspension_reason = models.TextField(blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="archived_organizations",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_organizations",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="updated_organizations",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def initials(self) -> str:
        words = [word for word in self.name.split() if word]
        if not words:
            return "CW"
        return "".join(word[0] for word in words[:2]).upper()


class ClientNumberSequence(models.Model):
    """Database row used as a lock for monotonic client numbers."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    next_number = models.PositiveBigIntegerField(default=1000)


class ClientInvitation(UUIDTimeStampedModel):
    """Hashed, expiring invitation for a provisioned client administrator."""

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="invitations")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="client_invitations")
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_usable(self):
        return self.used_at is None and self.expires_at > timezone.now()


class PrivilegedAccessGrant(UUIDTimeStampedModel):
    """Time-boxed, reasoned, fully-audited break-glass access to one client's
    clinical data for a platform super administrator. Super admins have no
    standing clinical access; this is the only, explicit path in, and every
    grant and every read taken under it is audited.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="privileged_access_grants"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="privileged_access_grants"
    )
    reason = models.TextField()
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_privileged_access_grants",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organization", "actor", "expires_at"])]

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > timezone.now()


class Location(UUIDTimeStampedModel):
    """Operational clinic location or treatment site for a tenant."""

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="locations",
    )
    name = models.CharField(max_length=160)
    address_line_1 = models.CharField(max_length=200, blank=True)
    address_line_2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=80, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    timezone = models.CharField(max_length=80, default="America/Los_Angeles")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["organization", "name"])]

    def __str__(self) -> str:
        return self.name


class AppointmentType(UUIDTimeStampedModel):
    """Clinic-administrator-configured appointment type label and default duration.

    Deliberately separate from Appointment.Kind (the fixed clinical-workflow
    enum that drives note templates and compliance logic) — this is the
    org-facing scheduling label a clinic administrator maintains, e.g. "New
    Patient Eval — Ortho" vs. "New Patient Eval — Neuro" might both map to the
    same underlying evaluation workflow.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="appointment_types"
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    default_duration_minutes = models.PositiveSmallIntegerField(default=30)
    price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    color = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    online_booking_enabled = models.BooleanField(default=True)
    requires_new_patient = models.BooleanField(
        default=False, help_text="Only offered to patients booking as a new patient (e.g. Initial Evaluation)."
    )
    buffer_before_minutes = models.PositiveSmallIntegerField(default=0)
    buffer_after_minutes = models.PositiveSmallIntegerField(default=0)
    default_kind = models.CharField(
        max_length=20, blank=True,
        help_text="Optional Appointment.Kind value this maps to for clinical-workflow defaults.",
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"], name="unique_appointment_type_name_per_org"
            )
        ]

    def clean(self):
        if self.default_kind and self.default_kind not in Appointment.Kind.values:
            raise ValidationError({"default_kind": "Choose a supported appointment kind."})

    def __str__(self) -> str:
        return self.name


class Provider(UUIDTimeStampedModel):
    """Clinical provider profile tied to a tenant and optionally a user account."""

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="providers",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="provider_profile",
    )
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    specialty = models.CharField(max_length=120, blank=True)
    credentials = models.CharField(max_length=120, blank=True)
    license_number = models.CharField(max_length=80, blank=True)
    npi_number = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)
    online_booking_enabled = models.BooleanField(default=True)
    bio = models.TextField(blank=True)
    locations = models.ManyToManyField(Location, blank=True, related_name="providers")

    class Meta:
        ordering = ["last_name", "first_name"]
        indexes = [models.Index(fields=["organization", "last_name", "first_name"])]

    def clean(self):
        if (
            self.user_id
            and self.organization_id
            and self.user.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"user": "Provider user must belong to the same organization."}
            )

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class ProviderAppointmentType(UUIDTimeStampedModel):
    """Which appointment types a provider is eligible to perform — a provider
    with no row here for a given type is never offered it during booking."""

    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="appointment_type_links")
    appointment_type = models.ForeignKey(
        AppointmentType, on_delete=models.CASCADE, related_name="provider_links"
    )
    active = models.BooleanField(default=True)
    custom_duration_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    custom_price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["appointment_type__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "appointment_type"], name="unique_provider_appointment_type"
            )
        ]

    def clean(self):
        if (
            self.provider_id
            and self.appointment_type_id
            and self.provider.organization_id != self.appointment_type.organization_id
        ):
            raise ValidationError(
                {"appointment_type": "Appointment type must belong to the provider's organization."}
            )

    def __str__(self) -> str:
        return f"{self.provider} — {self.appointment_type}"


class ProviderAvailability(UUIDTimeStampedModel):
    """One recurring weekly working-hours window for a provider at a location.
    Multiple rows per (provider, location, day_of_week) are expected and
    supported — that's how a lunch break splits a day into two windows.
    """

    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="availabilities")
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="provider_availabilities")
    day_of_week = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    active = models.BooleanField(default=True)
    effective_from = models.DateField(null=True, blank=True)
    effective_until = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["provider", "day_of_week", "start_time"]
        indexes = [models.Index(fields=["provider", "location", "day_of_week"])]

    def clean(self):
        errors = {}
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            errors["end_time"] = "End time must be after start time."
        if (
            self.provider_id
            and self.location_id
            and not self.provider.locations.filter(pk=self.location_id).exists()
        ):
            errors["location"] = "Provider does not work at this location."
        if self.effective_from and self.effective_until and self.effective_until < self.effective_from:
            errors["effective_until"] = "End date cannot precede the start date."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.provider} · {self.get_day_of_week_display()} {self.start_time}-{self.end_time}"


class ProviderTimeOff(UUIDTimeStampedModel):
    """A block of time a provider is unavailable for booking (vacation, a
    meeting, lunch not already covered by a split availability window, etc.).
    """

    class Reason(models.TextChoices):
        VACATION = "vacation", "Vacation"
        PERSONAL = "personal", "Personal leave"
        CONFERENCE = "conference", "Conference"
        LUNCH = "lunch", "Lunch"
        MEETING = "meeting", "Meeting"
        ADMIN = "admin", "Admin time"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        APPROVED = "approved", "Approved"
        CANCELLED = "cancelled", "Cancelled"

    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="time_off")
    location = models.ForeignKey(
        Location, on_delete=models.SET_NULL, null=True, blank=True, related_name="provider_time_off"
    )
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    reason = models.CharField(max_length=16, choices=Reason.choices, default=Reason.OTHER)
    notes = models.CharField(max_length=240, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.APPROVED)

    class Meta:
        ordering = ["-start_datetime"]
        indexes = [models.Index(fields=["provider", "start_datetime", "end_datetime"])]

    def clean(self):
        if self.start_datetime and self.end_datetime and self.end_datetime <= self.start_datetime:
            raise ValidationError({"end_datetime": "End time must be after start time."})

    def __str__(self) -> str:
        return f"{self.provider} — {self.get_reason_display()}"


class LocationClosure(UUIDTimeStampedModel):
    """A clinic-wide closure at one location (holiday, staff meeting, weather)
    during which no provider at that location can be booked."""

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="closures")
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    reason = models.CharField(max_length=160)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-start_datetime"]
        indexes = [models.Index(fields=["location", "start_datetime", "end_datetime"])]

    def clean(self):
        if self.start_datetime and self.end_datetime and self.end_datetime <= self.start_datetime:
            raise ValidationError({"end_datetime": "End time must be after start time."})

    def __str__(self) -> str:
        return f"{self.location} — {self.reason}"


class BookingConfiguration(UUIDTimeStampedModel):
    """Per-organization public-booking policy. Online booking is off by
    default — an organization must explicitly opt in."""

    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name="booking_configuration"
    )
    online_booking_enabled = models.BooleanField(default=False)
    allow_new_patients = models.BooleanField(default=True)
    allow_returning_patients = models.BooleanField(default=True)
    allow_any_available_therapist = models.BooleanField(default=True)
    min_notice_hours = models.PositiveSmallIntegerField(default=4)
    max_advance_days = models.PositiveSmallIntegerField(default=90)
    slot_interval_minutes = models.PositiveSmallIntegerField(default=15)
    cancellation_policy = models.TextField(blank=True)

    def __str__(self) -> str:
        return f"Booking configuration — {self.organization}"


class Feature(UUIDTimeStampedModel):
    """SaaS feature flag available to a subscription plan or a tenant."""

    code = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class SubscriptionPlan(UUIDTimeStampedModel):
    """Base SaaS offer for an organization."""

    code = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    monthly_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    annual_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    provider_seat_limit = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    features = models.ManyToManyField(Feature, blank=True, related_name="plans")

    class Meta:
        ordering = ["monthly_price", "name"]

    def __str__(self) -> str:
        return self.name


class OrganizationSubscription(UUIDTimeStampedModel):
    """The currently active SaaS contract for a tenant."""

    class Status(models.TextChoices):
        TRIAL = "trial", "Trial"
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past due"
        SUSPENDED = "suspended", "Suspended"
        CANCELLED = "cancelled", "Cancelled"

    class BillingCycle(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        ANNUAL = "annual", "Annual"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name="organization_subscriptions",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.TRIAL)
    billing_cycle = models.CharField(
        max_length=16,
        choices=BillingCycle.choices,
        default=BillingCycle.MONTHLY,
    )
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(null=True, blank=True)
    provider_seat_count = models.PositiveIntegerField(default=1)
    features = models.ManyToManyField(Feature, blank=True, related_name="subscriptions")
    last_payment_status = models.CharField(max_length=32, blank=True)

    class Meta:
        ordering = ["-starts_at"]

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE

    def has_feature(self, feature_code: str) -> bool:
        if not self.is_active:
            return False
        return self.features.filter(code=feature_code).exists()

    def __str__(self) -> str:
        return f"{self.organization.name} :: {self.plan.name}"


class User(AbstractUser):
    """Application user with a single organization and least-privilege role."""

    class Role(models.TextChoices):
        SUPER_ADMIN = "super_admin", "Super administrator"
        ADMIN = "admin", "Organization administrator"
        DIRECTOR = "director", "Clinical director"
        THERAPIST = "therapist", "Physical therapist"
        ASSISTANT = "assistant", "PTA / therapy assistant"
        SCHEDULER = "scheduler", "Scheduler / front desk"
        BILLER = "biller", "Billing specialist"
        COMPLIANCE = "compliance", "Compliance officer"
        PATIENT = "patient", "Patient portal user"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users",
    )
    role = models.CharField(max_length=24, choices=Role.choices, default=Role.THERAPIST)
    credential = models.CharField(max_length=64, blank=True)
    must_use_mfa = models.BooleanField(default=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="archived_users",
    )

    class Meta:
        ordering = ["last_name", "first_name", "username"]

    @property
    def is_platform_super_admin(self) -> bool:
        """Return whether this is the canonical cross-client platform account."""
        return bool(
            self.is_superuser
            and self.role == self.Role.SUPER_ADMIN
            and self.organization_id is None
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.role == self.Role.SUPER_ADMIN:
            if self.organization_id is not None:
                errors["organization"] = (
                    "Platform super administrators cannot be assigned to a client."
                )
            if not self.is_superuser:
                errors["role"] = (
                    "A platform super administrator must have platform superuser status."
                )
        elif self.is_superuser:
            errors["role"] = (
                "Platform superuser status requires the Super administrator role."
            )
        if errors:
            raise ValidationError(errors)

    @property
    def can_access_clinical(self) -> bool:
        return self.role in {
            self.Role.ADMIN,
            self.Role.DIRECTOR,
            self.Role.THERAPIST,
            self.Role.ASSISTANT,
            self.Role.COMPLIANCE,
        }

    @property
    def can_sign_notes(self) -> bool:
        return self.role in {
            self.Role.ADMIN,
            self.Role.DIRECTOR,
            self.Role.THERAPIST,
        }

    @property
    def can_manage_schedule(self) -> bool:
        return self.role in {
            self.Role.ADMIN,
            self.Role.DIRECTOR,
            self.Role.THERAPIST,
            self.Role.ASSISTANT,
            self.Role.SCHEDULER,
        }


class Patient(UUIDTimeStampedModel):
    """Minimum-necessary demographics and PT chart header."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        DISCHARGED = "discharged", "Discharged"

    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="patients"
    )
    medical_record_number = models.CharField(
        max_length=24, unique=True, default=generate_mrn, editable=False
    )
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    date_of_birth = models.DateField()
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    emergency_contact = models.CharField(max_length=200, blank=True)
    diagnoses = models.TextField(blank=True)
    precautions = models.TextField(blank=True)
    assigned_therapist = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_patients",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        ordering = ["last_name", "first_name"]
        indexes = [
            models.Index(fields=["organization", "last_name", "first_name"]),
            models.Index(fields=["organization", "medical_record_number"]),
        ]

    def __str__(self) -> str:
        return self.full_name

    @property
    def full_name(self) -> str:
        return (self.first_name + " " + self.last_name).strip()

    @property
    def age(self) -> int:
        today = date.today()
        return today.year - self.date_of_birth.year - (
            (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
        )

    def clean(self):
        if self.assigned_therapist and (
            self.assigned_therapist.organization_id != self.organization_id
        ):
            raise ValidationError(
                {"assigned_therapist": "Assigned therapist must belong to this organization."}
            )


class Referral(UUIDTimeStampedModel):
    """A referral to or from an outside provider, tracked by front-desk staff."""

    class Direction(models.TextChoices):
        INCOMING = "incoming", "Incoming — from a referring provider"
        OUTGOING = "outgoing", "Outgoing — to a specialist or provider"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SCHEDULED = "scheduled", "Scheduled"
        COMPLETED = "completed", "Completed"
        DECLINED = "declined", "Declined"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="referrals")
    direction = models.CharField(max_length=16, choices=Direction.choices, default=Direction.INCOMING)
    provider_name = models.CharField(max_length=200)
    provider_contact = models.CharField(max_length=200, blank=True)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_referrals"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["patient", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.get_direction_display()} — {self.provider_name}"


class Consent(UUIDTimeStampedModel):
    """Versioned consent record; document storage belongs in encrypted object storage."""

    class Kind(models.TextChoices):
        TREATMENT = "treatment", "Consent to treatment"
        TELEHEALTH = "telehealth", "Telehealth consent"
        FINANCIAL = "financial", "Financial policy"
        VOICE = "voice", "Voice documentation consent"
        PRIVACY = "privacy", "Privacy notice acknowledgement"

    class Status(models.TextChoices):
        SIGNED = "signed", "Signed"
        DECLINED = "declined", "Declined"
        WITHDRAWN = "withdrawn", "Withdrawn"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="consents")
    kind = models.CharField(max_length=24, choices=Kind.choices)
    document_version = models.CharField(max_length=40)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SIGNED)
    signature_name = models.CharField(max_length=160, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recorded_consents"
    )

    class Meta:
        ordering = ["-signed_at", "-created_at"]


class IntakeSubmission(UUIDTimeStampedModel):
    """Structured intake answers. Do not add sensitive fields to application logs."""

    class Status(models.TextChoices):
        STARTED = "started", "Started"
        SUBMITTED = "submitted", "Submitted"
        REVIEWED = "reviewed", "Reviewed"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="intakes")
    form_version = models.CharField(max_length=40)
    answers = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.STARTED)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_intakes",
    )


private_document_storage = FileSystemStorage(location=str(settings.PRIVATE_MEDIA_ROOT))


def patient_document_upload_path(instance, filename: str) -> str:
    """Opaque name under a per-patient folder; the original filename is kept
    separately on the model so it never has to round-trip through storage."""
    extension = Path(filename).suffix.lower()
    return "patient_documents/%s/%s%s" % (instance.patient_id, uuid.uuid4().hex, extension)


class PatientDocument(UUIDTimeStampedModel):
    """A clinician-uploaded reference file attached to a patient's chart
    (e.g. an outside imaging report). Stored under PRIVATE_MEDIA_ROOT, never
    MEDIA_ROOT — see settings.PRIVATE_MEDIA_ROOT — so it is reachable only
    through the authenticated, permission-checked download view, never a
    public static-file URL.
    """

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="documents")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="uploaded_patient_documents"
    )
    file = models.FileField(
        upload_to=patient_document_upload_path,
        storage=private_document_storage,
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "png", "jpg", "jpeg", "doc", "docx"])],
    )
    original_filename = models.CharField(max_length=255)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    size_bytes = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["patient", "-created_at"])]

    def __str__(self) -> str:
        return self.title


class Appointment(UUIDTimeStampedModel):
    """A scheduled clinic, telehealth, or home-visit appointment."""

    class Kind(models.TextChoices):
        EVALUATION = "evaluation", "Initial evaluation"
        FOLLOW_UP = "follow_up", "Follow-up visit"
        PROGRESS = "progress", "Progress visit"
        DISCHARGE = "discharge", "Discharge visit"
        TELEHEALTH = "telehealth", "Telehealth"

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        CHECKED_IN = "checked_in", "Checked in"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        NO_SHOW = "no_show", "No show"

    class BookingSource(models.TextChoices):
        FRONT_DESK = "front_desk", "Front desk"
        PATIENT_PORTAL = "patient_portal", "Patient portal"
        PUBLIC_BOOKING = "public_booking", "Public booking page"
        PROVIDER = "provider", "Provider"
        MOBILE_APP = "mobile_app", "Mobile app"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="appointments")
    therapist = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="appointments"
    )
    provider = models.ForeignKey(
        "Provider",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.FOLLOW_UP)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.SCHEDULED
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    location = models.CharField(max_length=180, blank=True)
    location_detail = models.ForeignKey(
        Location,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )
    is_home_visit = models.BooleanField(default=False)
    private_notes = models.TextField(blank=True)
    appointment_type = models.ForeignKey(
        AppointmentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )
    booking_source = models.CharField(
        max_length=20, choices=BookingSource.choices, default=BookingSource.FRONT_DESK
    )
    reason_for_visit = models.CharField(max_length=240, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_appointments"
    )

    class Meta:
        ordering = ["starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")),
                name="appointment_ends_after_start",
            )
        ]
        indexes = [
            models.Index(fields=["therapist", "starts_at"]),
            models.Index(fields=["patient", "starts_at"]),
            models.Index(fields=["provider", "starts_at"]),
            models.Index(fields=["location_detail", "starts_at"]),
        ]

    def clean(self):
        errors = {}
        if self.ends_at and self.starts_at and self.ends_at <= self.starts_at:
            errors["ends_at"] = "End time must be after start time."
        if self.therapist_id and self.patient_id and (
            self.therapist.organization_id != self.patient.organization_id
        ):
            errors["therapist"] = "Therapist must belong to the patient's organization."
        if self.provider_id and self.provider.organization_id != self.patient.organization_id:
            errors["provider"] = "Provider must belong to the same organization as the patient."
        if self.location_detail_id and self.location_detail.organization_id != self.patient.organization_id:
            errors["location_detail"] = "Location must belong to the same organization as the patient."
        if self.provider_id and self.therapist_id and self.provider.user_id and self.provider.user_id != self.therapist_id:
            errors["provider"] = "Provider does not match the assigned therapist's user profile."
        if self.appointment_type_id and self.patient_id and self.appointment_type.organization_id != self.patient.organization_id:
            errors["appointment_type"] = "Appointment type must belong to the patient's organization."
        if (
            self.therapist_id
            and self.starts_at
            and self.ends_at
            and self.ends_at > self.starts_at
            and self.status not in (self.Status.CANCELLED, self.Status.NO_SHOW)
        ):
            # Model-level backstop against double-booking a therapist — the primary,
            # concurrency-safe defense is each creation path's own select_for_update()
            # check (see care/api/workflow_views.py, care/views.py, care/booking.py),
            # but this also protects callers that bypass those (e.g. Django admin).
            conflicts = Appointment.objects.filter(
                therapist_id=self.therapist_id,
                starts_at__lt=self.ends_at,
                ends_at__gt=self.starts_at,
            ).exclude(status__in=[self.Status.CANCELLED, self.Status.NO_SHOW])
            if self.pk:
                conflicts = conflicts.exclude(pk=self.pk)
            if conflicts.exists():
                errors["starts_at"] = "This therapist already has an appointment during this time."
        if errors:
            raise ValidationError(errors)

    @property
    def confirmation_number(self) -> str:
        return f"APT-{str(self.pk).split('-')[0].upper()}"


class ClinicalNote(UUIDTimeStampedModel):
    """Editable draft note that becomes immutable after therapist signature."""

    class Type(models.TextChoices):
        EVALUATION = "evaluation", "Initial evaluation"
        DAILY = "daily", "Daily treatment note"
        PROGRESS = "progress", "Progress note"
        DISCHARGE = "discharge", "Discharge summary"
        HANDOFF = "handoff", "Handoff summary"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        REVIEW_REQUIRED = "review_required", "Review required"
        SIGNED = "signed", "Signed / locked"
        AMENDED = "amended", "Amended"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="notes")
    therapist = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="clinical_notes"
    )
    appointment = models.OneToOneField(
        Appointment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clinical_note",
    )
    note_type = models.CharField(max_length=20, choices=Type.choices, default=Type.DAILY)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    service_date = models.DateField(default=timezone.localdate)
    diagnosis_snapshot = models.TextField(blank=True)
    precautions_snapshot = models.TextField(blank=True)
    subjective = models.TextField(blank=True)
    objective = models.TextField(blank=True)
    interventions = models.TextField(blank=True)
    assessment = models.TextField(blank=True)
    plan = models.TextField(blank=True)
    plan_of_care_start = models.DateField(null=True, blank=True)
    plan_of_care_end = models.DateField(null=True, blank=True)
    frequency_per_week = models.PositiveSmallIntegerField(null=True, blank=True)
    duration_weeks = models.PositiveSmallIntegerField(null=True, blank=True)
    reassessment_due = models.DateField(null=True, blank=True)
    signature_name = models.CharField(max_length=160, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    finalization_attestation = models.BooleanField(default=False)

    class Meta:
        ordering = ["-service_date", "-created_at"]
        indexes = [
            models.Index(fields=["patient", "service_date"]),
            models.Index(fields=["therapist", "service_date"]),
            models.Index(fields=["status", "reassessment_due"]),
        ]

    def clean(self):
        errors = {}
        if self.therapist_id and self.patient_id and (
            self.therapist.organization_id != self.patient.organization_id
        ):
            errors["therapist"] = "Therapist must belong to the patient's organization."
        if self.plan_of_care_end and self.plan_of_care_start and (
            self.plan_of_care_end < self.plan_of_care_start
        ):
            errors["plan_of_care_end"] = "Plan-of-care end cannot precede its start."
        if self.status == self.Status.SIGNED:
            if not self.signature_name:
                errors["signature_name"] = "A signature is required to finalize a note."
            if not self.signed_at:
                errors["signed_at"] = "Signing time is required to finalize a note."
            if not self.finalization_attestation:
                errors["finalization_attestation"] = (
                    "Therapist attestation is required to finalize a note."
                )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            existing = type(self).objects.filter(pk=self.pk).only("status").first()
            if existing and existing.status == self.Status.SIGNED:
                raise ValidationError(
                    "Signed notes are immutable. Create an addendum instead."
                )
        super().save(*args, **kwargs)

    @property
    def is_signed(self) -> bool:
        return self.status == self.Status.SIGNED


class NoteAddendum(UUIDTimeStampedModel):
    """Correction to a signed note; never changes the signed original."""

    note = models.ForeignKey(ClinicalNote, on_delete=models.PROTECT, related_name="addenda")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="note_addenda"
    )
    reason = models.CharField(max_length=240)
    body = models.TextField()

    class Meta:
        ordering = ["created_at"]

    def clean(self):
        if not self.note.is_signed:
            raise ValidationError("Addenda can only be attached to signed notes.")


class FunctionalGoal(UUIDTimeStampedModel):
    """Structured, measurable goal linked directly to a functional limitation."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft / needs approval"
        ACTIVE = "active", "Active"
        MET = "met", "Met"
        DISCONTINUED = "discontinued", "Discontinued"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="goals")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="authored_goals"
    )
    functional_limitation = models.TextField()
    functional_task = models.CharField(max_length=240)
    baseline_value = models.DecimalField(max_digits=8, decimal_places=2)
    target_value = models.DecimalField(max_digits=8, decimal_places=2)
    current_value = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    unit = models.CharField(max_length=64)
    measurement_method = models.CharField(max_length=160)
    target_date = models.DateField()
    suggested_wording = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_goals",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["status", "target_date"]
        indexes = [models.Index(fields=["patient", "status", "target_date"])]

    def clean(self):
        errors = {}
        required_fields = {
            "functional_limitation": self.functional_limitation,
            "functional_task": self.functional_task,
            "unit": self.unit,
            "measurement_method": self.measurement_method,
            "target_date": self.target_date,
        }
        if self.status == self.Status.ACTIVE:
            for field, value in required_fields.items():
                if not value:
                    errors[field] = "Required before a goal can become active."
            if not self.approved_by_id or not self.approved_at:
                errors["status"] = "A clinician must approve an active goal."
        if errors:
            raise ValidationError(errors)

    @property
    def progress_percent(self) -> int | None:
        if self.current_value is None or self.target_value == self.baseline_value:
            return None
        progress = (
            (self.current_value - self.baseline_value)
            / (self.target_value - self.baseline_value)
            * 100
        )
        return max(0, min(100, round(float(progress))))


class OutcomeScore(UUIDTimeStampedModel):
    """Outcome-measure score and raw component data for deterministic trends."""

    class Measure(models.TextChoices):
        LEFS = "lefs", "LEFS"
        ODI = "odi", "ODI"
        NDI = "ndi", "NDI"
        QUICK_DASH = "quickdash", "QuickDASH"
        TUG = "tug", "Timed Up and Go"
        BERG = "berg", "Berg Balance Scale"
        PSFS = "psfs", "Patient-Specific Functional Scale"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="outcomes")
    note = models.ForeignKey(
        ClinicalNote,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="outcome_scores",
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recorded_outcomes"
    )
    measure = models.CharField(max_length=20, choices=Measure.choices)
    measured_on = models.DateField(default=timezone.localdate)
    score = models.DecimalField(max_digits=8, decimal_places=2)
    maximum_score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    item_responses = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["measure", "measured_on"]
        constraints = [
            models.UniqueConstraint(
                fields=["patient", "measure", "measured_on"],
                name="unique_outcome_per_patient_measure_day",
            )
        ]
        indexes = [models.Index(fields=["patient", "measure", "measured_on"])]

    def clean(self):
        if self.maximum_score is not None and self.score > self.maximum_score:
            raise ValidationError({"score": "Score cannot exceed the entered maximum."})
        if self.score < 0:
            raise ValidationError({"score": "Score cannot be negative."})


class AIArtifact(UUIDTimeStampedModel):
    """Auditable draft generated from an explicit, permission-checked source set."""

    class Kind(models.TextChoices):
        PROGRESS = "progress", "Progress-note draft"
        DISCHARGE = "discharge", "Discharge-summary draft"
        HANDOFF = "handoff", "Handoff-summary draft"
        GOAL = "goal", "Goal suggestion"
        HEP = "hep", "Home-program suggestion"
        PATIENT_SUMMARY = "patient_summary", "Patient visit summary"
        COMPLIANCE = "compliance", "Compliance check"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft — therapist review required"
        APPROVED = "approved", "Approved by therapist"
        REJECTED = "rejected", "Rejected"
        APPLIED = "applied", "Applied to editable note"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="ai_artifacts")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_ai_artifacts"
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    source_note_ids = models.JSONField(default=list)
    source_fingerprint = models.CharField(max_length=128)
    provider = models.CharField(max_length=80, default="local-template")
    model_version = models.CharField(max_length=80, default="clinical-draft-v1")
    draft_text = models.TextField()
    safety_notice = models.TextField(
        default="Draft only. A licensed therapist must verify, edit, approve, and sign."
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_ai_artifacts",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    applied_note = models.ForeignKey(
        ClinicalNote,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_artifacts",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["patient", "kind", "status"])]


class HomeProgram(UUIDTimeStampedModel):
    """Therapist-reviewed home exercise program."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="home_programs")
    prescribed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="home_programs"
    )
    title = models.CharField(max_length=160)
    diagnosis_context = models.TextField(blank=True)
    precautions = models.TextField(blank=True)
    patient_instructions = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class HomeExercise(UUIDTimeStampedModel):
    """Individual prescribed exercise; avoid autonomous dosage changes."""

    home_program = models.ForeignKey(
        HomeProgram, on_delete=models.CASCADE, related_name="exercises"
    )
    name = models.CharField(max_length=160)
    instructions = models.TextField()
    dosage = models.CharField(max_length=120)
    precaution_note = models.TextField(blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]


class VoiceCapture(UUIDTimeStampedModel):
    """Transcript metadata for mobile documentation; raw audio is not stored here."""

    class Status(models.TextChoices):
        TRANSCRIBED = "transcribed", "Transcript ready for review"
        REVIEWED = "reviewed", "Transcript reviewed"
        DISCARDED = "discarded", "Discarded"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="voice_captures")
    therapist = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="voice_captures"
    )
    consent_confirmed = models.BooleanField(default=False)
    duration_seconds = models.PositiveIntegerField(default=0)
    transcript = models.TextField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.TRANSCRIBED
    )
    linked_note = models.ForeignKey(
        ClinicalNote,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="voice_captures",
    )

    class Meta:
        ordering = ["-created_at"]


class SecureMessage(UUIDTimeStampedModel):
    """In-app secure message. Notifications must never include its content."""

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="messages")
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sent_secure_messages"
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="received_secure_messages",
    )
    subject = models.CharField(max_length=180)
    body = models.TextField()
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "read_at"])]


class Superbill(UUIDTimeStampedModel):
    """Billing draft that stores service codes, never payment-card data."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        READY = "ready", "Ready for billing"
        SUBMITTED = "submitted", "Submitted"
        PAID = "paid", "Paid"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="superbills")
    clinician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="superbills"
    )
    service_date = models.DateField()
    codes = models.JSONField(default=list)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    payment_processor_reference = models.CharField(max_length=160, blank=True)


class PaymentRecord(UUIDTimeStampedModel):
    """Token/reference-only payment record; never capture cardholder data here."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RECEIVED = "received", "Received"
        REFUNDED = "refunded", "Refunded"
        VOID = "void", "Void"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="payments")
    superbill = models.ForeignKey(
        Superbill,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recorded_payments"
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    received_on = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    payment_processor_reference = models.CharField(max_length=160)

    class Meta:
        ordering = ["-received_on", "-created_at"]
        indexes = [models.Index(fields=["patient", "received_on"])]

    def clean(self):
        if self.superbill_id and self.superbill.patient_id != self.patient_id:
            raise ValidationError(
                {"superbill": "A payment can only be linked to this patient's superbill."}
            )


class AuditEvent(models.Model):
    """Append-only audit trail. Metadata must contain no clinical narrative."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="audit_events"
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    action = models.CharField(max_length=80)
    object_type = models.CharField(max_length=80)
    object_id = models.UUIDField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["patient", "-created_at"]),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Audit events are append-only and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit events are append-only and cannot be deleted.")
