"""Tenant-scoped clinical data models for the PT EMR.

This application deliberately keeps clinical AI artifacts separate from signed
documentation. A therapist must review and sign any resulting note.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.validators import FileExtensionValidator, RegexValidator
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


def expiry_alert_tier(days_remaining: int, warning_days) -> str:
    """Escalating severity string from a days-remaining count and a set of
    day-count thresholds: 'expired' (days_remaining < 0), 'critical_N' for a
    threshold N <= 14, 'expiring_N' for a larger threshold, else 'valid'.
    Shared by every "expires soon" concept in this codebase (license, plan of
    care, ...) so each one only supplies its own threshold list."""
    if days_remaining < 0:
        return "expired"
    for threshold in sorted(warning_days):
        if days_remaining <= threshold:
            return f"critical_{threshold}" if threshold <= 14 else f"expiring_{threshold}"
    return "valid"


def expiry_color_bucket(tier: str) -> str:
    """'valid' | 'expiring_soon' | 'critical' | 'expired' — the 4-color
    grouping badge/banner UI renders from an `expiry_alert_tier` result."""
    if tier == "expired":
        return "expired"
    if tier.startswith("critical_"):
        return "critical"
    if tier.startswith("expiring_"):
        return "expiring_soon"
    return "valid"


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
    npi_number = models.CharField(
        max_length=10, blank=True, help_text="Billing-provider (group) NPI — CMS-1500 box 33."
    )
    tax_id = models.CharField(
        max_length=20, blank=True, help_text="Federal tax ID / EIN — CMS-1500 box 25."
    )
    address = models.TextField(blank=True)
    address_line_1 = models.CharField(max_length=200, blank=True)
    address_line_2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=80, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=80, default="United States")
    comments = models.TextField(blank=True)
    # Clinical documentation policy: whether a PTA/ASSISTANT-authored note
    # requires a supervising PT/Director cosignature before it's final.
    # Conservative default (True) since this is new safety-relevant behavior
    # for every existing PTA the moment this ships, unless an admin opts out.
    pta_cosign_required = models.BooleanField(default=True)
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
    patient_change_cutoff_hours = models.PositiveSmallIntegerField(
        default=24,
        help_text="How many hours before an appointment a patient may still cancel or reschedule it online via the portal.",
    )

    def __str__(self) -> str:
        return f"Booking configuration — {self.organization}"


class Waitlist(UUIDTimeStampedModel):
    """A patient's request to be seen sooner than their next confirmed slot —
    joined from the portal, worked from the staff schedule when an opening
    appears. Preferences (location/type/provider) are all optional filters;
    leaving them blank means "any" for that dimension.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        FULFILLED = "fulfilled", "Fulfilled"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="waitlist_entries")
    patient = models.ForeignKey("Patient", on_delete=models.PROTECT, related_name="waitlist_entries")
    location = models.ForeignKey(
        Location, on_delete=models.SET_NULL, null=True, blank=True, related_name="waitlist_entries"
    )
    appointment_type = models.ForeignKey(
        AppointmentType, on_delete=models.SET_NULL, null=True, blank=True, related_name="waitlist_entries"
    )
    provider = models.ForeignKey(
        Provider, on_delete=models.SET_NULL, null=True, blank=True, related_name="waitlist_entries"
    )
    earliest_date = models.DateField()
    latest_date = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=240, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organization", "status"])]

    def clean(self):
        errors = {}
        if self.patient_id and self.organization_id and self.patient.organization_id != self.organization_id:
            errors["patient"] = "Patient must belong to the same organization."
        if self.location_id and self.organization_id and self.location.organization_id != self.organization_id:
            errors["location"] = "Location must belong to the same organization."
        if self.appointment_type_id and self.organization_id and self.appointment_type.organization_id != self.organization_id:
            errors["appointment_type"] = "Appointment type must belong to the same organization."
        if self.provider_id and self.organization_id and self.provider.organization_id != self.organization_id:
            errors["provider"] = "Provider must belong to the same organization."
        if self.latest_date and self.earliest_date and self.latest_date < self.earliest_date:
            errors["latest_date"] = "End of range cannot precede the start of the range."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.patient} waitlist entry — {self.get_status_display()}"


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

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        LOCKED_OUT = "locked_out", "Locked Out"
        SUSPENDED = "suspended", "Suspended"
        DELETED = "deleted", "Deleted"

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
    must_change_password = models.BooleanField(default=False)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    status_changed_at = models.DateTimeField(null=True, blank=True)
    status_changed_by = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="status_changed_users"
    )

    failed_login_attempts = models.PositiveIntegerField(default=0)
    last_failed_login_at = models.DateTimeField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)

    suspended_at = models.DateTimeField(null=True, blank=True)
    suspended_by = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="suspended_users"
    )
    suspension_reason = models.TextField(blank=True)

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

    @property
    def effective_status(self) -> str:
        """Status as it should be treated right now, healing an expired lockout for display
        purposes only — the underlying row is only written back to ACTIVE the next time this
        account actually attempts to authenticate (see `care.api.views.login`)."""
        if self.status == self.Status.LOCKED_OUT and self.locked_until and self.locked_until <= timezone.now():
            return self.Status.ACTIVE
        return self.status

    @property
    def _worst_license(self):
        """The single most urgent license among this user's `UserLicense` rows
        (smallest `days_remaining`), or None if the role doesn't carry a
        license or none is on file. Backs the two aggregate properties below,
        which the list/badge UI reads since it shows one value per user even
        though a PT/PTA may hold several licenses."""
        if self.role not in {self.Role.THERAPIST, self.Role.ASSISTANT}:
            return None
        return min(self.licenses.all(), key=lambda license: license.days_remaining, default=None)

    @property
    def license_days_remaining(self) -> int | None:
        """Days until this account's most urgent license expires, or negative
        if already expired. None when the role doesn't carry a license or
        none is on file."""
        worst = self._worst_license
        return worst.days_remaining if worst else None

    @property
    def license_alert_status(self) -> str:
        """'none' | 'valid' | 'expiring_soon' | 'critical' | 'expired' — drives
        the onboarding alert banner, aggregated across every license this user
        holds. Only meaningful for licensed clinician roles."""
        worst = self._worst_license
        return worst.color_bucket if worst else "none"

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


