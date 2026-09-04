"""Administrative tools for controlled provisioning and operational review."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    AIArtifact,
    Appointment,
    AuditEvent,
    ClinicalNote,
    Consent,
    FunctionalGoal,
    HomeExercise,
    HomeProgram,
    IntakeSubmission,
    NoteAddendum,
    Organization,
    OutcomeScore,
    PaymentRecord,
    Patient,
    SecureMessage,
    Superbill,
    User,
    VoiceCapture,
)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    search_fields = ("name", "slug")
    list_filter = ("is_active",)


@admin.register(User)
class ClinicalUserAdmin(UserAdmin):
    list_display = ("username", "get_full_name", "organization", "role", "is_active")
    list_filter = ("organization", "role", "is_active", "is_staff")
    fieldsets = UserAdmin.fieldsets + (
        (
            "Clinical workspace access",
            {"fields": ("organization", "role", "credential", "must_use_mfa")},
        ),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "Clinical workspace access",
            {"fields": ("organization", "role", "credential", "must_use_mfa")},
        ),
    )


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = (
        "medical_record_number",
        "last_name",
        "first_name",
        "organization",
        "assigned_therapist",
        "status",
    )
    list_filter = ("organization", "status")
    search_fields = ("medical_record_number", "first_name", "last_name")
    raw_id_fields = ("assigned_therapist",)


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("starts_at", "patient", "therapist", "kind", "status", "is_home_visit")
    list_filter = ("status", "kind", "is_home_visit")
    raw_id_fields = ("patient", "therapist", "created_by")


@admin.register(ClinicalNote)
class ClinicalNoteAdmin(admin.ModelAdmin):
    list_display = ("service_date", "patient", "therapist", "note_type", "status", "signed_at")
    list_filter = ("status", "note_type")
    raw_id_fields = ("patient", "therapist", "appointment")
    readonly_fields = ("created_at", "updated_at", "signed_at")


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "organization", "patient", "actor", "action", "object_type")
    list_filter = ("organization", "action", "object_type")
    search_fields = ("action", "object_type", "object_id")
    raw_id_fields = ("organization", "patient", "actor")
    readonly_fields = (
        "id",
        "organization",
        "patient",
        "actor",
        "action",
        "object_type",
        "object_id",
        "ip_address",
        "metadata",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD")

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(
    [
        Consent,
        IntakeSubmission,
        NoteAddendum,
        FunctionalGoal,
        OutcomeScore,
        PaymentRecord,
        HomeProgram,
        HomeExercise,
        VoiceCapture,
        SecureMessage,
        Superbill,
    ]
)
