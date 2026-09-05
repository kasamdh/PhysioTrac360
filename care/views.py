"""Authenticated clinical workspace views."""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.conf import settings
from django.http import FileResponse, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from .access import (
    BILLING_ROLES,
    CLINICAL_ROLES,
    PAYMENT_COLLECTION_ROLES,
    SCHEDULING_ROLES,
    organization_required,
    patients_for,
    require_patient_access,
    require_role,
)
from .forms import (
    AccessPasswordResetForm,
    AccessUserCreateForm,
    AccessUserUpdateForm,
    AppointmentForm,
    ClinicalNoteForm,
    ConsentForm,
    EmployeeOnboardingForm,
    FunctionalGoalForm,
    FacilitySettingsForm,
    HomeProgramForm,
    IntakeCaptureForm,
    NoteAddendumForm,
    OutcomeScoreForm,
    PaymentRecordForm,
    PatientForm,
    SecureMessageForm,
    SuperbillForm,
    VoiceCaptureForm,
)
from .models import (
    AIArtifact,
    Appointment,
    AuditEvent,
    ClinicalNote,
    Consent,
    FunctionalGoal,
    HomeProgram,
    IntakeSubmission,
    NoteAddendum,
    OutcomeScore,
    PaymentRecord,
    Patient,
    SecureMessage,
    Superbill,
    User,
    VoiceCapture,
)
from .services import (
    compose_draft,
    goal_suggestions,
    home_program_suggestions,
    note_compliance_findings,
    outcome_trends,
    patient_compliance_findings,
    record_audit_event,
)


ROLE_CAPABILITIES = [
    {
        "role": User.Role.ADMIN,
        "label": "Organization administrator",
        "summary": "Oversee clinic operations; platform super administrators provision user accounts.",
    },
    {
        "role": User.Role.DIRECTOR,
        "label": "Clinical director",
        "summary": "Access clinical charts across the organization and approve/sign clinical work.",
    },
    {
        "role": User.Role.THERAPIST,
        "label": "Physical therapist",
        "summary": "Access assigned charts, document visits, approve goals, and sign own notes.",
    },
    {
        "role": User.Role.ASSISTANT,
        "label": "PTA / therapy assistant",
        "summary": "Access assigned charts and draft clinical documentation; cannot finalize notes.",
    },
    {
        "role": User.Role.SCHEDULER,
        "label": "Front desk / office admin",
        "summary": "Manage demographics, appointments, intake, and consent without clinical narratives.",
    },
    {
        "role": User.Role.BILLER,
        "label": "Billing specialist",
        "summary": "Access billing records and the minimum demographic data required for reimbursement.",
    },
    {
        "role": User.Role.COMPLIANCE,
        "label": "Compliance officer",
        "summary": "Review clinical records and audit history for authorized oversight activities.",
    },
    {
        "role": User.Role.PATIENT,
        "label": "Patient portal user",
        "summary": "Reserved for a separate, limited patient portal experience.",
    },
]

CLINICAL_ACCESS_ROLES = {
    User.Role.ADMIN,
    User.Role.DIRECTOR,
    User.Role.THERAPIST,
    User.Role.ASSISTANT,
    User.Role.COMPLIANCE,
}
ASSIGNED_CLINICIAN_ROLES = {User.Role.THERAPIST, User.Role.ASSISTANT}


class SecureLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["username"].widget.attrs.update(
            {"class": "field-input", "autocomplete": "username"}
        )
        form.fields["password"].widget.attrs.update(
            {"class": "field-input", "autocomplete": "current-password"}
        )
        return form


def react_workspace(request: HttpRequest) -> HttpResponse:
    """Serve the built React shell; JSON APIs still enforce all data access."""
    index_path = settings.FRONTEND_DIST_DIR / "index.html"
    if not index_path.exists():
        return HttpResponse(
            "React workspace is not built. Run npm.cmd run build in PhysioTrac360/frontend/.",
            status=503,
            content_type="text/plain; charset=utf-8",
        )
    return FileResponse(index_path.open("rb"), content_type="text/html; charset=utf-8")


def _patient_or_404(request: HttpRequest, patient_id: str, *, clinical: bool = True) -> Patient:
    patient = get_object_or_404(Patient, pk=patient_id)
    return require_patient_access(request, patient, clinical=clinical)


def _clinical_access(user):
    require_role(user, CLINICAL_ROLES)
    organization_required(user)


def _can_finalize_for(user, note: ClinicalNote) -> bool:
    if user.role in {User.Role.ADMIN, User.Role.DIRECTOR}:
        return True
    return user.can_sign_notes and note.therapist_id == user.id


def _can_edit_note(user, note: ClinicalNote) -> bool:
    if note.is_signed:
        return False
    if user.role in {User.Role.ADMIN, User.Role.DIRECTOR}:
        return True
    return note.therapist_id == user.id


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    if request.user.is_platform_super_admin:
        return redirect("react-workspace")
    organization = organization_required(request.user)
    today = timezone.localdate()
    appointments = Appointment.objects.filter(
        patient__organization=organization, starts_at__date=today
    ).select_related("patient", "therapist")
    if request.user.role in {User.Role.THERAPIST, User.Role.ASSISTANT}:
        appointments = appointments.filter(therapist=request.user)

    clinical_patients = patients_for(request.user, clinical=True)
    pending_notes = ClinicalNote.objects.filter(
        patient__in=clinical_patients
    ).exclude(status=ClinicalNote.Status.SIGNED)
    due_notes = ClinicalNote.objects.filter(
        patient__in=clinical_patients,
        reassessment_due__isnull=False,
        reassessment_due__lte=today + timedelta(days=7),
    ).exclude(status=ClinicalNote.Status.SIGNED)
    patient_alerts = []
    for patient in clinical_patients[:30]:
        for finding in patient_compliance_findings(patient):
            patient_alerts.append({"patient": patient, "finding": finding})
    unread_messages = SecureMessage.objects.filter(recipient=request.user, read_at__isnull=True)

    context = {
        "today": today,
        "appointments": appointments[:12],
        "appointment_count": appointments.count(),
        "pending_notes": pending_notes[:6],
        "pending_note_count": pending_notes.count(),
        "due_notes": due_notes[:6],
        "due_note_count": due_notes.count(),
        "patient_alerts": patient_alerts[:6],
        "unread_message_count": unread_messages.count(),
        "ai_drafts": AIArtifact.objects.filter(
            patient__in=clinical_patients, status=AIArtifact.Status.DRAFT
        )[:5],
    }
    return render(request, "care/dashboard.html", context)