class UserSession(UUIDTimeStampedModel):
    """One authenticated browser/device session, tracked independently of
    Django's own session store so a login can be revoked, listed, and limited
    per user regardless of how long the underlying session cookie is valid.
    """

    class RevokedReason(models.TextChoices):
        NEW_LOGIN = "new_login", "Signed in from another browser or device"
        USER_LOGOUT = "user_logout", "Signed out"
        IDLE_TIMEOUT = "idle_timeout", "Idle timeout"
        ABSOLUTE_TIMEOUT = "absolute_timeout", "Maximum session lifetime reached"
        PASSWORD_CHANGED = "password_changed", "Password changed"
        PASSWORD_RESET = "password_reset", "Password reset by an administrator"
        ACCOUNT_LOCKED = "account_locked", "Account locked"
        ACCOUNT_SUSPENDED = "account_suspended", "Account suspended"
        ACCOUNT_DEACTIVATED = "account_deactivated", "Account deactivated"
        ACCOUNT_DELETED = "account_deleted", "Account deleted"
        ADMIN_REVOKED = "admin_revoked", "Signed out by an administrator"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sessions")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, null=True, blank=True, related_name="user_sessions")
    django_session_key = models.CharField(max_length=64, unique=True)
    last_activity_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=24, choices=RevokedReason.choices, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=400, blank=True)
    device_name = models.CharField(max_length=80, blank=True)
    browser_name = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > timezone.now()


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

    class ContactMethod(models.TextChoices):
        EMAIL = "email", "Email"
        PHONE = "phone", "Phone call"
        SMS = "sms", "Text message"

    pharmacy_name = models.CharField(max_length=160, blank=True)
    pharmacy_phone = models.CharField(max_length=32, blank=True)
    pharmacy_address = models.TextField(blank=True)
    preferred_contact_method = models.CharField(max_length=16, choices=ContactMethod.choices, default=ContactMethod.EMAIL)
    email_notifications_enabled = models.BooleanField(
        default=True,
        help_text="Whether this patient receives the (content-free) 'you have a new secure message' email.",
    )
    assigned_therapist = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_patients",
    )
    portal_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="patient_profile",
        help_text="The login identity (role=patient) this chart's portal account uses, if one has been issued.",
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
        if self.portal_user_id:
            if self.portal_user.organization_id != self.organization_id:
                raise ValidationError({"portal_user": "Portal account must belong to this organization."})
            if self.portal_user.role != User.Role.PATIENT:
                raise ValidationError({"portal_user": "Portal account must have the patient role."})

    @property
    def _active_plan_of_care_note(self):
        """The most recently documented note that carries a plan_of_care_end
        date — i.e. the note that currently defines this patient's active
        plan of care. Not the same as "most recent note" (a daily note
        rarely carries POC fields); matches the same source-of-truth notes
        already query when checking `reassessment_due`."""
        return (
            self.notes.filter(plan_of_care_end__isnull=False)
            .order_by("-service_date", "-created_at")
            .first()
        )

    @property
    def plan_of_care_end_date(self):
        note = self._active_plan_of_care_note
        return note.plan_of_care_end if note else None

    @property
    def plan_of_care_days_remaining(self) -> int | None:
        end_date = self.plan_of_care_end_date
        if end_date is None:
            return None
        return (end_date - timezone.localdate()).days

    @property
    def plan_of_care_alert_tier(self) -> str:
        """'none' (no documented plan of care yet) | 'expired' | 'critical_N'
        | 'expiring_N' | 'valid'."""
        days = self.plan_of_care_days_remaining
        if days is None:
            return "none"
        return expiry_alert_tier(days, settings.PLAN_OF_CARE_WARNING_DAYS)

    @property
    def plan_of_care_color_bucket(self) -> str:
        """'none' | 'valid' | 'expiring_soon' | 'critical' | 'expired'."""
        tier = self.plan_of_care_alert_tier
        if tier == "none":
            return "none"
        return expiry_color_bucket(tier)


class PatientProfileChangeRequest(UUIDTimeStampedModel):
    """A patient's self-submitted request to change sensitive contact
    fields (phone/email/address/emergency contact) — never applied
    automatically. Staff review and either approve (which writes `changes`
    onto the Patient row) or reject; the request row itself is kept either
    way as a permanent record of what was asked and decided. Lower-risk
    fields (pharmacy, communication preference) skip this queue entirely
    and are written directly to Patient — see care/api/patient_portal.py's
    portal_profile_preferences."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    ALLOWED_FIELDS = {"phone", "email", "address", "emergency_contact"}

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="profile_change_requests")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_profile_changes"
    )
    changes = models.JSONField(default=dict, blank=True, help_text="Proposed {field_name: new_value}, keys restricted to ALLOWED_FIELDS.")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_profile_changes"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewer_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["patient", "status"])]

    def clean(self):
        errors = {}
        if self.patient_id and self.requested_by_id and self.patient.portal_user_id != self.requested_by_id:
            errors["requested_by"] = "Only the patient's own portal account may request changes to their profile."
        if not isinstance(self.changes, dict) or not self.changes:
            errors["changes"] = "At least one field change is required."
        elif not set(self.changes.keys()) <= self.ALLOWED_FIELDS:
            errors["changes"] = f"Only these fields may be requested: {', '.join(sorted(self.ALLOWED_FIELDS))}."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.patient} profile change ({self.get_status_display()})"


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


class EpisodeOfCare(UUIDTimeStampedModel):
    """One course of treatment for a patient — groups the appointments and
    clinical notes belonging to a single referral/diagnosis/plan-of-care
    cycle. A patient may have multiple episodes over their lifetime (a knee
    surgery this year, an unrelated shoulder injury next year) and,
    occasionally, more than one open at once (different body regions under
    different plans of care). Deliberately optional everywhere it's
    referenced (Appointment.episode_of_care, ClinicalNote.episode_of_care)
    — every existing patient/appointment/note predates this model and must
    keep working with no episode assigned."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ON_HOLD = "on_hold", "On hold"
        DISCHARGED = "discharged", "Discharged"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="episodes_of_care")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="episodes_of_care")
    primary_therapist = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="episodes_of_care",
    )
    referral = models.ForeignKey(
        Referral, on_delete=models.SET_NULL, null=True, blank=True, related_name="episodes_of_care"
    )
    diagnosis = models.CharField(max_length=240, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    start_date = models.DateField(default=date.today)
    end_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_episodes_of_care",
    )

    class Meta:
        ordering = ["-start_date", "-created_at"]
        indexes = [models.Index(fields=["organization", "patient", "status"])]

    def clean(self):
        errors = {}
        if self.patient_id and self.organization_id and self.patient.organization_id != self.organization_id:
            errors["patient"] = "Patient must belong to this organization."
        if (
            self.primary_therapist_id
            and self.organization_id
            and self.primary_therapist.organization_id != self.organization_id
        ):
            errors["primary_therapist"] = "Therapist must belong to this organization."
        if self.referral_id and self.patient_id and self.referral.patient_id != self.patient_id:
            errors["referral"] = "Referral must belong to the same patient."
        if self.end_date and self.start_date and self.end_date < self.start_date:
            errors["end_date"] = "End date cannot precede the start date."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.patient} — {self.get_status_display()} ({self.start_date})"


