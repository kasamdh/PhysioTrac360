"""Centralized tenant and role checks.

Views must use these checks instead of trusting a patient id submitted by the
browser. Database row-level security is still required for a production
PostgreSQL deployment.
"""
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest

from .models import Patient, User
from .services import record_audit_event


CLINICAL_ROLES = {
    User.Role.ADMIN,
    User.Role.DIRECTOR,
    User.Role.THERAPIST,
    User.Role.ASSISTANT,
    User.Role.COMPLIANCE,
}
SCHEDULING_ROLES = {
    User.Role.ADMIN,
    User.Role.DIRECTOR,
    User.Role.THERAPIST,
    User.Role.ASSISTANT,
    User.Role.SCHEDULER,
}
BILLING_ROLES = {User.Role.ADMIN, User.Role.BILLER, User.Role.DIRECTOR}
# Front desk collects payments (e.g. a copay at check-in) without the full
# billing visibility (superbills, billing detail) BILLING_ROLES grants.
PAYMENT_COLLECTION_ROLES = BILLING_ROLES | {User.Role.SCHEDULER}


def is_platform_super_admin(user) -> bool:
    """Return true only for the dedicated, organization-free platform account."""
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_platform_super_admin", False)
    )


def require_platform_super_admin(user) -> None:
    if not is_platform_super_admin(user):
        raise PermissionDenied("Only platform super administrators can manage clients.")


def organization_required(user):
    if is_platform_super_admin(user):
        raise PermissionDenied("Platform administrators must use the super-admin workspace.")
    if not user.organization_id:
        raise PermissionDenied(
            "This account is not assigned to an organization. Ask an administrator to assign it."
        )
    if user.organization.archived_at is not None:
        raise PermissionDenied(
            "Your organization account has been archived. Please contact your administrator."
        )
    if not user.organization.is_active or user.organization.status == user.organization.Status.SUSPENDED:
        raise PermissionDenied(
            "Your organization account is currently suspended. Please contact your administrator."
        )
    return user.organization


def patients_for(user, *, clinical: bool = True):
    """Return patient records limited to the caller's organization and role.

    The PATIENT-role check is deliberately first and unconditional — before
    the `clinical` flag is even consulted. Every other role's `clinical`
    flag toggles between "just my assigned patients" and "the whole org",
    but a portal (PATIENT-role) account must NEVER receive the whole-org
    queryset under any calling convention; it is always scoped to the one
    chart linked via `Patient.portal_user`, full stop."""
    organization = organization_required(user)
    queryset = Patient.objects.filter(organization=organization)
    if user.role == User.Role.PATIENT:
        return queryset.filter(portal_user=user)
    if not clinical:
        return queryset
    if user.role in {
        User.Role.ADMIN,
        User.Role.DIRECTOR,
        User.Role.COMPLIANCE,
    }:
        return queryset
    if user.role in {User.Role.THERAPIST, User.Role.ASSISTANT}:
        return queryset.filter(assigned_therapist=user)
    return queryset.none()


def require_portal_patient(request: HttpRequest) -> Patient:
    """The ONLY way a patient-portal endpoint resolves "which patient" — the
    authenticated session's own linked chart, never a patient id read from a
    URL, request body, or query parameter. This is the primary IDOR defense
    for the entire portal API surface: portal endpoints simply have no
    client-suppliable patient identifier to spoof in the first place. Any
    sub-resource within the portal (an appointment, a document, ...) must
    still be looked up filtered by `patient=` the value this returns."""
    if not getattr(request.user, "is_authenticated", False) or request.user.role != User.Role.PATIENT:
        raise PermissionDenied("This endpoint is only available to patient portal accounts.")
    organization = organization_required(request.user)
    patient = Patient.objects.filter(organization=organization, portal_user=request.user).select_related("organization").first()
    if patient is None:
        raise PermissionDenied("No patient chart is linked to this portal account. Contact your clinic.")
    return patient


def portal_patient_or_error(request):
    """Convenience wrapper matching this codebase's `(value, error_response)`
    convention (see care/api/utils.py:organization_or_error) — every portal
    view calls this instead of catching PermissionDenied itself."""
    from django.http import JsonResponse

    try:
        return require_portal_patient(request), None
    except PermissionDenied as exc:
        return None, JsonResponse({"detail": str(exc)}, status=403)


def require_role(user, roles: set[str]):
    if user.role in roles:
        return
    raise PermissionDenied("Your role is not permitted to perform this action.")


def require_patient_access(
    request: HttpRequest, patient: Patient, *, clinical: bool = True
) -> Patient:
    """Authorize a single chart lookup and log denied attempts without PHI."""
    try:
        allowed = patients_for(request.user, clinical=clinical).filter(pk=patient.pk).exists()
    except PermissionDenied:
        allowed = False
    if not allowed:
        if request.user.is_authenticated:
            record_audit_event(
                actor=request.user,
                action="access.denied",
                obj=patient,
                patient=patient,
                request=request,
                metadata={"route": request.path},
            )
        raise PermissionDenied("You are not permitted to access this patient record.")
    return patient