@login_required
def patient_list(request: HttpRequest) -> HttpResponse:
    organization_required(request.user)
    if request.user.role in CLINICAL_ROLES:
        queryset = patients_for(request.user, clinical=True)
    else:
        require_role(request.user, SCHEDULING_ROLES | BILLING_ROLES)
        queryset = patients_for(request.user, clinical=False)
    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(medical_record_number__icontains=query)
        )
    return render(
        request,
        "care/patient_list.html",
        {"patients": queryset.select_related("assigned_therapist"), "query": query},
    )


@login_required
@require_http_methods(["GET", "POST"])
def patient_create(request: HttpRequest) -> HttpResponse:
    require_role(request.user, SCHEDULING_ROLES)
    organization = organization_required(request.user)
    form = PatientForm(
        request.POST or None,
        organization=organization,
    )
    if request.method == "POST" and form.is_valid():
        patient = form.save(commit=False)
        patient.organization = organization
        patient.full_clean()
        patient.save()
        record_audit_event(
            actor=request.user,
            action="patient.created",
            obj=patient,
            patient=patient,
            request=request,
        )
        messages.success(request, "Patient chart created.")
        if request.user.can_access_clinical:
            return redirect("patient-detail", patient_id=patient.pk)
        return redirect("patient-list")
    return render(request, "care/form_page.html", {"form": form, "title": "New patient"})


@login_required
def patient_detail(request: HttpRequest, patient_id: str) -> HttpResponse:
    _clinical_access(request.user)
    patient = _patient_or_404(request, patient_id)
    record_audit_event(
        actor=request.user,
        action="patient.viewed",
        obj=patient,
        patient=patient,
        request=request,
        metadata={"route": "patient-detail"},
    )
    notes = patient.notes.select_related("therapist").all()[:8]
    outcomes = outcome_trends(patient)
    timeline = []
    for note in notes[:5]:
        timeline.append(
            {
                "date": note.service_date,
                "kind": note.get_note_type_display(),
                "detail": note.get_status_display(),
                "url": reverse("note-edit", kwargs={"note_id": note.pk}),
            }
        )
    for score in patient.outcomes.all()[:5]:
        timeline.append(
            {
                "date": score.measured_on,
                "kind": score.get_measure_display(),
                "detail": "Outcome score: %s" % score.score,
                "url": None,
            }
        )
    timeline.sort(key=lambda event: event["date"], reverse=True)
    context = {
        "patient": patient,
        "notes": notes,
        "goals": patient.goals.select_related("approved_by").all()[:8],
        "outcomes": outcomes,
        "appointments": patient.appointments.select_related("therapist").all()[:6],
        "compliance_findings": patient_compliance_findings(patient),
        "timeline": timeline[:8],
        "ai_artifacts": patient.ai_artifacts.select_related("requested_by").all()[:6],
        "home_programs": patient.home_programs.select_related("prescribed_by").all()[:4],
        "voice_captures": patient.voice_captures.select_related("therapist").all()[:3],
        "recent_audits": patient.audit_events.select_related("actor").all()[:6],
        "consents": patient.consents.select_related("recorded_by").all()[:4],
        "intakes": patient.intakes.select_related("reviewed_by").all()[:3],
    }
    return render(request, "care/patient_detail.html", context)


@login_required
def schedule(request: HttpRequest) -> HttpResponse:
    require_role(request.user, SCHEDULING_ROLES)
    organization = organization_required(request.user)
    today = timezone.localdate()
    requested_day = request.GET.get("day")
    if requested_day:
        try:
            selected_day = datetime.strptime(requested_day, "%Y-%m-%d").date()
        except ValueError:
            selected_day = today
    else:
        selected_day = today

    requested_month = request.GET.get("month")
    if requested_month:
        try:
            month_start = datetime.strptime(requested_month, "%Y-%m").date().replace(day=1)
        except ValueError:
            month_start = selected_day.replace(day=1)
    else:
        month_start = selected_day.replace(day=1)

    if selected_day.year != month_start.year or selected_day.month != month_start.month:
        selected_day = month_start

    calendar_weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(
        month_start.year, month_start.month
    )
    visible_start = calendar_weeks[0][0]
    visible_end = calendar_weeks[-1][-1]
    visible_appointments = Appointment.objects.filter(
        patient__organization=organization,
        starts_at__date__gte=visible_start,
        starts_at__date__lte=visible_end,
    ).select_related("patient", "therapist")
    if request.user.role in {User.Role.THERAPIST, User.Role.ASSISTANT}:
        visible_appointments = visible_appointments.filter(therapist=request.user)

    appointments_by_day = defaultdict(list)
    for appointment in visible_appointments:
        appointment_day = timezone.localtime(appointment.starts_at).date()
        appointments_by_day[appointment_day].append(appointment)

    month_grid = []
    for week in calendar_weeks:
        cells = []
        for calendar_day in week:
            day_appointments = appointments_by_day.get(calendar_day, [])
            cells.append(
                {
                    "date": calendar_day,
                    "appointments": day_appointments[:3],
                    "additional_count": max(0, len(day_appointments) - 3),
                    "in_current_month": calendar_day.month == month_start.month,
                    "is_today": calendar_day == today,
                    "is_selected": calendar_day == selected_day,
                }
            )
        month_grid.append(cells)

    previous_month = _shift_month(month_start, -1)
    next_month = _shift_month(month_start, 1)
    return render(
        request,
        "care/schedule.html",
        {
            "appointments": appointments_by_day.get(selected_day, []),
            "calendar_weeks": month_grid,
            "calendar_month": month_start,
            "selected_day": selected_day,
            "today": today,
            "previous_month": previous_month,
            "next_month": next_month,
            "previous_selected_day": _day_in_month(previous_month, selected_day.day),
            "next_selected_day": _day_in_month(next_month, selected_day.day),
        },
    )


def _shift_month(month_start: date, offset: int) -> date:
    """Return the first day of the month offset from month_start."""
    month_index = month_start.month - 1 + offset
    year = month_start.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _day_in_month(month_start: date, preferred_day: int) -> date:
    """Keep calendar navigation on a comparable day when a month is shorter."""
    last_day = calendar.monthrange(month_start.year, month_start.month)[1]
    return month_start.replace(day=min(preferred_day, last_day))