class Authorization(UUIDTimeStampedModel):
    """An insurance authorization for a block of visits. `status` is the
    staff-controlled workflow state (pending/active/denied/cancelled) —
    "expired" and "exhausted" are deliberately NOT stored status values,
    since both are fully derivable from `expires_at`/`visits_used` and
    storing them risks going stale, matching the same "don't store what's
    derivable" rule UserLicense.alert_tier and Patient.plan_of_care_alert_tier
    already follow in this file."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        DENIED = "denied", "Denied"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="authorizations")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="authorizations")
    episode_of_care = models.ForeignKey(
        EpisodeOfCare, on_delete=models.SET_NULL, null=True, blank=True, related_name="authorizations"
    )
    insurance_name = models.CharField(max_length=160, blank=True)
    authorization_number = models.CharField(max_length=80, blank=True)
    visits_approved = models.PositiveSmallIntegerField()
    visits_used = models.PositiveSmallIntegerField(default=0)
    start_date = models.DateField(default=date.today)
    expires_at = models.DateField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_authorizations",
    )

    class Meta:
        ordering = ["-start_date", "-created_at"]
        indexes = [models.Index(fields=["organization", "patient", "status"])]

    def clean(self):
        errors = {}
        if self.patient_id and self.organization_id and self.patient.organization_id != self.organization_id:
            errors["patient"] = "Patient must belong to this organization."
        if self.episode_of_care_id and self.patient_id and self.episode_of_care.patient_id != self.patient_id:
            errors["episode_of_care"] = "Episode of care must belong to the same patient."
        if self.expires_at and self.start_date and self.expires_at < self.start_date:
            errors["expires_at"] = "Expiration cannot precede the start date."
        if self.visits_used > self.visits_approved:
            errors["visits_used"] = "Visits used cannot exceed visits approved."
        if errors:
            raise ValidationError(errors)

    @property
    def visits_remaining(self) -> int:
        return max(0, self.visits_approved - self.visits_used)

    @property
    def days_remaining(self) -> int:
        return (self.expires_at - timezone.localdate()).days

    @property
    def date_alert_tier(self) -> str:
        """'expired' | 'critical_N' | 'expiring_N' | 'valid' — same day-based
        scale as UserLicense.alert_tier / Patient.plan_of_care_alert_tier."""
        return expiry_alert_tier(self.days_remaining, settings.AUTHORIZATION_WARNING_DAYS)

    @property
    def date_color_bucket(self) -> str:
        return expiry_color_bucket(self.date_alert_tier)

    @property
    def visit_alert_tier(self) -> str:
        """'exhausted' | 'critical_1' | 'critical_3' | 'warning_5' | 'ok' —
        the visits-remaining thresholds the product brief asks for (5/3/1/0),
        a separate dimension from date-based expiry."""
        remaining = self.visits_remaining
        if remaining <= 0:
            return "exhausted"
        if remaining <= 1:
            return "critical_1"
        if remaining <= 3:
            return "critical_3"
        if remaining <= 5:
            return "warning_5"
        return "ok"

    @property
    def visit_color_bucket(self) -> str:
        tier = self.visit_alert_tier
        if tier == "exhausted":
            return "expired"
        if tier.startswith("critical_"):
            return "critical"
        if tier.startswith("warning_"):
            return "expiring_soon"
        return "valid"

    @property
    def overall_color_bucket(self) -> str:
        """The worse of the date-based and visit-based buckets, for a single
        summary badge."""
        severity = {"expired": 3, "critical": 2, "expiring_soon": 1, "valid": 0}
        return max(self.date_color_bucket, self.visit_color_bucket, key=lambda bucket: severity[bucket])

    def __str__(self) -> str:
        return f"{self.patient} — {self.authorization_number or 'Authorization'} ({self.visits_remaining}/{self.visits_approved} remaining)"


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


class FormTemplate(UUIDTimeStampedModel):
    """A reusable, schema-driven form definition — digital intake, a privacy
    acknowledgement, or any future assignable form. `schema` is a list of
    sections, each `{"key", "label", "fields": [{"key", "label", "type",
    "required"}, ...]}` — deliberately data-driven (not one hardcoded model
    per form type) so a new form type is a new template row, not a
    migration. `validity_days` drives the computed "expired" status on
    FormSubmission (None means a completed submission never expires)."""

    class Category(models.TextChoices):
        INTAKE = "intake", "Intake"
        CONSENT = "consent", "Consent"
        OTHER = "other", "Other"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="form_templates")
    slug = models.SlugField(max_length=80)
    name = models.CharField(max_length=160)
    category = models.CharField(max_length=16, choices=Category.choices, default=Category.OTHER)
    schema = models.JSONField(default=list, blank=True)
    validity_days = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "slug"], name="unique_form_template_slug_per_org")
        ]

    def __str__(self) -> str:
        return self.name


class FormSubmission(UUIDTimeStampedModel):
    """One patient's answers to one FormTemplate. Insert-only once
    `status == COMPLETED`: a later re-submission (e.g. after expiration)
    creates a NEW row rather than mutating this one — historical submissions
    are never overwritten, matching every other audit-relevant record in
    this codebase."""

    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "Not started"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="form_submissions")
    template = models.ForeignKey(FormTemplate, on_delete=models.PROTECT, related_name="submissions")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NOT_STARTED)
    data = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    signature_name = models.CharField(max_length=160, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    signed_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["patient", "template", "-created_at"])]

    def clean(self):
        if self.patient_id and self.template_id and self.patient.organization_id != self.template.organization_id:
            raise ValidationError({"template": "Form template must belong to the patient's organization."})

    @property
    def is_expired(self) -> bool:
        """A completed submission "ages out" once past the template's
        validity window — computed live, never stored, same as every other
        derived-status field in this codebase (e.g. Authorization, Claim)."""
        if self.status != self.Status.COMPLETED or not self.submitted_at or not self.template.validity_days:
            return False
        return timezone.now() > self.submitted_at + timedelta(days=self.template.validity_days)

    def __str__(self) -> str:
        return f"{self.patient} — {self.template.name} ({self.get_status_display()})"


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
    visible_to_patient = models.BooleanField(
        default=False,
        help_text="Off by default for a staff upload — a clinician must explicitly share a document before the "
        "portal can show it. A patient's own upload through the portal always sets this true at creation.",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["patient", "-created_at"])]

    def __str__(self) -> str:
        return self.title


def user_license_document_upload_path(instance, filename: str) -> str:
    """Opaque name under a per-user folder, mirroring `patient_document_upload_path` —
    the original filename is kept separately on the model."""
    extension = Path(filename).suffix.lower()
    return "license_documents/%s/%s%s" % (instance.user_id, uuid.uuid4().hex, extension)


def patient_insurance_card_upload_path(instance, filename: str) -> str:
    """Opaque name under a per-policy folder, mirroring `patient_document_upload_path`."""
    extension = Path(filename).suffix.lower()
    return "insurance_cards/%s/%s%s" % (instance.pk or uuid.uuid4().hex, uuid.uuid4().hex, extension)


class UserLicense(UUIDTimeStampedModel):
    """One professional license (e.g. a state PT/PTA license) held by a user.
    A clinician may hold several — one per issuing state — so this is a child
    table rather than flat fields on `User`. Expiry severity (`alert_tier`/
    `color_bucket`) is always computed from `expires_at` + today, never
    stored, matching `User.effective_status`'s "don't store what's derivable"
    philosophy; `verification_status` is the one piece of real stored state,
    since whether an admin has reviewed the uploaded document is a genuine
    fact, not something derivable from a date.
    """

    class VerificationStatus(models.TextChoices):
        PENDING_VERIFICATION = "pending_verification", "Pending verification"
        VERIFIED = "verified", "Verified"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="licenses")
    license_number = models.CharField(max_length=80)
    issuing_state = models.CharField(max_length=40)
    license_type = models.CharField(max_length=40, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    expires_at = models.DateField()

    verification_status = models.CharField(
        max_length=24, choices=VerificationStatus.choices, default=VerificationStatus.PENDING_VERIFICATION
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="verified_licenses"
    )
    verification_notes = models.TextField(blank=True)

    document = models.FileField(
        upload_to=user_license_document_upload_path,
        storage=private_document_storage,
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "png", "jpg", "jpeg", "doc", "docx"])],
        null=True,
        blank=True,
    )
    document_original_filename = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-expires_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "issuing_state", "license_number"], name="unique_user_license_per_state_number"
            )
        ]
        indexes = [models.Index(fields=["user", "expires_at"])]

    @property
    def organization(self):
        """Not a stored field — lets `record_audit_event` resolve the tenant
        for a license the same way it already does for any other object,
        via `getattr(obj, "organization", None)`, without duplicating data."""
        return self.user.organization

    @property
    def days_remaining(self) -> int:
        return (self.expires_at - timezone.localdate()).days

    @property
    def alert_tier(self) -> str:
        """Escalating severity, most to least urgent: 'expired', 'critical_7',
        'critical_14', 'expiring_30', 'expiring_60', 'expiring_90', 'valid'."""
        return expiry_alert_tier(self.days_remaining, settings.LICENSE_WARNING_DAYS)

    @property
    def color_bucket(self) -> str:
        """'valid' | 'expiring_soon' | 'critical' | 'expired' — the 4-color
        grouping the badge/banner UI actually renders; `alert_tier` carries
        the precise day-count tier for the banner's message text."""
        return expiry_color_bucket(self.alert_tier)

    def __str__(self) -> str:
        return f"{self.issuing_state} {self.license_number}".strip()


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
    episode_of_care = models.ForeignKey(
        EpisodeOfCare,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )
    authorization = models.ForeignKey(
        Authorization,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_appointments"
    )
    confirmed_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the patient confirmed this visit via the portal. Null means unconfirmed.",
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
        if self.episode_of_care_id and self.patient_id and self.episode_of_care.patient_id != self.patient_id:
            errors["episode_of_care"] = "Episode of care must belong to the same patient."
        if self.authorization_id and self.patient_id and self.authorization.patient_id != self.patient_id:
            errors["authorization"] = "Authorization must belong to the same patient."
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
        RE_EVALUATION = "re_evaluation", "Re-evaluation"
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
    episode_of_care = models.ForeignKey(
        EpisodeOfCare,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clinical_notes",
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

    # Structured section data (ROM/MMT/special-tests/pain detail, discharge
    # specifics) — read/written as one blob per note, never queried across
    # notes in SQL, matching the existing OutcomeScore.item_responses /
    # IntakeSubmission.answers JSONField precedent in this codebase.
    subjective_details = models.JSONField(default=dict, blank=True)
    objective_measurements = models.JSONField(default=dict, blank=True)
    discharge_details = models.JSONField(default=dict, blank=True)

    # PTA cosign: set from Organization.pta_cosign_required at creation time
    # (only meaningful when the author is a PTA/ASSISTANT) — snapshotted so a
    # later org-policy change never silently changes an in-progress note's
    # requirement, matching diagnosis_snapshot/precautions_snapshot's pattern.
    cosign_required = models.BooleanField(default=False)
    cosigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="cosigned_notes",
    )
    cosigned_at = models.DateTimeField(null=True, blank=True)

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
        if self.episode_of_care_id and self.patient_id and self.episode_of_care.patient_id != self.patient_id:
            errors["episode_of_care"] = "Episode of care must belong to the same patient."
        if self.status == self.Status.SIGNED:
            if not self.signature_name:
                errors["signature_name"] = "A signature is required to finalize a note."
            if not self.signed_at:
                errors["signed_at"] = "Signing time is required to finalize a note."
            if not self.finalization_attestation:
                errors["finalization_attestation"] = (
                    "Therapist attestation is required to finalize a note."
                )
            if self.cosign_required and not (self.cosigned_by_id and self.cosigned_at):
                errors["cosigned_by"] = "A supervising cosignature is required to finalize this note."
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


