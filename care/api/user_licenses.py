"""PT/PTA professional license CRUD, document upload/download, and admin
verification — one license per state per user, several per user allowed.

Files are stored under settings.PRIVATE_MEDIA_ROOT (see care/models.py
UserLicense), exactly like PatientDocument — never a public URL, only ever
served through the authenticated, permission-checked download view below.
"""
from __future__ import annotations

from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from ..access import require_platform_super_admin
from ..models import User, UserLicense
from ..services import record_audit_event
from .serializers import serialize_user_license
from .utils import api_error, api_login_required, InvalidJSON, json_body, organization_or_error

MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB
ASSIGNED_CLINICIAN_ROLES = {User.Role.THERAPIST, User.Role.ASSISTANT}


def _string_value(payload: dict, key: str) -> str:
    value = payload.get(key, "")
    return value.strip() if isinstance(value, str) else ""


def _parse_license_date(value) -> date | None:
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _resolve_org_scoped_user(request, user_id):
    organization, error = organization_or_error(request, roles={User.Role.ADMIN})
    if error:
        return None, error
    account = User.objects.filter(pk=user_id, organization=organization).first()
    if not account:
        return None, api_error("User was not found.", status=404)
    return account, None


def _resolve_super_admin_user(request, user_id):
    try:
        require_platform_super_admin(request.user)
    except PermissionDenied as exc:
        return None, api_error(str(exc), status=403)
    account = User.objects.filter(pk=user_id, organization__isnull=False).select_related("organization").first()
    if not account:
        return None, api_error("User was not found.", status=404)
    return account, None


def _validate_license_payload(payload: dict) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not _string_value(payload, "licenseNumber"):
        errors["licenseNumber"] = "License number is required."
    if not _string_value(payload, "issuingState"):
        errors["issuingState"] = "Issuing state is required."
    expires_raw = _string_value(payload, "expiresAt")
    if not expires_raw:
        errors["expiresAt"] = "License expiration date is required."
    elif _parse_license_date(expires_raw) is None:
        errors["expiresAt"] = "Enter a valid date."
    issue_raw = _string_value(payload, "issueDate")
    if issue_raw and _parse_license_date(issue_raw) is None:
        errors["issueDate"] = "Enter a valid date."
    return errors


def _list_or_create_licenses(request, account: User):
    if request.method == "POST":
        try:
            payload = json_body(request)
        except InvalidJSON as exc:
            return api_error(str(exc), status=400)
        errors = _validate_license_payload(payload)
        if errors:
            return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=422)
        license = UserLicense(
            user=account,
            license_number=_string_value(payload, "licenseNumber"),
            issuing_state=_string_value(payload, "issuingState"),
            license_type=_string_value(payload, "licenseType"),
            issue_date=_parse_license_date(payload.get("issueDate")),
            expires_at=_parse_license_date(payload.get("expiresAt")),
        )
        try:
            license.full_clean()
        except ValidationError as exc:
            return JsonResponse(
                {"detail": "Please correct the highlighted fields.", "errors": {field: " ".join(messages) for field, messages in exc.message_dict.items()}},
                status=422,
            )
        license.save()
        record_audit_event(
            actor=request.user, action="provider_license.created", obj=license, request=request,
            metadata={"issuing_state": license.issuing_state, "license_number": license.license_number},
        )
        return JsonResponse({"license": serialize_user_license(license)}, status=201)
    licenses = account.licenses.all()
    return JsonResponse({"licenses": [serialize_user_license(license) for license in licenses]})


def _get_or_error(account: User, license_id):
    license = UserLicense.objects.filter(pk=license_id, user=account).first()
    if not license:
        return None, api_error("License was not found.", status=404)
    return license, None


def _update_or_delete_license(request, account: User, license_id):
    license, error = _get_or_error(account, license_id)
    if error:
        return error
    if request.method == "DELETE":
        record_audit_event(
            actor=request.user, action="provider_license.deleted", obj=license, request=request,
            metadata={"issuing_state": license.issuing_state, "license_number": license.license_number},
        )
        license.delete()
        return JsonResponse({}, status=200)

    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)
    errors: dict[str, str] = {}
    if "expiresAt" in payload:
        expires_raw = _string_value(payload, "expiresAt")
        if not expires_raw:
            errors["expiresAt"] = "License expiration date is required."
        elif _parse_license_date(expires_raw) is None:
            errors["expiresAt"] = "Enter a valid date."
    if "issueDate" in payload:
        issue_raw = _string_value(payload, "issueDate")
        if issue_raw and _parse_license_date(issue_raw) is None:
            errors["issueDate"] = "Enter a valid date."
    if errors:
        return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=422)

    if "licenseNumber" in payload:
        license.license_number = _string_value(payload, "licenseNumber")
    if "issuingState" in payload:
        license.issuing_state = _string_value(payload, "issuingState")
    if "licenseType" in payload:
        license.license_type = _string_value(payload, "licenseType")
    if "issueDate" in payload:
        license.issue_date = _parse_license_date(payload.get("issueDate"))
    date_changed = False
    if "expiresAt" in payload:
        new_expires = _parse_license_date(payload.get("expiresAt"))
        date_changed = new_expires != license.expires_at
        license.expires_at = new_expires
    if date_changed:
        # An edited date can't be trusted without re-verification — matches
        # the spec's "don't auto-reactivate on a date edit alone" principle.
        license.verification_status = UserLicense.VerificationStatus.PENDING_VERIFICATION
        license.verified_at = None
        license.verified_by = None
    try:
        license.full_clean()
    except ValidationError as exc:
        return JsonResponse(
            {"detail": "Please correct the highlighted fields.", "errors": {field: " ".join(messages) for field, messages in exc.message_dict.items()}},
            status=422,
        )
    license.save()
    record_audit_event(
        actor=request.user, action="provider_license.updated", obj=license, request=request,
        metadata={"issuing_state": license.issuing_state, "license_number": license.license_number, "date_changed": date_changed},
    )
    return JsonResponse({"license": serialize_user_license(license)})


