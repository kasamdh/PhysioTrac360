"""Mobile Care event notifications — in-app, email, and SMS for the
patient's and provider's in-home PT journey.

Reuses this codebase's existing notification infrastructure end to end
rather than building a parallel system:

  - Email: the same best-effort, never-raises send_mail() wrapper pattern
    as care/notifications.py (a transport failure is logged, never
    propagated — it can't block the underlying workflow action).
  - SMS: the same best-effort contract, behind an explicit
    SMS_BACKEND_CONFIGURED gate. No SMS provider is wired into this
    codebase (care/telehealth.py's Twilio note is a *video* integration
    for telehealth calls, not messaging) — this is a real, ready call site
    that currently no-ops rather than a fabricated integration, matching
    the "if existing integration supports it" qualifier in the request.
  - In-app: this app has no separate notification-inbox model. "In-app"
    already means "visible the moment the underlying row changes" — the
    Mobile Care Home dashboard's cards, the Visit Offers tab, the
    provider's Today's Home Visits queue, and the patient portal's request
    stage timeline (all built in earlier Mobile Care work) — so there is
    nothing further to *deliver* for that channel, only to audit.
  - Delivery audit: AuditEvent via record_audit_event(), the same
    append-only trail every other event in this app already uses — not a
    new "NotificationLog" table. One event per (event, channel) attempt,
    recording delivered / failed / skipped_preference / skipped_no_contact
    / skipped_not_configured.

Content policy ("do not include unnecessary PHI"): every message here
names only the practical logistics a patient or provider needs — a date,
a time, a name, "your provider is on the way" — never a diagnosis,
condition, chart note, or other clinical detail. SMS bodies stay to one
short sentence, matching the spec's own example:
"Your physical therapy home visit is scheduled for September 15 at 2:00 PM."
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .mobile_care_settings import is_notification_event_enabled
from .services import record_audit_event

logger = logging.getLogger(__name__)

# No SMS provider is configured in this codebase yet (see module
# docstring). Kept as a module-level constant, not a function, so it reads
# the same way as other "is this optional integration configured" flags
# and so tests can monkeypatch it directly.
SMS_BACKEND_CONFIGURED = bool(getattr(settings, "SMS_ACCOUNT_SID", "") and getattr(settings, "SMS_AUTH_TOKEN", ""))

_AUDIT_ACTION = "MOBILE_CARE_NOTIFICATION"


def _record_delivery(*, event: str, channel: str, status: str, patient, obj=None, django_request=None, recipient: str = "") -> None:
    """`obj` is the specific entity this notification is about (an
    Appointment for a visit reminder, say) when one is more useful for
    later lookup than the patient alone — e.g. send_home_visit_reminders.py
    dedupes "have we already reminded about this appointment" by querying
    for an existing audit row with object_id=appointment.pk. Defaults to
    the patient when no more specific object applies."""
    record_audit_event(
        actor=None,
        action=_AUDIT_ACTION,
        obj=obj if obj is not None else patient,
        patient=patient,
        request=django_request,
        metadata={"event": event, "channel": channel, "status": status, "recipient": recipient},
    )


def _patient_email_address(patient) -> str:
    """Prefer the portal login email (what the patient actually checks to
    sign in) and fall back to the chart's contact email."""
    portal_user = patient.portal_user
    if portal_user is not None and portal_user.email:
        return portal_user.email
    return patient.email


def _send_patient_email(patient, *, event: str, subject: str, body: str, obj=None, django_request=None) -> None:
    if not is_notification_event_enabled(patient.organization, event):
        _record_delivery(event=event, channel="email", status="skipped_org_disabled", patient=patient, obj=obj, django_request=django_request)
        return
    email = _patient_email_address(patient)
    if not email:
        _record_delivery(event=event, channel="email", status="skipped_no_contact", patient=patient, obj=obj, django_request=django_request)
        return
    if not patient.email_notifications_enabled:
        _record_delivery(event=event, channel="email", status="skipped_preference", patient=patient, obj=obj, django_request=django_request)
        return
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False)
        _record_delivery(event=event, channel="email", status="delivered", patient=patient, obj=obj, django_request=django_request, recipient=email)
    except Exception:
        logger.warning("Failed to send Mobile Care %s email to %s", event, email, exc_info=True)
        _record_delivery(event=event, channel="email", status="failed", patient=patient, obj=obj, django_request=django_request, recipient=email)


