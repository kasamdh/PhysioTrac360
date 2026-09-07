"""Clinical note lifecycle: permission predicates plus the sign/cosign/addendum
transition functions.

Mirrors `care/user_management.py`'s split — permission enforcement is the
caller's job (each view checks a `can_*` predicate before acting, exactly like
views already gate on `require_role`/`organization_or_error`), while the
functions here own state-validity checks (attestation, compliance blockers,
status preconditions) and the actual mutation + audit event. Both the legacy
server-rendered views (`care/views.py`) and the React API
(`care/api/note_views.py`) call these same functions so business logic exists
in exactly one place.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Appointment, ClinicalNote, NoteAddendum, User
from .services import note_compliance_findings, record_audit_event

FINALIZING_ROLES = {User.Role.ADMIN, User.Role.DIRECTOR}


def _complete_linked_appointment(note: ClinicalNote) -> None:
    """A signed note closes the loop on its appointment, matching how
    scheduling already treats a completed encounter — never overrides a
    cancellation or no-show, since those reflect what actually happened."""
    appointment = note.appointment
    if appointment is None:
        return
    if appointment.status not in {Appointment.Status.SCHEDULED, Appointment.Status.CHECKED_IN}:
        return
    appointment.status = Appointment.Status.COMPLETED
    appointment.save(update_fields=["status", "updated_at"])


def can_view_note(user, note: ClinicalNote) -> bool:
    return user.role in FINALIZING_ROLES or note.therapist_id == user.id


def can_edit_note(user, note: ClinicalNote) -> bool:
    """A signed note is never editable; otherwise the author, or an admin/director."""
    if note.is_signed:
        return False
    if user.role in FINALIZING_ROLES:
        return True
    return note.therapist_id == user.id


def can_finalize_note(user, note: ClinicalNote) -> bool:
    """Who may sign this specific note. Admin/director always; the owning
    therapist if their role carries `can_sign_notes`; the owning PTA/
    ASSISTANT too — `User.can_sign_notes` itself excludes ASSISTANT since
    unsupervised final sign-off isn't a PTA capability, but a PTA can always
    submit their own note for the sign action, landing on REVIEW_REQUIRED
    instead of SIGNED when `note.cosign_required` (see `sign_note`)."""
    if user.role in FINALIZING_ROLES:
        return True
    if note.therapist_id != user.id:
        return False
    return user.can_sign_notes or user.role == User.Role.ASSISTANT


def can_cosign_note(user, note: ClinicalNote) -> bool:
    """Who may cosign a PTA-authored note awaiting review — a supervising
    admin/director/therapist, never the note's own author."""
    if user.id == note.therapist_id:
        return False
    if user.role in FINALIZING_ROLES:
        return True
    return user.role == User.Role.THERAPIST and user.can_sign_notes


def can_create_addendum(user, note: ClinicalNote) -> bool:
    if not note.is_signed:
        return False
    return can_finalize_note(user, note)


def sign_note(*, note: ClinicalNote, user, attestation_confirmed: bool, request=None):
    """Finalize a note. Returns (note, errors, status_code) — `errors` is None
    on success. Caller must already have checked `can_finalize_note`."""
    if not attestation_confirmed:
        return None, {
            "attestation": "Confirm therapist review and attestation before finalizing this note."
        }, 422
    findings = note_compliance_findings(note)
    blockers = [finding for finding in findings if finding.finalization_blocker]
    if blockers:
        return None, {
            "status": "Note cannot be finalized until required documentation checks are resolved.",
            "blockers": [finding.code for finding in blockers],
        }, 409

    note.signature_name = user.get_full_name() or user.username
    note.signed_at = timezone.now()
    note.finalization_attestation = True
    pending_cosign = note.cosign_required and user.role == User.Role.ASSISTANT
    note.status = ClinicalNote.Status.REVIEW_REQUIRED if pending_cosign else ClinicalNote.Status.SIGNED
    try:
        note.full_clean()
        note.save()
    except ValidationError as exc:
        return None, {field: " ".join(messages) for field, messages in exc.message_dict.items()}, 422
    record_audit_event(
        actor=user,
        action="note.submitted_for_cosign" if pending_cosign else "note.signed",
        obj=note,
        patient=note.patient,
        request=request,
        metadata={"note_type": note.note_type, "status": note.status},
    )
    if note.status == ClinicalNote.Status.SIGNED:
        _complete_linked_appointment(note)
    return note, None, 200


def cosign_note(*, note: ClinicalNote, user, request=None):
    """Complete a PTA-authored note awaiting cosign. Caller must already have
    checked `can_cosign_note`."""
    if note.status != ClinicalNote.Status.REVIEW_REQUIRED:
        return None, {"status": "Only a note awaiting cosign can be cosigned."}, 409
    note.cosigned_by = user
    note.cosigned_at = timezone.now()
    note.status = ClinicalNote.Status.SIGNED
    try:
        note.full_clean()
        note.save()
    except ValidationError as exc:
        return None, {field: " ".join(messages) for field, messages in exc.message_dict.items()}, 422
    record_audit_event(
        actor=user, action="note.cosigned", obj=note, patient=note.patient, request=request,
        metadata={"note_type": note.note_type},
    )
    _complete_linked_appointment(note)
    return note, None, 200


def create_addendum(*, note: ClinicalNote, user, reason: str, body: str, request=None):
    """Attach a correction to a signed note. Caller must already have checked
    `can_create_addendum`. The original note is never touched."""
    if not note.is_signed:
        return None, {"status": "An addendum can only be created for a signed note."}, 409
    addendum = NoteAddendum(note=note, author=user, reason=reason, body=body)
    try:
        addendum.full_clean()
        addendum.save()
    except ValidationError as exc:
        return None, {field: " ".join(messages) for field, messages in exc.message_dict.items()}, 422
    record_audit_event(
        actor=user, action="note.addendum_created", obj=addendum, patient=note.patient, request=request,
        metadata={"note_id": str(note.pk)},
    )
    return addendum, None, 201