def _upload_or_download_document(request, account: User, license_id):
    license, error = _get_or_error(account, license_id)
    if error:
        return error

    if request.method == "GET":
        if not license.document:
            return api_error("No document has been uploaded for this license.", status=404)
        record_audit_event(
            actor=request.user, action="provider_license.document_downloaded", obj=license, request=request,
            metadata={"issuing_state": license.issuing_state, "license_number": license.license_number},
        )
        return FileResponse(license.document.open("rb"), as_attachment=True, filename=license.document_original_filename)

    upload = request.FILES.get("file")
    if not upload:
        return JsonResponse({"detail": "Choose a file to upload.", "errors": {"file": "A file is required."}}, status=422)
    if upload.size > MAX_UPLOAD_BYTES:
        return JsonResponse(
            {"detail": "Please correct the highlighted fields.", "errors": {"file": "Files must be 15 MB or smaller."}},
            status=422,
        )
    license.document = upload
    license.document_original_filename = upload.name
    # A freshly uploaded document supersedes any prior verification.
    license.verification_status = UserLicense.VerificationStatus.PENDING_VERIFICATION
    license.verified_at = None
    license.verified_by = None
    try:
        license.full_clean()
    except ValidationError:
        return JsonResponse(
            {"detail": "Please correct the highlighted fields.", "errors": {"file": "Unsupported file type. Allowed: PDF, PNG, JPG, DOC, DOCX."}},
            status=422,
        )
    license.save()
    record_audit_event(
        actor=request.user, action="provider_license.document_uploaded", obj=license, request=request,
        metadata={"issuing_state": license.issuing_state, "license_number": license.license_number},
    )
    return JsonResponse({"license": serialize_user_license(license)}, status=201)


def _verify_license(request, account: User, license_id):
    license, error = _get_or_error(account, license_id)
    if error:
        return error
    if not license.document:
        return JsonResponse(
            {"detail": "Please correct the highlighted fields.", "errors": {"document": "Upload the license document before verifying it."}},
            status=422,
        )
    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)

    license.verification_status = UserLicense.VerificationStatus.VERIFIED
    license.verified_at = timezone.now()
    license.verified_by = request.user
    license.verification_notes = _string_value(payload, "notes")
    license.save(update_fields=["verification_status", "verified_at", "verified_by", "verification_notes"])
    record_audit_event(
        actor=request.user, action="provider_license.verified", obj=license, request=request,
        metadata={"issuing_state": license.issuing_state, "license_number": license.license_number},
    )
    return JsonResponse({"license": serialize_user_license(license)})


# -- organization-admin routes, scoped to the admin's own tenant --------------

@require_http_methods(["GET", "POST"])
@api_login_required
def organization_user_licenses(request, user_id):
    account, error = _resolve_org_scoped_user(request, user_id)
    if error:
        return error
    return _list_or_create_licenses(request, account)


@require_http_methods(["PATCH", "DELETE"])
@api_login_required
def organization_user_license_detail(request, user_id, license_id):
    account, error = _resolve_org_scoped_user(request, user_id)
    if error:
        return error
    return _update_or_delete_license(request, account, license_id)


@require_http_methods(["GET", "POST"])
@api_login_required
def organization_user_license_document(request, user_id, license_id):
    account, error = _resolve_org_scoped_user(request, user_id)
    if error:
        return error
    return _upload_or_download_document(request, account, license_id)


@require_POST
@api_login_required
def organization_user_license_verify(request, user_id, license_id):
    account, error = _resolve_org_scoped_user(request, user_id)
    if error:
        return error
    return _verify_license(request, account, license_id)


# -- super-admin routes, platform-wide -----------------------------------------

@require_http_methods(["GET", "POST"])
@api_login_required
def super_admin_user_licenses(request, user_id):
    account, error = _resolve_super_admin_user(request, user_id)
    if error:
        return error
    return _list_or_create_licenses(request, account)


@require_http_methods(["PATCH", "DELETE"])
@api_login_required
def super_admin_user_license_detail(request, user_id, license_id):
    account, error = _resolve_super_admin_user(request, user_id)
    if error:
        return error
    return _update_or_delete_license(request, account, license_id)


@require_http_methods(["GET", "POST"])
@api_login_required
def super_admin_user_license_document(request, user_id, license_id):
    account, error = _resolve_super_admin_user(request, user_id)
    if error:
        return error
    return _upload_or_download_document(request, account, license_id)


@require_POST
@api_login_required
def super_admin_user_license_verify(request, user_id, license_id):
    account, error = _resolve_super_admin_user(request, user_id)
    if error:
        return error
    return _verify_license(request, account, license_id)