@login_required
@require_http_methods(["GET", "POST"])
def appointment_create(request: HttpRequest) -> HttpResponse:
    require_role(request.user, SCHEDULING_ROLES)
    organization = organization_required(request.user)
    form = AppointmentForm(
        request.POST or None,
        organization=organization,
        patient_queryset=patients_for(request.user, clinical=False),
    )
    if request.method == "POST" and form.is_valid():
        appointment = form.save(commit=False)
        appointment.created_by = request.user
        with transaction.atomic():
            therapist_conflict = (
                Appointment.objects.select_for_update()
                .filter(
                    therapist=appointment.therapist,
                    starts_at__lt=appointment.ends_at,
                    ends_at__gt=appointment.starts_at,
                )
                .exclude(status__in=[Appointment.Status.CANCELLED, Appointment.Status.NO_SHOW])
                .exists()
            )
            if therapist_conflict:
                form.add_error(None, "The assigned clinician already has an appointment at that time.")
                return render(
                    request, "care/form_page.html", {"form": form, "title": "Schedule appointment"}
                )
            appointment.full_clean()
            appointment.save()
        record_audit_event(
            actor=request.user,
            action="appointment.created",
            obj=appointment,
            patient=appointment.patient,
            request=request,
        )
        messages.success(request, "Appointment scheduled.")
        return redirect("schedule")
    return render(
        request, "care/form_page.html", {"form": form, "title": "Schedule appointment"}
    )