class NoteIntervention(UUIDTimeStampedModel):
    """One structured treatment line item on a Daily Treatment Note (the
    "treatment timer" — repeatable, billing-adjacent, and summed, unlike the
    free-text `ClinicalNote.interventions` field it sits alongside). A real
    child table rather than JSON because these rows need a DB-level sum for
    the timer and are the kind of data most likely to need reporting later —
    the same shape `NoteAddendum` already is to `ClinicalNote`.
    """

    class Category(models.TextChoices):
        THERAPEUTIC_EXERCISE = "therapeutic_exercise", "Therapeutic Exercise"
        MANUAL_THERAPY = "manual_therapy", "Manual Therapy"
        THERAPEUTIC_ACTIVITY = "therapeutic_activity", "Therapeutic Activity"
        NEUROMUSCULAR_REEDUCATION = "neuromuscular_reeducation", "Neuromuscular Re-education"
        GAIT_TRAINING = "gait_training", "Gait Training"
        SELF_CARE = "self_care", "Self-care / Home Management"
        PATIENT_EDUCATION = "patient_education", "Patient Education"
        OTHER = "other", "Other Intervention"

    note = models.ForeignKey(
        ClinicalNote, on_delete=models.CASCADE, related_name="intervention_items"
    )
    description = models.CharField(max_length=240)
    body_region = models.CharField(max_length=80, blank=True)
    # Blank means "not categorized" — deliberately excluded from CPT-code
    # suggestions (services.coding_suggestions) rather than guessed from the
    # free-text description, since fuzzy-matching text to a billing code is
    # exactly the kind of fabrication this app's AI-safety rules forbid.
    category = models.CharField(max_length=32, choices=Category.choices, blank=True)
    minutes = models.PositiveSmallIntegerField(default=0)
    units = models.PositiveSmallIntegerField(null=True, blank=True)
    is_timed = models.BooleanField(default=True)
    patient_response = models.CharField(max_length=240, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "created_at"]

    def clean(self):
        if self.note_id and self.note.is_signed:
            raise ValidationError("Interventions cannot be changed once the note is signed.")

    def __str__(self) -> str:
        return self.description


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