def _send_patient_sms(patient, *, event: str, body: str, obj=None, django_request=None) -> None:
    if not is_notification_event_enabled(patient.organization, event):
        _record_delivery(event=event, channel="sms", status="skipped_org_disabled", patient=patient, obj=obj, django_request=django_request)
        return
    phone = patient.phone
    if not phone:
        _record_delivery(event=event, channel="sms", status="skipped_no_contact", patient=patient, obj=obj, django_request=django_request)
        return
    if not patient.sms_notifications_enabled:
        _record_delivery(event=event, channel="sms", status="skipped_preference", patient=patient, obj=obj, django_request=django_request)
        return
    if not SMS_BACKEND_CONFIGURED:
        # The one branch a real SMS provider (Twilio, etc.) would replace
        # with an actual send once SMS_BACKEND_CONFIGURED reads real
        # credentials — no provider is configured in this codebase yet
        # (see the module docstring), so this is currently unreachable
        # past this point for every caller.
        logger.info("Mobile Care %s SMS to %s not sent: no SMS provider is configured.", event, phone)
        _record_delivery(event=event, channel="sms", status="skipped_not_configured", patient=patient, obj=obj, django_request=django_request, recipient=phone)
        return


def _record_in_app(patient, *, event: str, obj=None, django_request=None) -> None:
    """Always "delivered" — see module docstring: in-app means "already
    visible in the live dashboard/tab/status the moment the row changed,"
    so there's no separate push step that can fail. Still honors the org's
    Notification Settings toggle (an org can turn an event off entirely,
    not just its email/SMS channels)."""
    if not is_notification_event_enabled(patient.organization, event):
        _record_delivery(event=event, channel="in_app", status="skipped_org_disabled", patient=patient, obj=obj, django_request=django_request)
        return
    _record_delivery(event=event, channel="in_app", status="delivered", patient=patient, obj=obj, django_request=django_request)


def _send_provider_email(provider, *, event: str, subject: str, body: str, patient=None, django_request=None) -> None:
    """No preference gate — this app doesn't extend the same granular
    opt-in/opt-out consent model to staff/provider accounts that it does
    to patients; providers already rely on their account email for every
    other operational notice (invitations, etc.). Still honors the org's
    Notification Settings toggle, same as the patient-facing channels."""
    if not is_notification_event_enabled(provider.organization, event):
        record_audit_event(
            actor=None, action=_AUDIT_ACTION, obj=provider, patient=patient, request=django_request,
            metadata={"event": event, "channel": "email", "status": "skipped_org_disabled", "recipient": ""},
        )
        return
    user = provider.user
    email = user.email if user else ""
    if not email:
        status = "skipped_no_contact"
    else:
        try:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False)
            status = "delivered"
        except Exception:
            logger.warning("Failed to send Mobile Care %s email to provider %s", event, email, exc_info=True)
            status = "failed"
    record_audit_event(
        actor=None,
        action=_AUDIT_ACTION,
        obj=provider,
        patient=patient,
        request=django_request,
        metadata={"event": event, "channel": "email", "status": status, "recipient": email},
    )


def _visit_datetime_phrase(starts_at) -> str:
    """"September 15 at 2:00 PM" — no leading zero on the day or the hour.
    Built field-by-field rather than with a %-d/%-I strftime flag, which
    isn't portable to Windows."""
    local = timezone.localtime(starts_at)
    month_day = local.strftime("%B %d").replace(" 0", " ")
    hour_12 = local.strftime("%I").lstrip("0") or "12"
    return f"{month_day} at {hour_12}:{local.strftime('%M')} {local.strftime('%p')}"


# --- The 11 events -----------------------------------------------------------


