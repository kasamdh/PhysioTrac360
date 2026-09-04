"""Patient chart document upload/list/download.

Files are stored under settings.PRIVATE_MEDIA_ROOT (see care/models.py
PatientDocument) — never the public MEDIA_ROOT — and are only ever served
through the authenticated, permission-checked download view below. There is
no public URL for the underlying file at any point.
"""
from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods

from ..access import CLINICAL_ROLES, require_patient_access
from ..models import Patient, PatientDocument
from ..services import record_audit_event
from .utils import api_error, api_login_required, organization_or_error

MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB


def serialize_document(document: PatientDocument) -> dict:
    return {
        "id": str(document.pk),
        "title": document.title,
        "description": document.description,
        "originalFilename": document.original_filename,
        "sizeBytes": document.size_bytes,
        "uploadedBy": document.uploaded_by.get_full_name() or document.uploaded_by.username,
        "uploadedAt": document.created_at.isoformat(),
    }


@require_http_methods(["GET", "POST"])
@api_login_required
def patient_documents(request, patient_id):
    _, error = organization_or_error(request, roles=CLINICAL_ROLES)
    if error:
        return error
    patient = get_object_or_404(Patient, pk=patient_id)
    try:
        require_patient_access(request, patient, clinical=True)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)

    if request.method == "POST":
        upload = request.FILES.get("file")
        if not upload:
            return JsonResponse({"detail": "Choose a file to upload.", "errors": {"file": "A file is required."}}, status=422)
        if upload.size > MAX_UPLOAD_BYTES:
            return JsonResponse(
                {"detail": "Please correct the highlighted fields.", "errors": {"file": "Files must be 15 MB or smaller."}},
                status=422,
            )
        title = request.POST.get("title", "").strip() or upload.name
        document = PatientDocument(
            patient=patient,
            uploaded_by=request.user,
            file=upload,
            original_filename=upload.name,
            title=title,
            description=request.POST.get("description", "").strip(),
            size_bytes=upload.size,
        )
        try:
            document.full_clean()
        except ValidationError:
            return JsonResponse(
                {"detail": "Please correct the highlighted fields.", "errors": {"file": "Unsupported file type. Allowed: PDF, PNG, JPG, DOC, DOCX."}},
                status=422,
            )
        document.save()
        record_audit_event(
            actor=request.user,
            action="patient_document.uploaded",
            obj=document,
            patient=patient,
            request=request,
            metadata={"title": title, "size_bytes": document.size_bytes},
        )
        return JsonResponse({"document": serialize_document(document)}, status=201)

    documents = patient.documents.select_related("uploaded_by").all()
    return JsonResponse({"documents": [serialize_document(document) for document in documents]})


@require_GET
@api_login_required
def patient_document_download(request, patient_id, document_id):
    _, error = organization_or_error(request, roles=CLINICAL_ROLES)
    if error:
        return error
    patient = get_object_or_404(Patient, pk=patient_id)
    try:
        require_patient_access(request, patient, clinical=True)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    document = PatientDocument.objects.filter(pk=document_id, patient=patient).first()
    if not document:
        return api_error("Document was not found.", status=404)
    record_audit_event(
        actor=request.user,
        action="patient_document.downloaded",
        obj=document,
        patient=patient,
        request=request,
        metadata={"title": document.title},
    )
    return FileResponse(document.file.open("rb"), as_attachment=True, filename=document.original_filename)