class OutcomeAssignment(UUIDTimeStampedModel):
    """A therapist's request that a patient complete one specific
    self-report outcome measure through the portal. Deliberately patient-
    specific (unlike the org-wide FormTemplate engine) since which measure
    applies is a clinical judgment — a knee patient gets LEFS, a neck
    patient gets NDI, not every patient gets every measure. Re-administering
    the same measure later (standard practice for tracking progress) is a
    new assignment row, never a re-opened old one — history stays intact."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="outcome_assignments")
    measure = models.CharField(max_length=20, choices=OutcomeScore.Measure.choices)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assigned_outcome_measures"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    assigned_at = models.DateTimeField(default=timezone.now)
    completed_score = models.ForeignKey(
        OutcomeScore, on_delete=models.SET_NULL, null=True, blank=True, related_name="assignment"
    )

    class Meta:
        ordering = ["-assigned_at"]
        indexes = [models.Index(fields=["patient", "status"])]

    def clean(self):
        if self.patient_id and self.completed_score_id and self.completed_score.patient_id != self.patient_id:
            raise ValidationError({"completed_score": "Score must belong to the same patient."})

    def __str__(self) -> str:
        return f"{self.patient} — {self.get_measure_display()} ({self.get_status_display()})"


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
        CODING = "coding", "Coding suggestion"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft — therapist review required"
        APPROVED = "approved", "Approved by therapist"
        REJECTED = "rejected", "Rejected"
        APPLIED = "applied", "Applied to editable note"

    class SectionStatus(models.TextChoices):
        """Per-section review state stored inside the `sections` JSON list —
        not a DB column, just a shared vocabulary for services/views/tests."""

        PENDING = "pending", "Pending review"
        ACCEPTED = "accepted", "Accepted as drafted"
        EDITED = "edited", "Edited by therapist"
        REJECTED = "rejected", "Rejected"

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
    sections = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Optional per-section breakdown of draft_text for granular therapist "
            "review: [{key, label, draftText, status, reviewedText}, ...]. Empty "
            "for kinds that are only ever reviewed as a single block."
        ),
    )
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
    video_url = models.URLField(blank=True, help_text="Link to an instructional video (YouTube, Vimeo, or similar).")

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class HomeExerciseLog(UUIDTimeStampedModel):
    """One patient-reported completion of one exercise — the raw material
    for adherence tracking. Insert-only: a patient logging the same
    exercise again (a different day, or a second set later the same day)
    creates another row rather than editing a prior one, so history is
    never lost."""

    home_exercise = models.ForeignKey(HomeExercise, on_delete=models.PROTECT, related_name="logs")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="home_exercise_logs")
    completed_at = models.DateTimeField(default=timezone.now)
    pain_level = models.PositiveSmallIntegerField(null=True, blank=True)
    difficulty_level = models.PositiveSmallIntegerField(null=True, blank=True)
    comment = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-completed_at"]
        indexes = [models.Index(fields=["patient", "-completed_at"])]

    def clean(self):
        errors = {}
        if self.home_exercise_id and self.patient_id and self.home_exercise.home_program.patient_id != self.patient_id:
            errors["home_exercise"] = "Exercise must belong to this patient's own home program."
        for field_name in ("pain_level", "difficulty_level"):
            value = getattr(self, field_name)
            if value is not None and not (0 <= value <= 10):
                errors[field_name] = "Enter a value from 0 to 10."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.patient} — {self.home_exercise.name} ({self.completed_at.date()})"


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

    class Category(models.TextChoices):
        GENERAL = "general", "General"
        APPOINTMENT = "appointment", "Appointment"
        HEP = "hep", "Home exercise program"
        BILLING = "billing", "Billing"
        CLINICAL = "clinical", "Clinical"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="messages")
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sent_secure_messages"
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="received_secure_messages",
    )
    category = models.CharField(max_length=16, choices=Category.choices, default=Category.GENERAL)
    subject = models.CharField(max_length=180)
    body = models.TextField()
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "read_at"])]


class DiagnosisCode(UUIDTimeStampedModel):
    """Read-only ICD-10-CM reference data, shared across every tenant — the
    same catalog for everyone, not per-organization data. Maintained only via
    `seed_diagnosis_codes` (idempotent, get-or-create by code), never edited
    through the API, exactly like the platform-wide Feature/SubscriptionPlan
    catalogs in this file."""

    code = models.CharField(max_length=10, unique=True)
    description = models.CharField(max_length=255)
    is_billable = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return "%s — %s" % (self.code, self.description)


class Payer(UUIDTimeStampedModel):
    """One entry in an organization's configurable insurance-payer directory.
    Deliberately data-driven (timely filing days, authorization requirement,
    free-text rules notes) rather than hard-coding any payer's rules into the
    UI — billing staff maintain this directory themselves."""

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="payers")
    name = models.CharField(max_length=160)
    payer_id = models.CharField(max_length=40, blank=True)
    electronic_payer_id = models.CharField(max_length=40, blank=True)
    address_line_1 = models.CharField(max_length=200, blank=True)
    address_line_2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=80, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    is_active = models.BooleanField(default=True)
    timely_filing_days = models.PositiveSmallIntegerField(default=90)
    authorization_required = models.BooleanField(default=False)
    authorization_notes = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_payers"
    )

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["organization", "name"])]

    def __str__(self) -> str:
        return self.name


class PatientInsurance(UUIDTimeStampedModel):
    """One insurance policy on a patient's chart. Multiple rows accumulate
    over time (terminated policies are kept, never deleted, for billing
    history) — `is_active` is computed from the effective/termination dates,
    never stored, matching this app's alert-tier/derivable-status pattern."""

    class Rank(models.TextChoices):
        PRIMARY = "primary", "Primary"
        SECONDARY = "secondary", "Secondary"
        TERTIARY = "tertiary", "Tertiary"

    class Relationship(models.TextChoices):
        SELF = "self", "Self"
        SPOUSE = "spouse", "Spouse"
        CHILD = "child", "Child"
        OTHER = "other", "Other"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="patient_insurance_policies")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="insurance_policies")
    payer = models.ForeignKey(Payer, on_delete=models.PROTECT, related_name="patient_policies")
    rank = models.CharField(max_length=16, choices=Rank.choices, default=Rank.PRIMARY)
    plan_name = models.CharField(max_length=160, blank=True)
    member_id = models.CharField(max_length=80)
    group_number = models.CharField(max_length=80, blank=True)
    subscriber_name = models.CharField(max_length=160, blank=True)
    subscriber_date_of_birth = models.DateField(null=True, blank=True)
    relationship_to_subscriber = models.CharField(max_length=16, choices=Relationship.choices, default=Relationship.SELF)
    effective_date = models.DateField()
    termination_date = models.DateField(null=True, blank=True)
    copay = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    coinsurance_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    deductible = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    authorization_required = models.BooleanField(default=False)
    card_front = models.ImageField(
        upload_to=patient_insurance_card_upload_path,
        storage=private_document_storage,
        validators=[FileExtensionValidator(allowed_extensions=["png", "jpg", "jpeg"])],
        null=True,
        blank=True,
    )
    card_back = models.ImageField(
        upload_to=patient_insurance_card_upload_path,
        storage=private_document_storage,
        validators=[FileExtensionValidator(allowed_extensions=["png", "jpg", "jpeg"])],
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_patient_insurance_policies",
    )

    class Meta:
        ordering = ["rank", "-effective_date"]
        indexes = [models.Index(fields=["organization", "patient", "rank"])]

    def clean(self):
        if self.patient_id and self.organization_id and self.patient.organization_id != self.organization_id:
            raise ValidationError({"patient": "Patient must belong to the same organization."})
        if self.payer_id and self.organization_id and self.payer.organization_id != self.organization_id:
            raise ValidationError({"payer": "Payer must belong to the same organization."})
        if self.termination_date and self.effective_date and self.termination_date < self.effective_date:
            raise ValidationError({"terminationDate": "Termination date cannot be before the effective date."})
        if self.coinsurance_percent is not None and not (0 <= self.coinsurance_percent <= 100):
            raise ValidationError({"coinsurancePercent": "Coinsurance must be between 0 and 100 percent."})

    @property
    def is_active(self) -> bool:
        today = timezone.localdate()
        if self.effective_date and self.effective_date > today:
            return False
        if self.termination_date and self.termination_date <= today:
            return False
        return True

    def __str__(self) -> str:
        return "%s — %s (%s)" % (self.patient, self.payer, self.get_rank_display())