def notify_service_request_created(mobile_care_request, *, django_request=None) -> None:
    patient = mobile_care_request.patient
    subject = "We've received your in-home PT request"
    body = (
        f"Hi {patient.first_name},\n\n"
        "We've received your request for an in-home physical therapy visit and are now finding a "
        "therapist who covers your area. We'll let you know as soon as one is matched.\n"
    )
    _send_patient_email(patient, event="SERVICE_REQUEST_CREATED", subject=subject, body=body, django_request=django_request)
    _send_patient_sms(
        patient, event="SERVICE_REQUEST_CREATED",
        body="Your in-home PT request has been received. We're finding a therapist for you.",
        django_request=django_request,
    )
    _record_in_app(patient, event="SERVICE_REQUEST_CREATED", django_request=django_request)


def notify_provider_match_found(mobile_care_request, *, django_request=None) -> None:
    """In-app/audit only — candidates being identified isn't a confirmed
    match yet, so nothing is emailed or texted to the patient (that would
    be a premature "you're matched" signal ahead of the real one below)."""
    _record_in_app(mobile_care_request.patient, event="PROVIDER_MATCH_FOUND", django_request=django_request)


def notify_provider_offer_created(provider_match, *, django_request=None) -> None:
    provider = provider_match.provider
    subject = "New home visit offer"
    body = (
        f"Hi {provider.first_name},\n\n"
        "You have a new in-home PT visit offer waiting for your response. Sign in to Source Motion PT "
        "to accept or decline:\n\n"
        f"{settings.FRONTEND_BASE_URL}\n"
    )
    _send_provider_email(
        provider, event="PROVIDER_OFFER_CREATED", subject=subject, body=body,
        patient=provider_match.service_request.patient, django_request=django_request,
    )


def notify_provider_offer_accepted(provider_match, *, django_request=None) -> None:
    service_request = provider_match.service_request
    patient = service_request.patient
    provider = provider_match.provider
    subject = "A therapist has been matched to your request"
    body = (
        f"Hi {patient.first_name},\n\n"
        f"{provider.first_name} {provider.last_name}{f', {provider.credentials}' if provider.credentials else ''} "
        "has been matched to your in-home PT request. We'll follow up shortly to confirm a visit time.\n"
    )
    _send_patient_email(patient, event="PROVIDER_OFFER_ACCEPTED", subject=subject, body=body, django_request=django_request)
    _send_patient_sms(
        patient, event="PROVIDER_OFFER_ACCEPTED",
        body=f"{provider.first_name} {provider.last_name} has been matched to your in-home PT request.",
        django_request=django_request,
    )
    _record_in_app(patient, event="PROVIDER_OFFER_ACCEPTED", django_request=django_request)


def notify_provider_offer_declined(provider_match, *, django_request=None) -> None:
    """In-app/audit only — an individual candidate declining is an
    operational detail for staff/matching, not something the patient needs
    a push about; they simply keep seeing "Finding Therapist" until the
    next offer is accepted."""
    _record_in_app(provider_match.service_request.patient, event="PROVIDER_OFFER_DECLINED", django_request=django_request)


def notify_visit_scheduled(appointment, *, mobile_care_request, django_request=None) -> None:
    patient = mobile_care_request.patient
    when = _visit_datetime_phrase(appointment.starts_at)
    provider_name = str(appointment.provider) if appointment.provider_id else appointment.therapist.get_full_name()
    subject = "Your in-home PT visit is scheduled"
    body = (
        f"Hi {patient.first_name},\n\n"
        f"Your physical therapy home visit is scheduled for {when} with {provider_name}.\n"
    )
    _send_patient_email(patient, event="VISIT_SCHEDULED", subject=subject, body=body, obj=appointment, django_request=django_request)
    _send_patient_sms(
        patient, event="VISIT_SCHEDULED",
        body=f"Your physical therapy home visit is scheduled for {when}.",
        obj=appointment, django_request=django_request,
    )
    _record_in_app(patient, event="VISIT_SCHEDULED", obj=appointment, django_request=django_request)
    if appointment.provider_id:
        provider = appointment.provider
        _send_provider_email(
            provider, event="VISIT_SCHEDULED",
            subject="Home visit confirmed on your schedule",
            body=f"Hi {provider.first_name},\n\nA home visit has been scheduled for {when}. Check Source Motion PT for details.\n",
            patient=patient, django_request=django_request,
        )