@login_required
@require_POST
def appointment_move(request: HttpRequest, appointment_id: str) -> JsonResponse:
    """Reschedule a visit or cancel it with server-side conflict checks."""
    require_role(request.user, SCHEDULING_ROLES)
    organization = organization_required(request.user)
    action = request.POST.get("action", "reschedule")
    if action == "cancel":
        with transaction.atomic():
            appointments = Appointment.objects.select_for_update().select_related(
                "patient", "therapist"
            ).filter(pk=appointment_id, patient__organization=organization)
            if request.user.role in {User.Role.THERAPIST, User.Role.ASSISTANT}:
                appointments = appointments.filter(therapist=request.user)
            appointment = get_object_or_404(appointments)
            if appointment.status != Appointment.Status.SCHEDULED:
                return JsonResponse({"detail": "Only scheduled appointments can be cancelled."}, status=409)
            appointment.status = Appointment.Status.CANCELLED
            appointment.full_clean()
            appointment.save(update_fields=["status", "updated_at"])
            record_audit_event(
                actor=request.user,
                action="appointment.cancelled",
                obj=appointment,
                patient=appointment.patient,
                request=request,
                metadata={"source": "calendar"},
            )
        return JsonResponse({"cancelled": True, "detail": "Appointment cancelled."})

    target_date_value = request.POST.get("target_date", "")
    target_start_value = request.POST.get("target_start", "")
    try:
        target_date = datetime.strptime(target_date_value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return JsonResponse(
            {"detail": "Choose a valid calendar date to move this appointment."},
            status=400,
        )

    with transaction.atomic():
        appointments = Appointment.objects.select_for_update().select_related(
            "patient", "therapist"
        ).filter(pk=appointment_id, patient__organization=organization)
        if request.user.role in {User.Role.THERAPIST, User.Role.ASSISTANT}:
            appointments = appointments.filter(therapist=request.user)
        appointment = get_object_or_404(appointments)

        if appointment.status != Appointment.Status.SCHEDULED:
            return JsonResponse(
                {"detail": "Only scheduled appointments can be moved."}, status=409
            )
        if ClinicalNote.objects.filter(appointment=appointment).exists():
            return JsonResponse(
                {
                    "detail": (
                        "This appointment is linked to documentation and cannot be moved. "
                        "Review the appointment and note together."
                    )
                },
                status=409,
            )

        current_local_start = timezone.localtime(appointment.starts_at)
        if target_start_value:
            target_local_start = parse_datetime(target_start_value)
            if not target_local_start:
                return JsonResponse({"detail": "Choose a valid appointment date and time."}, status=400)
            if timezone.is_naive(target_local_start):
                target_local_start = timezone.make_aware(
                    target_local_start, timezone.get_current_timezone()
                )
        else:
            target_local_start = timezone.make_aware(
                datetime.combine(target_date, current_local_start.time()),
                timezone.get_current_timezone(),
            )
        target_date = timezone.localtime(target_local_start).date()
        if appointment.starts_at == target_local_start:
            return JsonResponse(
                {
                    "moved": False,
                    "detail": "This appointment is already scheduled at that time.",
                }
            )

        old_starts_at = appointment.starts_at
        old_ends_at = appointment.ends_at
        duration = old_ends_at - old_starts_at
        target_end = target_local_start + duration

        therapist_conflict = (
            Appointment.objects.select_for_update()
            .filter(
                therapist=appointment.therapist,
                starts_at__lt=target_end,
                ends_at__gt=target_local_start,
            )
            .exclude(pk=appointment.pk)
            .exclude(
                status__in=[Appointment.Status.CANCELLED, Appointment.Status.NO_SHOW]
            )
            .exists()
        )
        if therapist_conflict:
            return JsonResponse(
                {
                    "detail": (
                        "The assigned clinician already has an appointment at that time. "
                        "Choose another date or update the appointment details."
                    )
                },
                status=409,
            )

        appointment.starts_at = target_local_start
        appointment.ends_at = target_end
        appointment.full_clean()
        appointment.save(update_fields=["starts_at", "ends_at", "updated_at"])
        record_audit_event(
            actor=request.user,
            action="appointment.rescheduled",
            obj=appointment,
            patient=appointment.patient,
            request=request,
            metadata={
                "old_starts_at": old_starts_at.isoformat(),
                "old_ends_at": old_ends_at.isoformat(),
                "new_starts_at": appointment.starts_at.isoformat(),
                "new_ends_at": appointment.ends_at.isoformat(),
                "source": "calendar",
            },
        )

    return JsonResponse(
        {
            "moved": True,
            "detail": "Appointment moved.",
            "redirect_url": (
                f"{reverse('schedule')}?month={target_date:%Y-%m}&day={target_date:%Y-%m-%d}"
            ),
        }
    )


@login_required
@require_http_methods(["GET", "POST"])
def note_create(request: HttpRequest, patient_id: str) -> HttpResponse:
    _clinical_access(request.user)
    patient = _patient_or_404(request, patient_id)
    voice_capture = None
    voice_id = request.GET.get("voice")
    if voice_id:
        voice_capture = get_object_or_404(
            VoiceCapture.objects.filter(patient=patient, therapist=request.user), pk=voice_id
        )
    initial = {}
    if voice_capture:
        initial["subjective"] = voice_capture.transcript
    form = ClinicalNoteForm(
        request.POST or None,
        patient=patient,
        initial=initial,
    )
    if request.method == "POST" and form.is_valid():
        note = form.save(commit=False)
        note.patient = patient
        note.therapist = request.user
        note.full_clean()
        note.save()
        if voice_capture:
            voice_capture.linked_note = note
            voice_capture.status = VoiceCapture.Status.REVIEWED
            voice_capture.save(update_fields=["linked_note", "status", "updated_at"])
        record_audit_event(
            actor=request.user,
            action="note.created",
            obj=note,
            patient=patient,
            request=request,
            metadata={"note_type": note.note_type},
        )
        messages.success(request, "Clinical note saved as a draft.")
        return redirect("note-edit", note_id=note.pk)
    return render(
        request,
        "care/note_form.html",
        {
            "form": form,
            "patient": patient,
            "note": None,
            "voice_capture": voice_capture,
            "compliance_findings": [],
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def note_edit(request: HttpRequest, note_id: str) -> HttpResponse:
    note = get_object_or_404(ClinicalNote.objects.select_related("patient", "therapist"), pk=note_id)
    _clinical_access(request.user)
    require_patient_access(request, note.patient)
    if note.is_signed:
        if request.method != "GET":
            raise PermissionDenied("Signed notes are locked. Create an addendum for corrections.")
        record_audit_event(
            actor=request.user,
            action="note.viewed",
            obj=note,
            patient=note.patient,
            request=request,
            metadata={"status": note.status},
        )
        return render(
            request,
            "care/note_form.html",
            {
                "form": None,
                "patient": note.patient,
                "note": note,
                "voice_capture": None,
                "compliance_findings": [],
            },
        )
    if not _can_edit_note(request.user, note):
        raise PermissionDenied("Signed notes are locked or this note belongs to another clinician.")
    form = ClinicalNoteForm(request.POST or None, instance=note, patient=note.patient)
    if request.method == "POST" and form.is_valid():
        note = form.save(commit=False)
        if request.POST.get("submit_for_review"):
            note.status = ClinicalNote.Status.REVIEW_REQUIRED
        note.full_clean()
        note.save()
        record_audit_event(
            actor=request.user,
            action="note.updated",
            obj=note,
            patient=note.patient,
            request=request,
            metadata={"status": note.status},
        )
        messages.success(
            request,
            "Note submitted for review." if note.status == ClinicalNote.Status.REVIEW_REQUIRED else "Draft saved.",
        )
        return redirect("note-edit", note_id=note.pk)
    return render(
        request,
        "care/note_form.html",
        {
            "form": form,
            "patient": note.patient,
            "note": note,
            "voice_capture": None,
            "compliance_findings": note_compliance_findings(note),
        },
    )


@login_required
@require_POST
def note_sign(request: HttpRequest, note_id: str) -> HttpResponse:
    note = get_object_or_404(ClinicalNote.objects.select_related("patient", "therapist"), pk=note_id)
    _clinical_access(request.user)
    require_patient_access(request, note.patient)
    if not _can_finalize_for(request.user, note):
        raise PermissionDenied("Only the treating therapist or an authorized director may finalize this note.")
    if request.POST.get("attestation") != "confirmed":
        messages.error(
            request,
            "Confirm therapist review and attestation before finalizing this note.",
        )
        return redirect("note-edit", note_id=note.pk)
    findings = note_compliance_findings(note)
    blockers = [finding for finding in findings if finding.finalization_blocker]
    if blockers:
        messages.error(
            request,
            "Note cannot be finalized until required documentation checks are resolved.",
        )
        return redirect("note-edit", note_id=note.pk)
    note.signature_name = request.user.get_full_name() or request.user.username
    note.signed_at = timezone.now()
    note.finalization_attestation = True
    note.status = ClinicalNote.Status.SIGNED
    note.full_clean()
    note.save()
    record_audit_event(
        actor=request.user,
        action="note.signed",
        obj=note,
        patient=note.patient,
        request=request,
        metadata={"note_type": note.note_type},
    )
    messages.success(request, "Note finalized and locked. Use an addendum for later corrections.")
    return redirect("patient-detail", patient_id=note.patient_id)


@login_required
@require_http_methods(["GET", "POST"])
def note_addendum_create(request: HttpRequest, note_id: str) -> HttpResponse:
    note = get_object_or_404(
        ClinicalNote.objects.select_related("patient", "therapist"),
        pk=note_id,
    )
    _clinical_access(request.user)
    require_patient_access(request, note.patient)
    if not note.is_signed:
        raise PermissionDenied("An addendum can only be created for a signed note.")
    if not _can_finalize_for(request.user, note):
        raise PermissionDenied("Only an authorized therapist can create this addendum.")
    form = NoteAddendumForm(
        request.POST or None,
        instance=NoteAddendum(note=note, author=request.user),
    )
    if request.method == "POST" and form.is_valid():
        addendum = form.save(commit=False)
        addendum.note = note
        addendum.author = request.user
        addendum.full_clean()
        addendum.save()
        record_audit_event(
            actor=request.user,
            action="note.addendum_created",
            obj=addendum,
            patient=note.patient,
            request=request,
            metadata={"note_id": str(note.pk)},
        )
        messages.success(request, "Addendum saved without changing the signed original.")
        return redirect("note-edit", note_id=note.pk)
    return render(
        request,
        "care/form_page.html",
        {
            "form": form,
            "title": "Addendum to signed note",
            "patient": note.patient,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def goal_suggestion_view(request: HttpRequest, patient_id: str) -> HttpResponse:
    _clinical_access(request.user)
    patient = _patient_or_404(request, patient_id)
    suggestions = []
    limitation = request.POST.get("functional_limitation", "").strip()
    measure = request.POST.get("measure", "")
    if request.method == "POST" and limitation:
        suggestions = goal_suggestions(limitation, patient.diagnoses, measure)
        record_audit_event(
            actor=request.user,
            action="goal.suggestions_requested",
            obj=patient,
            patient=patient,
            request=request,
            metadata={"measure": measure or "none"},
        )
    return render(
        request,
        "care/goal_suggestions.html",
        {
            "patient": patient,
            "suggestions": suggestions,
            "limitation": limitation,
            "measure_choices": OutcomeScore.Measure.choices,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def goal_create(request: HttpRequest, patient_id: str) -> HttpResponse:
    _clinical_access(request.user)
    patient = _patient_or_404(request, patient_id)
    initial = {
        "functional_limitation": request.GET.get("functional_limitation", ""),
        "functional_task": request.GET.get("functional_task", ""),
        "measurement_method": request.GET.get("measurement_method", ""),
        "suggested_wording": request.GET.get("suggested_wording", ""),
    }
    form = FunctionalGoalForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        goal = form.save(commit=False)
        goal.patient = patient
        goal.author = request.user
        goal.status = FunctionalGoal.Status.DRAFT
        goal.full_clean()
        goal.save()
        record_audit_event(
            actor=request.user,
            action="goal.created_draft",
            obj=goal,
            patient=patient,
            request=request,
        )
        messages.success(request, "Measurable goal saved as a draft for clinician approval.")
        return redirect("patient-detail", patient_id=patient.pk)
    return render(
        request,
        "care/form_page.html",
        {"form": form, "title": "Create measurable functional goal", "patient": patient},
    )


@login_required
@require_POST
def goal_approve(request: HttpRequest, goal_id: str) -> HttpResponse:
    goal = get_object_or_404(FunctionalGoal.objects.select_related("patient"), pk=goal_id)
    _clinical_access(request.user)
    require_patient_access(request, goal.patient)
    if not request.user.can_sign_notes:
        raise PermissionDenied("Only an authorized therapist can approve a clinical goal.")
    goal.status = FunctionalGoal.Status.ACTIVE
    goal.approved_by = request.user
    goal.approved_at = timezone.now()
    goal.full_clean()
    goal.save()
    record_audit_event(
        actor=request.user,
        action="goal.approved",
        obj=goal,
        patient=goal.patient,
        request=request,
    )
    messages.success(request, "Goal approved and activated.")
    return redirect("patient-detail", patient_id=goal.patient_id)


@login_required
@require_http_methods(["GET", "POST"])
def outcome_list(request: HttpRequest, patient_id: str) -> HttpResponse:
    _clinical_access(request.user)
    patient = _patient_or_404(request, patient_id)
    form = OutcomeScoreForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        score = form.save(commit=False)
        score.patient = patient
        score.recorded_by = request.user
        score.full_clean()
        score.save()
        record_audit_event(
            actor=request.user,
            action="outcome.recorded",
            obj=score,
            patient=patient,
            request=request,
            metadata={"measure": score.measure},
        )
        messages.success(request, "Outcome score recorded. Trend updated.")
        return redirect("outcomes", patient_id=patient.pk)
    return render(
        request,
        "care/outcomes.html",
        {
            "patient": patient,
            "form": form,
            "trends": outcome_trends(patient),
            "scores": patient.outcomes.all(),
        },
    )


@login_required
@require_POST
def draft_create(request: HttpRequest, patient_id: str) -> HttpResponse:
    _clinical_access(request.user)
    patient = _patient_or_404(request, patient_id)
    kind = request.POST.get("kind", AIArtifact.Kind.PROGRESS)
    allowed_kinds = {
        AIArtifact.Kind.PROGRESS,
        AIArtifact.Kind.DISCHARGE,
        AIArtifact.Kind.HANDOFF,
        AIArtifact.Kind.PATIENT_SUMMARY,
    }
    if kind not in allowed_kinds:
        raise PermissionDenied("Unsupported draft type.")
    payload = compose_draft(patient, kind)
    artifact = AIArtifact.objects.create(
        patient=patient,
        requested_by=request.user,
        kind=kind,
        source_note_ids=payload["source_note_ids"],
        source_fingerprint=payload["source_fingerprint"],
        draft_text=payload["draft_text"],
    )
    record_audit_event(
        actor=request.user,
        action="ai_draft.created",
        obj=artifact,
        patient=patient,
        request=request,
        metadata={"kind": kind, "source_count": len(payload["source_note_ids"])},
    )
    messages.success(request, "Source-backed clinical draft created for therapist review.")
    return redirect("artifact-detail", artifact_id=artifact.pk)


@login_required
def artifact_detail(request: HttpRequest, artifact_id: str) -> HttpResponse:
    artifact = get_object_or_404(
        AIArtifact.objects.select_related("patient", "requested_by", "reviewed_by"),
        pk=artifact_id,
    )
    _clinical_access(request.user)
    require_patient_access(request, artifact.patient)
    return render(
        request,
        "care/artifact_detail.html",
        {
            "artifact": artifact,
            "source_notes": ClinicalNote.objects.filter(
                patient=artifact.patient, pk__in=artifact.source_note_ids
            ).order_by("-service_date"),
        },
    )


@login_required
@require_POST
def artifact_review(request: HttpRequest, artifact_id: str) -> HttpResponse:
    artifact = get_object_or_404(AIArtifact.objects.select_related("patient"), pk=artifact_id)
    _clinical_access(request.user)
    require_patient_access(request, artifact.patient)
    if not request.user.can_sign_notes:
        raise PermissionDenied("Only an authorized therapist can approve clinical drafts.")
    action = request.POST.get("action")
    if action == "reject":
        artifact.status = AIArtifact.Status.REJECTED
        artifact.review_note = request.POST.get("review_note", "")[:1000]
        outcome_message = "Draft rejected and retained in the audit trail."
    elif action == "approve":
        artifact.status = AIArtifact.Status.APPROVED
        artifact.review_note = request.POST.get("review_note", "")[:1000]
        outcome_message = "Draft approved. It is still not a signed clinical note."
    elif action == "apply":
        if artifact.status != AIArtifact.Status.APPROVED:
            messages.error(request, "Approve the draft before applying it to an editable note.")
            return redirect("artifact-detail", artifact_id=artifact.pk)
        note_type = {
            AIArtifact.Kind.PROGRESS: ClinicalNote.Type.PROGRESS,
            AIArtifact.Kind.DISCHARGE: ClinicalNote.Type.DISCHARGE,
            AIArtifact.Kind.HANDOFF: ClinicalNote.Type.HANDOFF,
        }.get(artifact.kind)
        if not note_type:
            messages.error(request, "This draft type cannot be applied to a clinical note.")
            return redirect("artifact-detail", artifact_id=artifact.pk)
        note = ClinicalNote.objects.create(
            patient=artifact.patient,
            therapist=request.user,
            note_type=note_type,
            diagnosis_snapshot=artifact.patient.diagnoses,
            precautions_snapshot=artifact.patient.precautions,
            assessment=artifact.draft_text,
            status=ClinicalNote.Status.DRAFT,
        )
        artifact.status = AIArtifact.Status.APPLIED
        artifact.applied_note = note
        outcome_message = "Draft applied to a new editable note. Review every section before signing."
    else:
        raise PermissionDenied("Unknown review action.")
    artifact.reviewed_by = request.user
    artifact.reviewed_at = timezone.now()
    artifact.save()
    record_audit_event(
        actor=request.user,
        action="ai_draft." + action,
        obj=artifact,
        patient=artifact.patient,
        request=request,
        metadata={"kind": artifact.kind},
    )
    messages.success(request, outcome_message)
    if artifact.applied_note_id:
        return redirect("note-edit", note_id=artifact.applied_note_id)
    return redirect("artifact-detail", artifact_id=artifact.pk)


@login_required
@require_http_methods(["GET", "POST"])
def voice_capture(request: HttpRequest, patient_id: str) -> HttpResponse:
    _clinical_access(request.user)
    patient = _patient_or_404(request, patient_id)
    form = VoiceCaptureForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        capture = form.save(commit=False)
        capture.patient = patient
        capture.therapist = request.user
        capture.full_clean()
        capture.save()
        record_audit_event(
            actor=request.user,
            action="voice_transcript.saved",
            obj=capture,
            patient=patient,
            request=request,
            metadata={"duration_seconds": capture.duration_seconds},
        )
        messages.success(request, "Transcript saved for clinician review; raw audio was not stored.")
        destination = reverse("note-create", kwargs={"patient_id": patient.pk})
        return redirect(destination + "?voice=" + str(capture.pk))
    return render(
        request,
        "care/voice_capture.html",
        {"patient": patient, "form": form},
    )


@login_required
@require_http_methods(["GET", "POST"])
def home_program_create(request: HttpRequest, patient_id: str) -> HttpResponse:
    _clinical_access(request.user)
    patient = _patient_or_404(request, patient_id)
    form = HomeProgramForm(
        request.POST or None,
        initial={
            "diagnosis_context": patient.diagnoses,
            "precautions": patient.precautions,
        },
    )
    if request.method == "POST" and form.is_valid():
        program = form.save(commit=False)
        program.patient = patient
        program.prescribed_by = request.user
        program.status = HomeProgram.Status.DRAFT
        program.full_clean()
        program.save()
        record_audit_event(
            actor=request.user,
            action="home_program.created_draft",
            obj=program,
            patient=patient,
            request=request,
        )
        messages.success(request, "Home program saved as a draft for therapist review.")
        return redirect("patient-detail", patient_id=patient.pk)
    return render(
        request,
        "care/home_program_form.html",
        {
            "patient": patient,
            "form": form,
            "suggestions": home_program_suggestions(patient),
        },
    )


@login_required
@require_POST
def home_program_approve(request: HttpRequest, program_id: str) -> HttpResponse:
    program = get_object_or_404(HomeProgram.objects.select_related("patient"), pk=program_id)
    _clinical_access(request.user)
    require_patient_access(request, program.patient)
    if not request.user.can_sign_notes:
        raise PermissionDenied("Only an authorized therapist can activate a home program.")
    program.status = HomeProgram.Status.ACTIVE
    program.approved_at = timezone.now()
    program.save()
    record_audit_event(
        actor=request.user,
        action="home_program.approved",
        obj=program,
        patient=program.patient,
        request=request,
    )
    messages.success(request, "Home program activated. Provide only through an approved patient channel.")
    return redirect("patient-detail", patient_id=program.patient_id)


@login_required
@require_http_methods(["GET", "POST"])
def intake_create(request: HttpRequest, patient_id: str) -> HttpResponse:
    require_role(request.user, SCHEDULING_ROLES)
    patient = _patient_or_404(request, patient_id, clinical=False)
    form = IntakeCaptureForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        intake = IntakeSubmission.objects.create(
            patient=patient,
            form_version=form.cleaned_data["form_version"],
            answers=form.as_answers(),
            status=IntakeSubmission.Status.SUBMITTED,
            submitted_at=timezone.now(),
        )
        record_audit_event(
            actor=request.user,
            action="intake.submitted",
            obj=intake,
            patient=patient,
            request=request,
            metadata={"form_version": intake.form_version},
        )
        messages.success(request, "Intake submission saved for clinical review.")
        if request.user.can_access_clinical:
            return redirect("patient-detail", patient_id=patient.pk)
        return redirect("patient-list")
    return render(
        request,
        "care/form_page.html",
        {"form": form, "title": "Record intake submission", "patient": patient},
    )


@login_required
@require_http_methods(["GET", "POST"])
def consent_create(request: HttpRequest, patient_id: str) -> HttpResponse:
    require_role(request.user, SCHEDULING_ROLES)
    patient = _patient_or_404(request, patient_id, clinical=False)
    form = ConsentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        consent = form.save(commit=False)
        consent.patient = patient
        consent.recorded_by = request.user
        consent.status = Consent.Status.SIGNED
        consent.signed_at = timezone.now()
        consent.full_clean()
        consent.save()
        record_audit_event(
            actor=request.user,
            action="consent.recorded",
            obj=consent,
            patient=patient,
            request=request,
            metadata={"kind": consent.kind, "version": consent.document_version},
        )
        messages.success(request, "Versioned consent record saved.")
        if request.user.can_access_clinical:
            return redirect("patient-detail", patient_id=patient.pk)
        return redirect("patient-list")
    return render(
        request,
        "care/form_page.html",
        {"form": form, "title": "Record consent", "patient": patient},
    )


@login_required
@require_http_methods(["GET", "POST"])
def secure_messages(request: HttpRequest, patient_id: str) -> HttpResponse:
    require_role(request.user, SCHEDULING_ROLES | BILLING_ROLES)
    patient = _patient_or_404(
        request,
        patient_id,
        clinical=request.user.role in {User.Role.THERAPIST, User.Role.ASSISTANT},
    )
    organization = organization_required(request.user)
    form = SecureMessageForm(request.POST or None, organization=organization)
    if request.method == "POST" and form.is_valid():
        message = form.save(commit=False)
        message.patient = patient
        message.sender = request.user
        message.save()
        record_audit_event(
            actor=request.user,
            action="secure_message.sent",
            obj=message,
            patient=patient,
            request=request,
            metadata={"recipient_id": str(message.recipient_id)},
        )
        messages.success(request, "Secure message sent. External notifications should remain generic.")
        return redirect("secure-messages", patient_id=patient.pk)
    thread = patient.messages.filter(
        Q(sender=request.user) | Q(recipient=request.user)
    ).select_related("sender", "recipient")
    return render(
        request,
        "care/secure_messages.html",
        {"patient": patient, "form": form, "thread": thread},
    )


@login_required
def billing_detail(request: HttpRequest, patient_id: str) -> HttpResponse:
    require_role(request.user, PAYMENT_COLLECTION_ROLES)
    patient = _patient_or_404(request, patient_id, clinical=False)
    return render(
        request,
        "care/billing.html",
        {
            "patient": patient,
            "superbills": patient.superbills.select_related("clinician").all(),
            "payments": patient.payments.select_related("superbill", "recorded_by").all(),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def superbill_create(request: HttpRequest, patient_id: str) -> HttpResponse:
    require_role(request.user, BILLING_ROLES)
    patient = _patient_or_404(request, patient_id, clinical=False)
    form = SuperbillForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        superbill = form.save(commit=False)
        superbill.patient = patient
        superbill.clinician = request.user
        superbill.full_clean()
        superbill.save()
        record_audit_event(
            actor=request.user,
            action="superbill.created",
            obj=superbill,
            patient=patient,
            request=request,
            metadata={"status": superbill.status, "code_count": len(superbill.codes)},
        )
        messages.success(request, "Superbill saved. Verify payer-specific coding before submission.")
        return redirect("billing-detail", patient_id=patient.pk)
    return render(
        request,
        "care/form_page.html",
        {"form": form, "title": "Create superbill", "patient": patient},
    )


@login_required
@require_http_methods(["GET", "POST"])
def payment_record_create(request: HttpRequest, patient_id: str) -> HttpResponse:
    require_role(request.user, PAYMENT_COLLECTION_ROLES)
    patient = _patient_or_404(request, patient_id, clinical=False)
    form = PaymentRecordForm(request.POST or None, patient=patient)
    if request.method == "POST" and form.is_valid():
        payment = form.save(commit=False)
        payment.patient = patient
        payment.recorded_by = request.user
        payment.full_clean()
        payment.save()
        record_audit_event(
            actor=request.user,
            action="payment.recorded",
            obj=payment,
            patient=patient,
            request=request,
            metadata={"status": payment.status, "superbill_id": str(payment.superbill_id or "")},
        )
        messages.success(request, "Payment reference saved. No cardholder data was stored.")
        return redirect("billing-detail", patient_id=patient.pk)
    return render(
        request,
        "care/form_page.html",
        {"form": form, "title": "Record payment status", "patient": patient},
    )


@login_required
def platform_user_management(request: HttpRequest, **kwargs) -> HttpResponse:
    """Route legacy access URLs to the platform-only client management console."""
    if not request.user.is_platform_super_admin:
        raise PermissionDenied(
            "Only platform super administrators can create or manage client users."
        )
    return redirect(f"{reverse('react-workspace')}#clients")


def _access_control_organization(user):
    """Limit account administration to organization administrators."""
    require_role(user, {User.Role.ADMIN})
    return organization_required(user)


def _access_control_target(request: HttpRequest, user_id: str):
    organization = _access_control_organization(request.user)
    target = get_object_or_404(User, pk=user_id, organization=organization)
    if (
        target.is_superuser
        or target.is_staff
        or target.role == User.Role.SUPER_ADMIN
        or (target.role == User.Role.ADMIN and target.pk != request.user.pk)
    ) and not request.user.is_platform_super_admin:
        raise PermissionDenied(
            "Only a platform superuser may modify a platform administrator account."
        )
    return organization, target


@login_required
def access_control(request: HttpRequest) -> HttpResponse:
    organization = _access_control_organization(request.user)
    users = User.objects.filter(organization=organization).order_by(
        "-is_active", "last_name", "first_name", "username"
    )
    record_audit_event(
        actor=request.user,
        action="access_control.viewed",
        obj=request.user,
        request=request,
        metadata={"active_account_count": users.filter(is_active=True).count()},
    )
    return render(
        request,
        "care/access_control.html",
        {
            "users": users,
            "role_capabilities": ROLE_CAPABILITIES,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def facility_settings(request: HttpRequest) -> HttpResponse:
    organization = _access_control_organization(request.user)
    form = FacilitySettingsForm(
        request.POST or None,
        request.FILES or None,
        instance=organization,
    )
    if request.method == "POST" and form.is_valid():
        logo_changed = bool(request.FILES.get("logo") or request.POST.get("logo-clear"))
        organization = form.save(commit=False)
        if organization.onboarding_completed_at is None:
            organization.onboarding_completed_at = timezone.now()
        organization.full_clean()
        organization.save()
        record_audit_event(
            actor=request.user,
            action="facility.settings_updated",
            obj=organization,
            request=request,
            metadata={
                "logo_changed": logo_changed,
                "onboarding_completed": True,
            },
        )
        messages.success(request, "Facility settings and workspace branding updated.")
        return redirect("facility-settings")
    return render(
        request,
        "care/facility_settings.html",
        {
            "form": form,
            "organization": organization,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def employee_onboard(request: HttpRequest) -> HttpResponse:
    """Provision one employee with a tenant-scoped, least-privilege role."""
    organization = _access_control_organization(request.user)
    form = EmployeeOnboardingForm(
        request.POST or None,
        allow_admin=request.user.is_platform_super_admin,
    )
    if request.method == "POST" and form.is_valid():
        account = form.save(commit=False)
        account.organization = organization
        account.full_clean()
        account.save()
        record_audit_event(
            actor=request.user,
            action="access.employee_onboarded",
            obj=account,
            request=request,
            metadata={
                "role": account.role,
                "credential_recorded": bool(account.credential),
                "least_privilege_confirmed": True,
                "mfa_policy_required": account.must_use_mfa,
            },
        )
        messages.success(
            request,
            "Employee account created. Share the temporary password through an approved secure channel.",
        )
        return redirect("access-control")

    available_roles = {choice[0] for choice in form.fields["role"].choices}
    role_capabilities = [
        capability
        for capability in ROLE_CAPABILITIES
        if capability["role"] in available_roles
    ]
    return render(
        request,
        "care/employee_onboarding.html",
        {
            "form": form,
            "role_capabilities": role_capabilities,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def access_user_create(request: HttpRequest) -> HttpResponse:
    organization = _access_control_organization(request.user)
    form = AccessUserCreateForm(
        request.POST or None,
        allow_admin=request.user.is_platform_super_admin,
    )
    if request.method == "POST" and form.is_valid():
        account = form.save(commit=False)
        account.organization = organization
        account.full_clean()
        account.save()
        record_audit_event(
            actor=request.user,
            action="access.user_provisioned",
            obj=account,
            request=request,
            metadata={
                "role": account.role,
                "mfa_policy_required": account.must_use_mfa,
            },
        )
        messages.success(request, "User account created. Share the temporary password securely.")
        return redirect("access-control")
    return render(
        request,
        "care/access_user_form.html",
        {
            "form": form,
            "title": "Provision user access",
            "account": None,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def access_user_update(request: HttpRequest, user_id: str) -> HttpResponse:
    organization, account = _access_control_target(request, user_id)
    original_role = account.role
    form = AccessUserUpdateForm(
        request.POST or None,
        instance=account,
        allow_admin=request.user.is_platform_super_admin or account.pk == request.user.pk,
    )
    if request.method == "POST" and form.is_valid():
        requested_role = form.cleaned_data["role"]
        requested_active = form.cleaned_data["is_active"]
        requested_mfa_policy = form.cleaned_data["must_use_mfa"]
        if account.pk == request.user.pk:
            if not form.cleaned_data["is_active"]:
                form.add_error("is_active", "You cannot deactivate your own account.")
            if not requested_mfa_policy:
                form.add_error("must_use_mfa", "You cannot opt your own account out of MFA policy.")
            if requested_role != original_role:
                form.add_error("role", "You cannot change your own administrator role.")
        if not form.errors:
            with transaction.atomic():
                locked_account = User.objects.select_for_update().get(
                    pk=account.pk, organization=organization
                )
                if locked_account.role == User.Role.ADMIN and locked_account.is_active:
                    removes_admin = (
                        requested_role != User.Role.ADMIN or not requested_active
                    )
                    active_admin_count = User.objects.filter(
                        organization=organization,
                        role=User.Role.ADMIN,
                        is_active=True,
                    ).count()
                    if removes_admin and active_admin_count <= 1:
                        error_field = "role" if requested_role != User.Role.ADMIN else "is_active"
                        form.add_error(
                            error_field,
                            "Assign another active organization administrator before removing this access.",
                        )
                leaves_clinical_scope = (
                    locked_account.role in ASSIGNED_CLINICIAN_ROLES
                    and (
                        not requested_active
                        or requested_role not in CLINICAL_ACCESS_ROLES
                    )
                )
                if leaves_clinical_scope:
                    active_caseload = Patient.objects.filter(
                        assigned_therapist=locked_account,
                        status=Patient.Status.ACTIVE,
                    ).exists()
                    future_visits = Appointment.objects.filter(
                        therapist=locked_account,
                        starts_at__gte=timezone.now(),
                        status__in=[
                            Appointment.Status.SCHEDULED,
                            Appointment.Status.CHECKED_IN,
                        ],
                    ).exists()
                    unsigned_notes = ClinicalNote.objects.filter(
                        therapist=locked_account
                    ).exclude(status=ClinicalNote.Status.SIGNED).exists()
                    if active_caseload or future_visits or unsigned_notes:
                        error_field = (
                            "is_active" if not requested_active else "role"
                        )
                        form.add_error(
                            error_field,
                            "Reassign the active caseload and future visits, and resolve unsigned notes before removing clinical access.",
                        )
                if not form.errors:
                    previous_role = locked_account.role
                    previous_active = locked_account.is_active
                    previous_mfa_policy = locked_account.must_use_mfa
                    for field_name in form.Meta.fields:
                        setattr(locked_account, field_name, form.cleaned_data[field_name])
                    locked_account.full_clean()
                    locked_account.save()
                    account = locked_account
                    if previous_active and not account.is_active:
                        action = "access.user_deactivated"
                    elif previous_role != account.role:
                        action = "access.role_changed"
                    elif previous_mfa_policy != account.must_use_mfa:
                        action = "access.mfa_policy_changed"
                    else:
                        action = "access.user_updated"
                    record_audit_event(
                        actor=request.user,
                        action=action,
                        obj=account,
                        request=request,
                        metadata={
                            "previous_role": previous_role,
                            "role": account.role,
                            "active": account.is_active,
                            "mfa_policy_required": account.must_use_mfa,
                        },
                    )
                    messages.success(request, "Access settings updated.")
                    return redirect("access-control")
    return render(
        request,
        "care/access_user_form.html",
        {
            "form": form,
            "title": "Edit user access",
            "account": account,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def access_password_reset(request: HttpRequest, user_id: str) -> HttpResponse:
    _, account = _access_control_target(request, user_id)
    form = AccessPasswordResetForm(request.POST or None, user=account)
    if request.method == "POST" and form.is_valid():
        account.set_password(form.cleaned_data["password1"])
        account.save(update_fields=["password"])
        record_audit_event(
            actor=request.user,
            action="access.password_reset",
            obj=account,
            request=request,
            metadata={"mfa_policy_required": account.must_use_mfa},
        )
        messages.success(
            request,
            "Password reset. Share the temporary password through an approved secure channel.",
        )
        return redirect("access-control")
    return render(
        request,
        "care/access_password_reset.html",
        {"form": form, "account": account},
    )


@login_required
def audit_log(request: HttpRequest) -> HttpResponse:
    require_role(
        request.user,
        {User.Role.ADMIN, User.Role.DIRECTOR, User.Role.COMPLIANCE},
    )
    organization = organization_required(request.user)
    events = AuditEvent.objects.filter(organization=organization).select_related(
        "actor", "patient"
    )[:150]
    return render(request, "care/audit_log.html", {"events": events})