_CPT_CODE_VALIDATOR = RegexValidator(
    regex=r"^[A-Z0-9]{5}$", message="Enter a 5-character CPT/HCPCS code (e.g. 97110)."
)
_MODIFIER_VALIDATOR = RegexValidator(regex=r"^[A-Z0-9]{2}$", message="Modifiers must be 2 characters (e.g. GP, 59).")


class Charge(UUIDTimeStampedModel):
    """One billable line item — the unit that will eventually roll up into a
    Claim (a later phase). `recommended_units` is always computed server-side
    from documented timed minutes via the same 8-minute-rule engine used for
    AI coding suggestions (see services.coding_suggestions); it is never
    client-supplied, so it stays a trustworthy comparison point. Entering a
    different `units` value is always allowed — this only assists billing
    staff, it never blocks or rewrites clinician documentation — but requires
    `units_override_reason` once there is a recommendation to diverge from."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        READY = "ready", "Ready to bill"
        BILLED = "billed", "Billed"
        VOID = "void", "Void"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="charges")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="charges")
    episode_of_care = models.ForeignKey(
        EpisodeOfCare, on_delete=models.SET_NULL, null=True, blank=True, related_name="charges"
    )
    clinical_note = models.ForeignKey(
        ClinicalNote, on_delete=models.SET_NULL, null=True, blank=True, related_name="charges"
    )
    provider = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="rendered_charges")
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, related_name="charges")
    claim = models.ForeignKey("Claim", on_delete=models.SET_NULL, null=True, blank=True, related_name="charges")
    superbill = models.ForeignKey(
        "Superbill", on_delete=models.SET_NULL, null=True, blank=True, related_name="charges"
    )
    service_date = models.DateField()
    cpt_code = models.CharField(max_length=5, validators=[_CPT_CODE_VALIDATOR])
    modifiers = models.JSONField(default=list, blank=True)
    units = models.PositiveSmallIntegerField(default=1)
    minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    recommended_units = models.PositiveSmallIntegerField(null=True, blank=True)
    units_override_reason = models.TextField(blank=True)
    diagnosis_codes = models.ManyToManyField(DiagnosisCode, blank=True, related_name="charges")
    charge_amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_charges"
    )

    class Meta:
        ordering = ["-service_date", "-created_at"]
        indexes = [models.Index(fields=["organization", "patient", "service_date"])]

    def clean(self):
        if self.patient_id and self.organization_id and self.patient.organization_id != self.organization_id:
            raise ValidationError({"patient": "Patient must belong to the same organization."})
        if self.episode_of_care_id and self.episode_of_care.patient_id != self.patient_id:
            raise ValidationError({"episodeOfCareId": "Episode of care must belong to this patient."})
        if self.clinical_note_id and self.clinical_note.patient_id != self.patient_id:
            raise ValidationError({"noteId": "The linked note must belong to this patient."})
        if self.location_id and self.organization_id and self.location.organization_id != self.organization_id:
            raise ValidationError({"locationId": "Location must belong to the same organization."})
        if self.superbill_id and self.superbill.patient_id != self.patient_id:
            raise ValidationError({"superbillId": "Superbill must belong to this patient."})
        if self.claim_id and self.superbill_id:
            raise ValidationError({"claimId": "A charge can be billed to insurance or cash-pay, not both."})
        if not isinstance(self.modifiers, list) or len(self.modifiers) > 4:
            raise ValidationError({"modifiers": "Enter at most 4 modifiers."})
        for modifier in self.modifiers:
            try:
                _MODIFIER_VALIDATOR(modifier)
            except ValidationError:
                raise ValidationError({"modifiers": "Modifiers must each be 2 characters (e.g. GP, 59)."})
        if (
            self.recommended_units is not None
            and self.units != self.recommended_units
            and not self.units_override_reason.strip()
        ):
            raise ValidationError(
                {"unitsOverrideReason": "Explain why the entered units differ from the recommended units."}
            )

    @property
    def units_difference(self) -> int | None:
        if self.recommended_units is None:
            return None
        return self.units - self.recommended_units

    def __str__(self) -> str:
        return "%s — %s x%s (%s)" % (self.patient, self.cpt_code, self.units, self.service_date)


class Claim(UUIDTimeStampedModel):
    """An insurance claim — one or more Charge line items billed together
    against one patient insurance policy. `diagnosis_code_list` is an
    ordered snapshot (CMS-1500 box 21, lettered A-L) built once at claim
    creation from the union of its charges' diagnosis codes; each charge's
    diagnosis pointer letters are derived from this list at read time
    (`diagnosis_pointers_for`), never stored per charge. Cash-pay billing
    uses Superbill, not Claim — a claim always requires insurance."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        READY = "ready", "Ready"
        VALIDATION_ERROR = "validation_error", "Validation Error"
        SUBMITTED = "submitted", "Submitted"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        PROCESSING = "processing", "Processing"
        DENIED = "denied", "Denied"
        PARTIAL_PAYMENT = "partial_payment", "Partial Payment"
        PAID = "paid", "Paid"
        APPEALED = "appealed", "Appealed"
        CORRECTED = "corrected", "Corrected"
        CLOSED = "closed", "Closed"

    # Statuses that represent a claim actively awaiting payer action — once a
    # claim leaves DRAFT/READY/VALIDATION_ERROR, charges are locked in.
    OPEN_STATUSES = {
        Status.SUBMITTED, Status.ACCEPTED, Status.PROCESSING, Status.PARTIAL_PAYMENT, Status.APPEALED,
    }
    TERMINAL_STATUSES = {Status.PAID, Status.CLOSED}

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="claims")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="claims")
    patient_insurance = models.ForeignKey(PatientInsurance, on_delete=models.PROTECT, related_name="claims")
    payer = models.ForeignKey(Payer, on_delete=models.PROTECT, related_name="claims")
    diagnosis_code_list = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    clearinghouse_claim_id = models.CharField(max_length=80, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_claims"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organization", "patient", "status"])]

    def clean(self):
        if self.patient_id and self.organization_id and self.patient.organization_id != self.organization_id:
            raise ValidationError({"patient": "Patient must belong to the same organization."})
        if self.patient_insurance_id and self.patient_insurance.patient_id != self.patient_id:
            raise ValidationError({"patientInsuranceId": "Insurance policy must belong to this patient."})
        if (
            self.patient_insurance_id
            and self.payer_id
            and self.patient_insurance.payer_id != self.payer_id
        ):
            raise ValidationError({"payerId": "Payer must match the selected insurance policy's payer."})
        if not isinstance(self.diagnosis_code_list, list) or len(self.diagnosis_code_list) > 12:
            raise ValidationError({"diagnosisCodeList": "A claim can carry at most 12 diagnosis codes."})

    @property
    def total_charge_amount(self) -> Decimal:
        return sum((charge.charge_amount for charge in self.charges.all()), Decimal("0.00"))

    @property
    def total_paid(self) -> Decimal:
        """Insurance + patient payments, net of any refunds — computed live
        from ClaimTransaction rows, never stored (same rule as everywhere
        else in this module: a derivable total is not a field)."""
        payments = sum(
            (t.amount for t in self.transactions.all() if t.kind in (ClaimTransaction.Kind.INSURANCE_PAYMENT, ClaimTransaction.Kind.PATIENT_PAYMENT)),
            Decimal("0.00"),
        )
        refunds = sum((t.amount for t in self.transactions.all() if t.kind == ClaimTransaction.Kind.REFUND), Decimal("0.00"))
        return payments - refunds

    @property
    def total_adjusted(self) -> Decimal:
        return sum(
            (t.amount for t in self.transactions.all() if t.kind in (ClaimTransaction.Kind.ADJUSTMENT, ClaimTransaction.Kind.WRITE_OFF)),
            Decimal("0.00"),
        )

    @property
    def balance(self) -> Decimal:
        return self.total_charge_amount - self.total_paid - self.total_adjusted

    def diagnosis_pointers_for(self, charge: "Charge") -> list[str]:
        """CMS-1500 box 24E letters (A-L) for one charge line, derived from
        this claim's stored diagnosis_code_list — never stored per charge."""
        codes_on_charge = {code.code for code in charge.diagnosis_codes.all()}
        return [
            chr(65 + index)
            for index, code in enumerate(self.diagnosis_code_list)
            if code in codes_on_charge
        ]

    def __str__(self) -> str:
        return "%s — %s (%s)" % (self.patient, self.payer, self.get_status_display())