def reminder_already_sent(appointment) -> bool:
    """Dedup check for send_home_visit_reminders.py — has this appointment
    already gotten a VISIT_REMINDER audit record? Uses the same AuditEvent
    trail as delivery, rather than a new "reminder_sent_at" column."""
    from .models import AuditEvent

    return AuditEvent.objects.filter(
        action=_AUDIT_ACTION, object_id=appointment.pk, metadata__event="VISIT_REMINDER",
    ).exists()


def notify_visit_reminder(appointment, *, mobile_care_request, django_request=None) -> None:
    """Not called inline — dispatched by the periodic
    care/management/commands/send_home_visit_reminders.py sweep, the same
    "does not schedule itself" pattern as check_license_expirations.py /
    expire_stale_provider_offers.py. That command calls
    reminder_already_sent() first so this never double-sends."""
    patient = mobile_care_request.patient
    when = _visit_datetime_phrase(appointment.starts_at)
    subject = "Reminder: your in-home PT visit is tomorrow"
    body = f"Hi {patient.first_name},\n\nThis is a reminder that your physical therapy home visit is scheduled for {when}.\n"
    _send_patient_email(patient, event="VISIT_REMINDER", subject=subject, body=body, obj=appointment, django_request=django_request)
    _send_patient_sms(
        patient, event="VISIT_REMINDER",
        body=f"Reminder: your physical therapy home visit is scheduled for {when}.",
        obj=appointment, django_request=django_request,
    )
    _record_in_app(patient, event="VISIT_REMINDER", obj=appointment, django_request=django_request)


def notify_provider_en_route(assignment, *, django_request=None) -> None:
    patient = assignment.service_request.patient
    _send_patient_sms(
        patient, event="PROVIDER_EN_ROUTE",
        body=f"{assignment.provider.first_name} is on the way to your home visit.",
        django_request=django_request,
    )
    _send_patient_email(
        patient, event="PROVIDER_EN_ROUTE",
        subject="Your provider is on the way",
        body=f"Hi {patient.first_name},\n\n{assignment.provider.first_name} {assignment.provider.last_name} is on the way to your home visit.\n",
        django_request=django_request,
    )
    _record_in_app(patient, event="PROVIDER_EN_ROUTE", django_request=django_request)


def notify_provider_arrived(assignment, *, django_request=None) -> None:
    """SMS/email are intentionally skipped by default here — the provider
    is physically at the door, so a push notification is rarely useful and
    would often arrive after the fact; this is recorded as an in-app/audit
    event only. Kept as its own function (not folded into en_route) so the
    audit trail — and a future preference to enable it — are both
    per-event, matching the other ten."""
    _record_in_app(assignment.service_request.patient, event="PROVIDER_ARRIVED", django_request=django_request)


def notify_visit_completed(assignment, *, django_request=None) -> None:
    patient = assignment.service_request.patient
    subject = "Your in-home PT visit is complete"
    body = f"Hi {patient.first_name},\n\nYour physical therapy home visit is complete. Thank you!\n"
    _send_patient_email(patient, event="VISIT_COMPLETED", subject=subject, body=body, django_request=django_request)
    _send_patient_sms(patient, event="VISIT_COMPLETED", body="Your physical therapy home visit is complete. Thank you!", django_request=django_request)
    _record_in_app(patient, event="VISIT_COMPLETED", django_request=django_request)


def notify_visit_cancelled(mobile_care_request, *, reason: str = "", django_request=None) -> None:
    patient = mobile_care_request.patient
    subject = "Your in-home PT visit has been cancelled"
    body = f"Hi {patient.first_name},\n\nYour in-home physical therapy request has been cancelled.\n"
    _send_patient_email(patient, event="VISIT_CANCELLED", subject=subject, body=body, django_request=django_request)
    _send_patient_sms(patient, event="VISIT_CANCELLED", body="Your in-home PT visit has been cancelled.", django_request=django_request)
    _record_in_app(patient, event="VISIT_CANCELLED", django_request=django_request)
    if mobile_care_request.matched_provider_id:
        provider = mobile_care_request.matched_provider
        _send_provider_email(
            provider, event="VISIT_CANCELLED",
            subject="A home visit has been cancelled",
            body=f"Hi {provider.first_name},\n\nA home visit on your schedule has been cancelled. Check Source Motion PT for details.\n",
            patient=patient, django_request=django_request,
        )
