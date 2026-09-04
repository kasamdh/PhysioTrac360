from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views


urlpatterns = [
    path("login/", views.SecureLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("patients/", views.patient_list, name="patient-list"),
    path("patients/new/", views.patient_create, name="patient-create"),
    path("appointments/new/", views.appointment_create, name="appointment-create"),
    path(
        "appointments/<uuid:appointment_id>/move/",
        views.appointment_move,
        name="appointment-move",
    ),
    path("patients/<uuid:patient_id>/", views.patient_detail, name="patient-detail"),
    path(
        "patients/<uuid:patient_id>/schedule/",
        views.appointment_create,
        name="appointment-create",
    ),
    path("schedule/", views.schedule, name="schedule"),
    path(
        "patients/<uuid:patient_id>/notes/new/",
        views.note_create,
        name="note-create",
    ),
    path("notes/<uuid:note_id>/", views.note_edit, name="note-edit"),
    path("notes/<uuid:note_id>/sign/", views.note_sign, name="note-sign"),
    path(
        "notes/<uuid:note_id>/addenda/new/",
        views.note_addendum_create,
        name="note-addendum-create",
    ),
    path(
        "patients/<uuid:patient_id>/goals/suggestions/",
        views.goal_suggestion_view,
        name="goal-suggestions",
    ),
    path(
        "patients/<uuid:patient_id>/goals/new/",
        views.goal_create,
        name="goal-create",
    ),
    path("goals/<uuid:goal_id>/approve/", views.goal_approve, name="goal-approve"),
    path(
        "patients/<uuid:patient_id>/outcomes/",
        views.outcome_list,
        name="outcomes",
    ),
    path(
        "patients/<uuid:patient_id>/drafts/new/",
        views.draft_create,
        name="draft-create",
    ),
    path(
        "drafts/<uuid:artifact_id>/",
        views.artifact_detail,
        name="artifact-detail",
    ),
    path(
        "drafts/<uuid:artifact_id>/review/",
        views.artifact_review,
        name="artifact-review",
    ),
    path(
        "patients/<uuid:patient_id>/voice/",
        views.voice_capture,
        name="voice-capture",
    ),
    path(
        "patients/<uuid:patient_id>/home-programs/new/",
        views.home_program_create,
        name="home-program-create",
    ),
    path(
        "home-programs/<uuid:program_id>/approve/",
        views.home_program_approve,
        name="home-program-approve",
    ),
    path(
        "patients/<uuid:patient_id>/messages/",
        views.secure_messages,
        name="secure-messages",
    ),
    path(
        "patients/<uuid:patient_id>/intake/",
        views.intake_create,
        name="intake-create",
    ),
    path(
        "patients/<uuid:patient_id>/consents/new/",
        views.consent_create,
        name="consent-create",
    ),
    path(
        "patients/<uuid:patient_id>/billing/",
        views.billing_detail,
        name="billing-detail",
    ),
    path(
        "patients/<uuid:patient_id>/billing/superbills/new/",
        views.superbill_create,
        name="superbill-create",
    ),
    path(
        "patients/<uuid:patient_id>/billing/payments/new/",
        views.payment_record_create,
        name="payment-record-create",
    ),
    path("access/", views.platform_user_management, name="access-control"),
    path(
        "access/facility/",
        views.facility_settings,
        name="facility-settings",
    ),
    path(
        "access/employees/onboard/",
        views.platform_user_management,
        name="employee-onboard",
    ),
    path("access/users/new/", views.platform_user_management, name="access-user-create"),
    path(
        "access/users/<uuid:user_id>/",
        views.platform_user_management,
        name="access-user-update",
    ),
    path(
        "access/users/<uuid:user_id>/password/",
        views.platform_user_management,
        name="access-password-reset",
    ),
    path("audit/", views.audit_log, name="audit-log"),
]