class ClaimTransaction(UUIDTimeStampedModel):
    """One ledger entry against an insurance claim — an ERA/EOB line posted
    manually (no clearinghouse ERA feed is connected yet; see
    care/clearinghouse.py), a patient payment, a contractual adjustment, a
    write-off, a refund, or a balance transfer to a secondary claim. `claim`
    is nullable specifically to model an unmatched payment sitting in a
    reconciliation queue until a biller matches it (see `claim_matched`).
    Cash-pay payments keep using PaymentRecord/Superbill — this model is
    insurance-claim-ledger only, to avoid two competing payment concepts."""

    class Kind(models.TextChoices):
        INSURANCE_PAYMENT = "insurance_payment", "Insurance Payment"
        PATIENT_PAYMENT = "patient_payment", "Patient Payment"
        ADJUSTMENT = "adjustment", "Contractual Adjustment"
        WRITE_OFF = "write_off", "Write-off"
        REFUND = "refund", "Refund"
        TRANSFER = "transfer", "Transfer"

    class Method(models.TextChoices):
        CHECK = "check", "Check"
        EFT = "eft", "EFT"
        CREDIT_CARD = "credit_card", "Credit Card"
        CASH = "cash", "Cash"
        ERA = "era", "ERA (Electronic)"
        OTHER = "other", "Other"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="claim_transactions")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="claim_transactions")
    claim = models.ForeignKey(Claim, on_delete=models.SET_NULL, null=True, blank=True, related_name="transactions")
    transferred_to_claim = models.ForeignKey(
        Claim, on_delete=models.SET_NULL, null=True, blank=True, related_name="incoming_transfers"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    method = models.CharField(max_length=16, choices=Method.choices, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateField(default=timezone.localdate)
    reference = models.CharField(max_length=160, blank=True)
    denial_code = models.CharField(max_length=20, blank=True)
    denial_reason = models.CharField(max_length=240, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="recorded_claim_transactions"
    )

    class Meta:
        ordering = ["-payment_date", "-created_at"]
        indexes = [
            models.Index(fields=["organization", "patient", "payment_date"]),
            models.Index(fields=["claim"]),
        ]

    def clean(self):
        if self.patient_id and self.organization_id and self.patient.organization_id != self.organization_id:
            raise ValidationError({"patient": "Patient must belong to the same organization."})
        if self.claim_id and self.claim.patient_id != self.patient_id:
            raise ValidationError({"claimId": "Claim must belong to this patient."})
        if self.kind == self.Kind.TRANSFER and not self.transferred_to_claim_id:
            raise ValidationError({"transferredToClaimId": "A transfer requires a destination claim."})
        if self.transferred_to_claim_id and self.transferred_to_claim.patient_id != self.patient_id:
            raise ValidationError({"transferredToClaimId": "Destination claim must belong to this patient."})
        if self.transferred_to_claim_id and self.transferred_to_claim_id == self.claim_id:
            raise ValidationError({"transferredToClaimId": "A transfer's destination must be a different claim."})
        if self.amount is not None and self.amount <= 0:
            raise ValidationError({"amount": "Amount must be greater than zero."})

    @property
    def is_matched(self) -> bool:
        return self.claim_id is not None

    def __str__(self) -> str:
        return "%s — %s (%s)" % (self.patient, self.get_kind_display(), self.amount)


class ClaimDenial(UUIDTimeStampedModel):
    """One denial work-queue item for a claim. A claim can be denied more
    than once across resubmission/appeal cycles, so this is a child table,
    not a field on Claim — each row tracks its own owner, follow-up
    deadline, and resolution independently of the claim's own status."""

    class AppealStatus(models.TextChoices):
        NOT_APPEALED = "not_appealed", "Not Appealed"
        PREPARING = "preparing", "Preparing Appeal"
        SUBMITTED = "submitted", "Appeal Submitted"
        WON = "won", "Appeal Won"
        LOST = "lost", "Appeal Lost"

    class Resolution(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED_PAID = "resolved_paid", "Resolved — Paid"
        RESOLVED_WRITTEN_OFF = "resolved_written_off", "Resolved — Written Off"
        RESOLVED_PATIENT_BILLED = "resolved_patient_billed", "Resolved — Billed to Patient"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="claim_denials")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="claim_denials")
    claim = models.ForeignKey(Claim, on_delete=models.PROTECT, related_name="denials")
    denial_code = models.CharField(max_length=20, blank=True)
    denial_reason = models.CharField(max_length=240)
    denied_on = models.DateField(default=timezone.localdate)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="owned_denials"
    )
    due_date = models.DateField(null=True, blank=True)
    action_notes = models.TextField(blank=True)
    appeal_status = models.CharField(max_length=16, choices=AppealStatus.choices, default=AppealStatus.NOT_APPEALED)
    resolution = models.CharField(max_length=24, choices=Resolution.choices, default=Resolution.OPEN)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_denials"
    )

    class Meta:
        ordering = ["resolution", "due_date", "-denied_on"]
        indexes = [models.Index(fields=["organization", "resolution", "due_date"])]

    def clean(self):
        if self.patient_id and self.organization_id and self.patient.organization_id != self.organization_id:
            raise ValidationError({"patient": "Patient must belong to the same organization."})
        if self.claim_id and self.claim.patient_id != self.patient_id:
            raise ValidationError({"claimId": "Claim must belong to this patient."})

    @property
    def is_overdue(self) -> bool:
        return (
            self.resolution == self.Resolution.OPEN
            and self.due_date is not None
            and self.due_date < timezone.localdate()
        )

    def __str__(self) -> str:
        return "%s — %s (%s)" % (self.patient, self.denial_reason, self.get_resolution_display())


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


class PatientPayment(UUIDTimeStampedModel):
    """A patient-initiated online payment attempt through the portal —
    distinct from PaymentRecord (staff manually recording a payment already
    collected out-of-band) and ClaimTransaction (insurance-ledger posting).
    Routed through care/payment_processor.py, the same swap-in-a-real-
    integration seam as ClearinghouseAdapter. Every attempt is kept,
    succeeded or not, for a complete patient-facing payment history —
    insert-only, matching the audit-trail convention of this whole app.
    Never stores card/CVV — see care/payment_processor.py's docstring."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="online_payments")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    processor_reference = models.CharField(max_length=160, blank=True)
    failure_message = models.TextField(blank=True)
    attempted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-attempted_at"]
        indexes = [models.Index(fields=["patient", "-attempted_at"])]

    def clean(self):
        if self.amount is not None and self.amount <= 0:
            raise ValidationError({"amount": "Enter an amount greater than zero."})

    def __str__(self) -> str:
        return f"{self.patient} — ${self.amount} ({self.get_status_display()})"


class ServicePrice(UUIDTimeStampedModel):
    """Org-configurable cash-pay price list — one row per CPT/service, the
    same data-driven-not-hard-coded pattern as Payer. Cash-pay charges look
    up a price here rather than the UI hard-coding a dollar figure."""

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="service_prices")
    cpt_code = models.CharField(max_length=5, validators=[_CPT_CODE_VALIDATOR])
    label = models.CharField(max_length=160)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_service_prices"
    )

    class Meta:
        ordering = ["cpt_code"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "cpt_code"], name="unique_service_price_per_org_cpt")
        ]

    def __str__(self) -> str:
        return "%s — %s (%s)" % (self.cpt_code, self.label, self.price)


class CashPackage(UUIDTimeStampedModel):
    """A pre-paid bundle of visits or a recurring membership sold directly
    to a patient — cash-pay only, no insurance claim involved.
    `visits_included=None` models an unlimited membership; a fixed package
    tracks `visits_used` the same way Authorization tracks visit
    consumption, but this counter is not auto-decremented on note-signing
    (unlike Authorization) since a package purchase is a front-desk/billing
    transaction, not a clinical-authorization one — staff mark usage
    explicitly via `record_visit`."""

    class Kind(models.TextChoices):
        PACKAGE = "package", "Visit Package"
        MEMBERSHIP = "membership", "Membership"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="cash_packages")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="cash_packages")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    name = models.CharField(max_length=160)
    visits_included = models.PositiveSmallIntegerField(null=True, blank=True)
    visits_used = models.PositiveSmallIntegerField(default=0)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    purchased_on = models.DateField(default=timezone.localdate)
    expires_at = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_cash_packages"
    )

    class Meta:
        ordering = ["-purchased_on"]
        indexes = [models.Index(fields=["organization", "patient", "status"])]

    def clean(self):
        if self.patient_id and self.organization_id and self.patient.organization_id != self.organization_id:
            raise ValidationError({"patient": "Patient must belong to the same organization."})
        if self.visits_included is not None and self.visits_used > self.visits_included:
            raise ValidationError({"visitsUsed": "Visits used cannot exceed visits included."})
        if self.discount_percent is not None and not (0 <= self.discount_percent <= 100):
            raise ValidationError({"discountPercent": "Discount must be between 0 and 100 percent."})

    @property
    def visits_remaining(self) -> int | None:
        if self.visits_included is None:
            return None
        return max(0, self.visits_included - self.visits_used)

    @property
    def is_active(self) -> bool:
        if self.status != self.Status.ACTIVE:
            return False
        if self.expires_at and self.expires_at < timezone.localdate():
            return False
        if self.visits_included is not None and self.visits_remaining == 0:
            return False
        return True

    def __str__(self) -> str:
        return "%s — %s" % (self.patient, self.name)


class PatientStatement(UUIDTimeStampedModel):
    """A generated patient billing statement. Only the generation event and
    a balance snapshot are stored — the itemized charges/payments/
    adjustments are rebuilt live from Claim/Charge/ClaimTransaction data at
    view/print time (see billing_services.build_patient_statement_data),
    filtered to activity on or before `statement_date` so a previously
    generated statement's line items stay reproducible even as new
    activity is posted later."""

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="patient_statements")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="statements")
    statement_date = models.DateField(default=timezone.localdate)
    due_date = models.DateField()
    balance_at_generation = models.DecimalField(max_digits=10, decimal_places=2)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="generated_statements"
    )

    class Meta:
        ordering = ["-statement_date"]
        indexes = [models.Index(fields=["organization", "patient", "-statement_date"])]

    def __str__(self) -> str:
        return "%s — statement %s" % (self.patient, self.statement_date)


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
