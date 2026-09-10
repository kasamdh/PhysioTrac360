import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import AppointmentForm
from .models import (
    AIArtifact,
    Appointment,
    AppointmentType,
    AuditEvent,
    Authorization,
    BookingConfiguration,
    CashPackage,
    Charge,
    Claim,
    ClaimDenial,
    ClaimTransaction,
    ClientInvitation,
    ClinicalNote,
    Consent,
    DiagnosisCode,
    EpisodeOfCare,
    Feature,
    FormSubmission,
    FormTemplate,
    FunctionalGoal,
    HomeExercise,
    HomeExerciseLog,
    HomeProgram,
    IntakeSubmission,
    Location,
    LocationClosure,
    NoteAddendum,
    NoteIntervention,
    Organization,
    OrganizationSubscription,
    OutcomeAssignment,
    OutcomeScore,
    Patient,
    PatientDocument,
    PatientInsurance,
    PatientPayment,
    PatientProfileChangeRequest,
    PatientStatement,
    Payer,
    PaymentRecord,
    PrivilegedAccessGrant,
    Provider,
    ProviderAppointmentType,
    ProviderAvailability,
    ProviderTimeOff,
    Referral,
    SecureMessage,
    ServicePrice,
    SubscriptionPlan,
    Superbill,
    User,
    UserLicense,
    UserSession,
    Waitlist,
)
from .services import (
    coding_suggestions,
    compose_draft,
    goal_suggestions,
    note_compliance_findings,
    patient_compliance_findings,
    record_audit_event,
)


class SubscriptionFoundationTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="North Clinic", slug="north")

    def test_plan_can_grant_feature_access_when_active(self):
        plan = SubscriptionPlan.objects.create(
            code="growth",
            name="Growth",
            monthly_price=249,
            provider_seat_limit=10,
            is_active=True,
        )
        feature = Feature.objects.create(code="ai_documentation", name="AI documentation")
        subscription = OrganizationSubscription.objects.create(
            organization=self.organization,
            plan=plan,
            status=OrganizationSubscription.Status.ACTIVE,
        )
        subscription.features.add(feature)

        self.assertTrue(subscription.is_active)
        self.assertTrue(subscription.has_feature("ai_documentation"))

    def test_inactive_subscription_cannot_access_feature(self):
        plan = SubscriptionPlan.objects.create(
            code="solo",
            name="Solo",
            monthly_price=99,
            provider_seat_limit=1,
            is_active=True,
        )
        feature = Feature.objects.create(code="insurance_workflows", name="Insurance workflows")
        subscription = OrganizationSubscription.objects.create(
            organization=self.organization,
            plan=plan,
            status=OrganizationSubscription.Status.PAST_DUE,
        )
        subscription.features.add(feature)

        self.assertFalse(subscription.is_active)
        self.assertFalse(subscription.has_feature("insurance_workflows"))


class ProviderLocationFoundationTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="North Clinic", slug="north")

    def test_provider_and_location_are_tenant_scoped(self):
        location = Location.objects.create(
            organization=self.organization,
            name="North Clinic - Downtown",
            city="Portland",
            state="OR",
            zip_code="97205",
        )
        provider = Provider.objects.create(
            organization=self.organization,
            first_name="Maya",
            last_name="Lee",
            specialty="Orthopedic PT",
            license_number="PT-44521",
        )
        provider.locations.add(location)

        self.assertEqual(location.organization, self.organization)
        self.assertEqual(provider.organization, self.organization)
        self.assertIn(location, provider.locations.all())

    def test_provider_must_belong_to_same_org_as_linked_user(self):
        other_org = Organization.objects.create(name="South Clinic", slug="south")
        user = User.objects.create_user(
            username="other-therapist",
            password="safe-test-password",
            organization=other_org,
            role=User.Role.THERAPIST,
        )

        provider = Provider(
            organization=self.organization,
            user=user,
            first_name="Avery",
            last_name="Stone",
            specialty="Neurologic PT",
            license_number="PT-99881",
        )
        with self.assertRaisesMessage(ValidationError, "Provider user must belong to the same organization."):
            provider.full_clean()

    def test_appointment_can_bind_to_org_provider_and_location(self):
        therapist = User.objects.create_user(
            username="team-therapist",
            password="safe-test-password",
            organization=self.organization,
            role=User.Role.THERAPIST,
        )
        patient = Patient.objects.create(
            organization=self.organization,
            first_name="Jordan",
            last_name="Patient",
            date_of_birth="1988-04-12",
            assigned_therapist=therapist,
        )
        location = Location.objects.create(
            organization=self.organization,
            name="North Clinic - South",
            city="Portland",
            state="OR",
            zip_code="97201",
        )
        provider = Provider.objects.create(
            organization=self.organization,
            user=therapist,
            first_name="Maya",
            last_name="Lee",
            specialty="Orthopedic PT",
            license_number="PT-11099",
        )
        provider.locations.add(location)

        appointment = Appointment(
            patient=patient,
            therapist=therapist,
            starts_at=timezone.make_aware(datetime(2026, 6, 1, 9, 0)),
            ends_at=timezone.make_aware(datetime(2026, 6, 1, 9, 45)),
            location="Main clinic",
            provider=provider,
            location_detail=location,
            created_by=therapist,
        )
        appointment.full_clean()
        appointment.save()

        self.assertEqual(appointment.provider, provider)
        self.assertEqual(appointment.location_detail, location)

    def test_appointment_form_limits_provider_and_location_to_org(self):
        therapist = User.objects.create_user(
            username="org-therapist",
            password="safe-test-password",
            organization=self.organization,
            role=User.Role.THERAPIST,
        )
        in_org_location = Location.objects.create(
            organization=self.organization,
            name="Main clinic",
            city="Portland",
            state="OR",
        )
        in_org_provider = Provider.objects.create(
            organization=self.organization,
            user=therapist,
            first_name="Nina",
            last_name="Ward",
            specialty="Sports PT",
        )
        other_org = Organization.objects.create(name="East Clinic", slug="east")
        other_location = Location.objects.create(
            organization=other_org,
            name="Outside site",
            city="Seattle",
            state="WA",
        )
        other_provider = Provider.objects.create(
            organization=other_org,
            first_name="Evan",
            last_name="Stone",
            specialty="Neuro PT",
        )

        form = AppointmentForm(organization=self.organization)

        self.assertIn(in_org_provider, form.fields["provider"].queryset)
        self.assertIn(in_org_location, form.fields["location_detail"].queryset)
        self.assertNotIn(other_provider, form.fields["provider"].queryset)
        self.assertNotIn(other_location, form.fields["location_detail"].queryset)

    def test_therapist_cannot_be_double_booked_at_the_model_level(self):
        therapist = User.objects.create_user(
            username="double-book-therapist",
            password="safe-test-password",
            organization=self.organization,
            role=User.Role.THERAPIST,
        )
        first_patient = Patient.objects.create(
            organization=self.organization, first_name="First", last_name="Patient", date_of_birth="1980-01-01"
        )
        second_patient = Patient.objects.create(
            organization=self.organization, first_name="Second", last_name="Patient", date_of_birth="1982-02-02"
        )
        starts_at = timezone.make_aware(datetime(2026, 7, 6, 9, 0))
        Appointment.objects.create(
            patient=first_patient, therapist=therapist, starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=45), created_by=therapist,
        )

        overlapping = Appointment(
            patient=second_patient, therapist=therapist, starts_at=starts_at + timedelta(minutes=15),
            ends_at=starts_at + timedelta(minutes=60), created_by=therapist,
        )
        with self.assertRaisesMessage(
            ValidationError, "This therapist already has an appointment during this time."
        ):
            overlapping.full_clean()

        # A different, non-overlapping time for the same therapist is unaffected.
        later = Appointment(
            patient=second_patient, therapist=therapist, starts_at=starts_at + timedelta(hours=2),
            ends_at=starts_at + timedelta(hours=2, minutes=45), created_by=therapist,
        )
        later.full_clean()

        # Cancelling the first appointment frees the slot for a new one.
        cancelled_conflict = Appointment.objects.get(patient=first_patient)
        cancelled_conflict.status = Appointment.Status.CANCELLED
        cancelled_conflict.full_clean()
        cancelled_conflict.save()
        overlapping.full_clean()

    def test_legacy_appointment_create_view_rejects_double_booking(self):
        scheduler = User.objects.create_user(
            username="legacy-scheduler", password="safe-test-password",
            organization=self.organization, role=User.Role.SCHEDULER,
        )
        therapist = User.objects.create_user(
            username="legacy-therapist", password="safe-test-password",
            organization=self.organization, role=User.Role.THERAPIST,
        )
        first_patient = Patient.objects.create(
            organization=self.organization, first_name="Legacy", last_name="First", date_of_birth="1975-03-03"
        )
        second_patient = Patient.objects.create(
            organization=self.organization, first_name="Legacy", last_name="Second", date_of_birth="1979-04-04"
        )
        self.client.force_login(scheduler)

        first_response = self.client.post(reverse("appointment-create"), data={
            "patient": str(first_patient.pk), "therapist": str(therapist.pk), "kind": Appointment.Kind.FOLLOW_UP,
            "status": Appointment.Status.SCHEDULED, "starts_at": "2026-07-06T09:00", "ends_at": "2026-07-06T09:45",
        })
        self.assertEqual(first_response.status_code, 302)
        self.assertTrue(Appointment.objects.filter(patient=first_patient).exists())

        second_response = self.client.post(reverse("appointment-create"), data={
            "patient": str(second_patient.pk), "therapist": str(therapist.pk), "kind": Appointment.Kind.FOLLOW_UP,
            "status": Appointment.Status.SCHEDULED, "starts_at": "2026-07-06T09:15", "ends_at": "2026-07-06T10:00",
        })
        self.assertEqual(second_response.status_code, 200)
        self.assertFalse(Appointment.objects.filter(patient=second_patient).exists())
        self.assertContains(second_response, "already has an appointment during this time")


class ClinicalWorkflowTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="North Clinic", slug="north")
        self.therapist = User.objects.create_user(
            username="therapist",
            password="safe-test-password",
            organization=self.organization,
            role=User.Role.THERAPIST,
        )
        self.patient = Patient.objects.create(
            organization=self.organization,
            first_name="Alex",
            last_name="Patient",
            date_of_birth="1984-01-02",
            assigned_therapist=self.therapist,
            diagnoses="Knee pain",
        )

    def test_goal_suggestions_are_tied_to_the_stated_limitation(self):
        limitation = "Cannot safely descend the stairs to enter the home."
        suggestions = goal_suggestions(limitation, "Knee pain", "lefs")
        self.assertTrue(suggestions)
        self.assertIn(limitation, suggestions[0]["wording"])
        self.assertIn("stairs", suggestions[0]["functional_task"].lower())

    def test_missing_objective_and_plan_block_finalization(self):
        note = ClinicalNote.objects.create(
            patient=self.patient,
            therapist=self.therapist,
            note_type=ClinicalNote.Type.DAILY,
            subjective="Patient reports knee pain.",
            assessment="Requires continued skilled care.",
        )
        blockers = [
            finding.code
            for finding in note_compliance_findings(note)
            if finding.finalization_blocker
        ]
        self.assertIn("missing_objective", blockers)
        self.assertIn("missing_plan", blockers)

    def test_therapist_can_sign_complete_daily_note(self):
        note = ClinicalNote.objects.create(
            patient=self.patient,
            therapist=self.therapist,
            note_type=ClinicalNote.Type.DAILY,
            subjective="Reports less pain when walking.",
            objective="Walked 200 feet with prescribed device and no loss of balance.",
            assessment="Improved gait tolerance.",
            plan="Continue gait training and reassess next visit.",
        )
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("note-sign", kwargs={"note_id": note.pk}),
            {"attestation": "confirmed"},
        )
        self.assertRedirects(
            response, reverse("patient-detail", kwargs={"patient_id": self.patient.pk})
        )
        note.refresh_from_db()
        self.assertEqual(note.status, ClinicalNote.Status.SIGNED)
        self.assertTrue(note.finalization_attestation)

    def test_note_cannot_sign_without_server_side_attestation(self):
        note = ClinicalNote.objects.create(
            patient=self.patient,
            therapist=self.therapist,
            note_type=ClinicalNote.Type.DAILY,
            objective="Objective findings.",
            assessment="Assessment.",
            plan="Plan.",
        )
        self.client.force_login(self.therapist)
        response = self.client.post(reverse("note-sign", kwargs={"note_id": note.pk}))
        self.assertRedirects(response, reverse("note-edit", kwargs={"note_id": note.pk}))
        note.refresh_from_db()
        self.assertEqual(note.status, ClinicalNote.Status.DRAFT)

    def test_drafts_only_use_signed_prior_notes(self):
        signed = ClinicalNote.objects.create(
            patient=self.patient,
            therapist=self.therapist,
            note_type=ClinicalNote.Type.DAILY,
            status=ClinicalNote.Status.SIGNED,
            objective="Signed objective data.",
            assessment="Signed assessment.",
            plan="Signed plan.",
            signature_name="Therapist",
            signed_at="2026-01-02T12:00:00Z",
            finalization_attestation=True,
        )
        ClinicalNote.objects.create(
            patient=self.patient,
            therapist=self.therapist,
            note_type=ClinicalNote.Type.DAILY,
            objective="Unreviewed data.",
        )
        payload = compose_draft(self.patient, AIArtifact.Kind.PROGRESS)
        self.assertEqual(payload["source_note_ids"], [str(signed.pk)])
        self.assertIn("Signed objective data", payload["draft_text"])
        self.assertNotIn("Unreviewed data", payload["draft_text"])

    def test_other_tenant_cannot_open_chart(self):
        other_org = Organization.objects.create(name="South Clinic", slug="south")
        other_user = User.objects.create_user(
            username="other",
            password="safe-test-password",
            organization=other_org,
            role=User.Role.THERAPIST,
        )
        self.client.force_login(other_user)
        response = self.client.get(
            reverse("patient-detail", kwargs={"patient_id": self.patient.pk})
        )
        self.assertEqual(response.status_code, 403)

    def test_authenticated_workspace_pages_render(self):
        note = ClinicalNote.objects.create(
            patient=self.patient,
            therapist=self.therapist,
            note_type=ClinicalNote.Type.DAILY,
            objective="Objective data.",
            assessment="Assessment.",
            plan="Plan.",
        )
        artifact = AIArtifact.objects.create(
            patient=self.patient,
            requested_by=self.therapist,
            kind=AIArtifact.Kind.PROGRESS,
            source_note_ids=[],
            source_fingerprint="test",
            draft_text="Draft content requiring review.",
        )
        signed_note = ClinicalNote.objects.create(
            patient=self.patient,
            therapist=self.therapist,
            note_type=ClinicalNote.Type.DAILY,
            status=ClinicalNote.Status.SIGNED,
            objective="Signed objective.",
            assessment="Signed assessment.",
            plan="Signed plan.",
            signature_name="Therapist",
            signed_at="2026-01-02T12:00:00Z",
            finalization_attestation=True,
        )
        self.therapist.role = User.Role.ADMIN
        self.therapist.save()
        self.client.force_login(self.therapist)
        pages = [
            reverse("dashboard"),
            reverse("patient-list"),
            reverse("patient-detail", kwargs={"patient_id": self.patient.pk}),
            reverse("schedule"),
            reverse("appointment-create"),
            reverse("note-create", kwargs={"patient_id": self.patient.pk}),
            reverse("note-edit", kwargs={"note_id": note.pk}),
            reverse("note-edit", kwargs={"note_id": signed_note.pk}),
            reverse("note-addendum-create", kwargs={"note_id": signed_note.pk}),
            reverse("goal-suggestions", kwargs={"patient_id": self.patient.pk}),
            reverse("goal-create", kwargs={"patient_id": self.patient.pk}),
            reverse("outcomes", kwargs={"patient_id": self.patient.pk}),
            reverse("artifact-detail", kwargs={"artifact_id": artifact.pk}),
            reverse("voice-capture", kwargs={"patient_id": self.patient.pk}),
            reverse("home-program-create", kwargs={"patient_id": self.patient.pk}),
            reverse("secure-messages", kwargs={"patient_id": self.patient.pk}),
            reverse("intake-create", kwargs={"patient_id": self.patient.pk}),
            reverse("consent-create", kwargs={"patient_id": self.patient.pk}),
            reverse("billing-detail", kwargs={"patient_id": self.patient.pk}),
            reverse("superbill-create", kwargs={"patient_id": self.patient.pk}),
            reverse("payment-record-create", kwargs={"patient_id": self.patient.pk}),
            reverse("facility-settings"),
            reverse("audit-log"),
        ]
        for url in pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

        restricted_pages = [
            reverse("access-control"),
            reverse("employee-onboard"),
            reverse("access-user-create"),
            reverse("access-user-update", kwargs={"user_id": self.therapist.pk}),
            reverse("access-password-reset", kwargs={"user_id": self.therapist.pk}),
        ]
        for url in restricted_pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 403)

    def test_intake_billing_goal_and_outcome_workflows(self):
        self.therapist.role = User.Role.ADMIN
        self.therapist.save()
        self.client.force_login(self.therapist)

        response = self.client.post(
            reverse("intake-create", kwargs={"patient_id": self.patient.pk}),
            {
                "form_version": "intake-v1",
                "chief_complaint": "Pain with stairs.",
                "functional_goals": "Return to full household mobility.",
                "relevant_history": "No additional history recorded.",
            },
        )
        self.assertRedirects(
            response, reverse("patient-detail", kwargs={"patient_id": self.patient.pk})
        )
        self.assertEqual(IntakeSubmission.objects.count(), 1)

        response = self.client.post(
            reverse("consent-create", kwargs={"patient_id": self.patient.pk}),
            {
                "kind": Consent.Kind.TREATMENT,
                "document_version": "v1",
                "signature_name": "Alex Patient",
            },
        )
        self.assertRedirects(
            response, reverse("patient-detail", kwargs={"patient_id": self.patient.pk})
        )
        self.assertEqual(Consent.objects.count(), 1)

        response = self.client.post(
            reverse("goal-create", kwargs={"patient_id": self.patient.pk}),
            {
                "functional_limitation": "Cannot descend one flight of stairs safely.",
                "functional_task": "Descend 12 stairs with a rail.",
                "baseline_value": "2",
                "target_value": "0",
                "current_value": "",
                "unit": "assistance level",
                "measurement_method": "direct stair observation",
                "target_date": "2026-06-01",
                "suggested_wording": "Within six weeks, patient will descend stairs.",
            },
        )
        self.assertRedirects(
            response, reverse("patient-detail", kwargs={"patient_id": self.patient.pk})
        )
        goal = FunctionalGoal.objects.get()
        response = self.client.post(reverse("goal-approve", kwargs={"goal_id": goal.pk}))
        self.assertRedirects(
            response, reverse("patient-detail", kwargs={"patient_id": self.patient.pk})
        )
        goal.refresh_from_db()
        self.assertEqual(goal.status, FunctionalGoal.Status.ACTIVE)

        response = self.client.post(
            reverse("outcomes", kwargs={"patient_id": self.patient.pk}),
            {
                "measure": OutcomeScore.Measure.LEFS,
                "measured_on": "2026-05-01",
                "score": "56",
                "maximum_score": "",
                "notes": "Initial recorded score.",
            },
        )
        self.assertRedirects(response, reverse("outcomes", kwargs={"patient_id": self.patient.pk}))
        self.assertEqual(OutcomeScore.objects.get().maximum_score, 80)

        response = self.client.post(
            reverse("superbill-create", kwargs={"patient_id": self.patient.pk}),
            {
                "service_date": "2026-05-01",
                "codes": "97110, 97140",
                "amount": "145.00",
                "status": Superbill.Status.READY,
                "payment_processor_reference": "",
            },
        )
        self.assertRedirects(
            response, reverse("billing-detail", kwargs={"patient_id": self.patient.pk})
        )
        superbill = Superbill.objects.get()
        self.assertEqual(superbill.codes, ["97110", "97140"])

        response = self.client.post(
            reverse("payment-record-create", kwargs={"patient_id": self.patient.pk}),
            {
                "superbill": str(superbill.pk),
                "amount": "145.00",
                "received_on": "2026-05-01",
                "status": PaymentRecord.Status.RECEIVED,
                "payment_processor_reference": "tok_processor_reference",
            },
        )
        self.assertRedirects(
            response, reverse("billing-detail", kwargs={"patient_id": self.patient.pk})
        )
        self.assertEqual(PaymentRecord.objects.count(), 1)

    def test_draft_review_must_precede_application_to_note(self):
        ClinicalNote.objects.create(
            patient=self.patient,
            therapist=self.therapist,
            note_type=ClinicalNote.Type.DAILY,
            status=ClinicalNote.Status.SIGNED,
            objective="Measured gait activity.",
            assessment="Improving activity tolerance.",
            plan="Continue safe functional progression.",
            signature_name="Therapist",
            signed_at="2026-01-02T12:00:00Z",
            finalization_attestation=True,
        )
        self.therapist.role = User.Role.ADMIN
        self.therapist.save()
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("draft-create", kwargs={"patient_id": self.patient.pk}),
            {"kind": AIArtifact.Kind.PROGRESS},
        )
        artifact = AIArtifact.objects.get()
        self.assertRedirects(
            response, reverse("artifact-detail", kwargs={"artifact_id": artifact.pk})
        )
        self.assertEqual(artifact.status, AIArtifact.Status.DRAFT)

        response = self.client.post(
            reverse("artifact-review", kwargs={"artifact_id": artifact.pk}),
            {"action": "apply"},
        )
        self.assertRedirects(
            response, reverse("artifact-detail", kwargs={"artifact_id": artifact.pk})
        )
        artifact.refresh_from_db()
        self.assertEqual(artifact.status, AIArtifact.Status.DRAFT)

        response = self.client.post(
            reverse("artifact-review", kwargs={"artifact_id": artifact.pk}),
            {"action": "approve", "review_note": "Reviewed source evidence."},
        )
        self.assertRedirects(
            response, reverse("artifact-detail", kwargs={"artifact_id": artifact.pk})
        )
        artifact.refresh_from_db()
        self.assertEqual(artifact.status, AIArtifact.Status.APPROVED)

        response = self.client.post(
            reverse("artifact-review", kwargs={"artifact_id": artifact.pk}),
            {"action": "apply"},
        )
        artifact.refresh_from_db()
        self.assertEqual(artifact.status, AIArtifact.Status.APPLIED)
        self.assertRedirects(
            response, reverse("note-edit", kwargs={"note_id": artifact.applied_note_id})
        )
        self.assertEqual(artifact.applied_note.status, ClinicalNote.Status.DRAFT)

    def test_addendum_preserves_signed_note(self):
        note = ClinicalNote.objects.create(
            patient=self.patient,
            therapist=self.therapist,
            note_type=ClinicalNote.Type.DAILY,
            status=ClinicalNote.Status.SIGNED,
            objective="Original objective.",
            assessment="Original assessment.",
            plan="Original plan.",
            signature_name="Therapist",
            signed_at="2026-01-02T12:00:00Z",
            finalization_attestation=True,
        )
        self.therapist.role = User.Role.ADMIN
        self.therapist.save()
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("note-addendum-create", kwargs={"note_id": note.pk}),
            {"reason": "Clarify measurement", "body": "Measurement was recorded in feet."},
        )
        self.assertRedirects(response, reverse("note-edit", kwargs={"note_id": note.pk}))
        self.assertEqual(NoteAddendum.objects.count(), 1)
        note.refresh_from_db()
        self.assertEqual(note.objective, "Original objective.")
        self.assertEqual(note.status, ClinicalNote.Status.SIGNED)

    def test_month_calendar_scopes_events_and_selects_agenda_day(self):
        selected_start = timezone.make_aware(datetime(2026, 5, 15, 9, 0))
        own_appointment = Appointment.objects.create(
            patient=self.patient,
            therapist=self.therapist,
            kind=Appointment.Kind.FOLLOW_UP,
            starts_at=selected_start,
            ends_at=selected_start.replace(hour=10),
            location="Clinic",
            created_by=self.therapist,
        )
        other_therapist = User.objects.create_user(
            username="other-therapist",
            password="safe-test-password",
            organization=self.organization,
            role=User.Role.THERAPIST,
        )
        other_patient = Patient.objects.create(
            organization=self.organization,
            first_name="Casey",
            last_name="Other",
            date_of_birth="1990-02-03",
            assigned_therapist=other_therapist,
        )
        other_start = timezone.make_aware(datetime(2026, 5, 15, 11, 0))
        other_appointment = Appointment.objects.create(
            patient=other_patient,
            therapist=other_therapist,
            kind=Appointment.Kind.FOLLOW_UP,
            starts_at=other_start,
            ends_at=other_start.replace(hour=12),
            location="Clinic",
            created_by=other_therapist,
        )

        self.client.force_login(self.therapist)
        response = self.client.get(
            reverse("schedule"),
            {"month": "2026-05", "day": "2026-05-15"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["calendar_month"], date(2026, 5, 1))
        self.assertEqual(response.context["selected_day"], date(2026, 5, 15))
        self.assertEqual(response.context["appointments"], [own_appointment])
        visible_ids = {
            appointment.id
            for week in response.context["calendar_weeks"]
            for cell in week
            for appointment in cell["appointments"]
        }
        self.assertIn(own_appointment.id, visible_ids)
        self.assertNotIn(other_appointment.id, visible_ids)
        self.assertContains(response, "data-appointment-calendar")

    def test_calendar_move_preserves_local_time_duration_and_audits(self):
        original_start = timezone.make_aware(datetime(2026, 5, 15, 9, 30))
        appointment = Appointment.objects.create(
            patient=self.patient,
            therapist=self.therapist,
            kind=Appointment.Kind.FOLLOW_UP,
            starts_at=original_start,
            ends_at=original_start + timedelta(minutes=45),
            location="Clinic",
            created_by=self.therapist,
        )
        self.client.force_login(self.therapist)

        response = self.client.post(
            reverse("appointment-move", kwargs={"appointment_id": appointment.pk}),
            {"target_date": "2026-05-20"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["moved"])
        appointment.refresh_from_db()
        moved_start = timezone.localtime(appointment.starts_at)
        self.assertEqual(moved_start.date(), date(2026, 5, 20))
        self.assertEqual((moved_start.hour, moved_start.minute), (9, 30))
        self.assertEqual(appointment.ends_at - appointment.starts_at, timedelta(minutes=45))
        event = AuditEvent.objects.get(
            actor=self.therapist,
            action="appointment.rescheduled",
            object_id=appointment.pk,
        )
        self.assertEqual(event.metadata["source"], "calendar")
        self.assertNotIn("patient", event.metadata)

    def test_calendar_move_enforces_scope_and_schedule_safety(self):
        own_start = timezone.make_aware(datetime(2026, 5, 15, 9, 0))
        own_appointment = Appointment.objects.create(
            patient=self.patient,
            therapist=self.therapist,
            starts_at=own_start,
            ends_at=own_start + timedelta(hours=1),
            location="Clinic",
            created_by=self.therapist,
        )
        other_therapist = User.objects.create_user(
            username="calendar-other",
            password="safe-test-password",
            organization=self.organization,
            role=User.Role.THERAPIST,
        )
        other_patient = Patient.objects.create(
            organization=self.organization,
            first_name="Casey",
            last_name="Calendar",
            date_of_birth="1990-02-03",
            assigned_therapist=other_therapist,
        )
        other_appointment = Appointment.objects.create(
            patient=other_patient,
            therapist=other_therapist,
            starts_at=own_start,
            ends_at=own_start + timedelta(hours=1),
            location="Clinic",
            created_by=other_therapist,
        )
        conflict_start = timezone.make_aware(datetime(2026, 5, 20, 9, 0))
        Appointment.objects.create(
            patient=self.patient,
            therapist=self.therapist,
            starts_at=conflict_start,
            ends_at=conflict_start + timedelta(hours=1),
            location="Clinic",
            created_by=self.therapist,
        )
        self.client.force_login(self.therapist)

        response = self.client.post(
            reverse("appointment-move", kwargs={"appointment_id": other_appointment.pk}),
            {"target_date": "2026-05-20"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 404)

        response = self.client.post(
            reverse("appointment-move", kwargs={"appointment_id": own_appointment.pk}),
            {"target_date": "2026-05-20"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 409)
        own_appointment.refresh_from_db()
        self.assertEqual(timezone.localtime(own_appointment.starts_at).date(), date(2026, 5, 15))

        own_appointment.status = Appointment.Status.COMPLETED
        own_appointment.save(update_fields=["status", "updated_at"])
        response = self.client.post(
            reverse("appointment-move", kwargs={"appointment_id": own_appointment.pk}),
            {"target_date": "2026-05-21"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 409)

        response = self.client.post(
            reverse("appointment-move", kwargs={"appointment_id": own_appointment.pk}),
            {"target_date": "not-a-date"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)

    def test_scheduler_can_move_an_organization_appointment(self):
        appointment_start = timezone.make_aware(datetime(2026, 5, 15, 13, 0))
        appointment = Appointment.objects.create(
            patient=self.patient,
            therapist=self.therapist,
            starts_at=appointment_start,
            ends_at=appointment_start + timedelta(minutes=30),
            location="Clinic",
            created_by=self.therapist,
        )
        scheduler = User.objects.create_user(
            username="calendar-scheduler",
            password="safe-test-password",
            organization=self.organization,
            role=User.Role.SCHEDULER,
        )
        self.client.force_login(scheduler)

        response = self.client.post(
            reverse("appointment-move", kwargs={"appointment_id": appointment.pk}),
            {"target_date": "2026-05-21"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        appointment.refresh_from_db()
        self.assertEqual(timezone.localtime(appointment.starts_at).date(), date(2026, 5, 21))

    def test_react_api_uses_csrf_sessions_and_scoped_schedule_data(self):
        own_start = timezone.make_aware(datetime(2026, 5, 15, 9, 0))
        own_appointment = Appointment.objects.create(
            patient=self.patient,
            therapist=self.therapist,
            starts_at=own_start,
            ends_at=own_start + timedelta(hours=1),
            location="Clinic",
            created_by=self.therapist,
        )
        other_therapist = User.objects.create_user(
            username="react-api-other",
            password="safe-test-password",
            organization=self.organization,
            role=User.Role.THERAPIST,
        )
        other_patient = Patient.objects.create(
            organization=self.organization,
            first_name="Casey",
            last_name="React",
            date_of_birth="1990-02-03",
            assigned_therapist=other_therapist,
        )
        other_appointment = Appointment.objects.create(
            patient=other_patient,
            therapist=other_therapist,
            starts_at=own_start,
            ends_at=own_start + timedelta(hours=1),
            location="Clinic",
            created_by=other_therapist,
        )

        self.assertEqual(self.client.get(reverse("api-me")).status_code, 401)
        api_client = Client(enforce_csrf_checks=True)
        csrf_response = api_client.get(reverse("api-csrf"))
        self.assertEqual(csrf_response.status_code, 200)
        csrf_token = csrf_response.json()["csrfToken"]
        login_response = api_client.post(
            reverse("api-login"),
            data=json.dumps(
                {"username": self.therapist.username, "password": "safe-test-password"}
            ),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(login_response.status_code, 200)
        refreshed_csrf_token = login_response.json()["csrfToken"]
        self.assertEqual(login_response.json()["user"]["id"], str(self.therapist.pk))

        schedule_response = api_client.get(reverse("api-schedule"), {"month": "2026-05"})
        self.assertEqual(schedule_response.status_code, 200)
        visible_ids = {event["id"] for event in schedule_response.json()["events"]}
        self.assertIn(str(own_appointment.pk), visible_ids)
        self.assertNotIn(str(other_appointment.pk), visible_ids)

        patient_response = api_client.get(reverse("api-patient-detail", kwargs={"patient_id": self.patient.pk}))
        self.assertEqual(patient_response.status_code, 200)
        self.assertEqual(patient_response.json()["patient"]["id"], str(self.patient.pk))

        move_response = api_client.post(
            reverse("api-appointment-move", kwargs={"appointment_id": own_appointment.pk}),
            {"target_date": "2026-05-20"},
            HTTP_X_CSRFTOKEN=refreshed_csrf_token,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(move_response.status_code, 200)
        own_appointment.refresh_from_db()
        self.assertEqual(timezone.localtime(own_appointment.starts_at).date(), date(2026, 5, 20))

    def test_react_patient_workspace_uses_role_scoped_workflow_actions(self):
        signed_note = ClinicalNote.objects.create(
            patient=self.patient,
            therapist=self.therapist,
            note_type=ClinicalNote.Type.DAILY,
            status=ClinicalNote.Status.SIGNED,
            objective="Measured safe stair performance.",
            assessment="Improving functional tolerance.",
            plan="Continue safe progression and reassess.",
            signature_name="Therapist",
            signed_at="2026-05-01T12:00:00Z",
            finalization_attestation=True,
        )
        self.client.force_login(self.therapist)

        workspace_response = self.client.get(
            reverse("api-patient-workspace", kwargs={"patient_id": self.patient.pk})
        )
        self.assertEqual(workspace_response.status_code, 200)
        workspace = workspace_response.json()
        self.assertIn("clinical", workspace)
        self.assertIn("operations", workspace)
        self.assertIn("diagnoses", workspace["patient"])
        self.assertNotIn("email", workspace["patient"])

        draft_response = self.client.post(
            reverse("api-draft-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"kind": AIArtifact.Kind.PROGRESS}),
            content_type="application/json",
        )
        self.assertEqual(draft_response.status_code, 201)
        artifact = AIArtifact.objects.get()
        self.assertEqual(artifact.source_note_ids, [str(signed_note.pk)])
        self.assertEqual(artifact.status, AIArtifact.Status.DRAFT)

        review_response = self.client.post(
            reverse("api-draft-review", kwargs={"artifact_id": artifact.pk}),
            data=json.dumps({"action": "approve", "reviewNote": "Reviewed signed evidence."}),
            content_type="application/json",
        )
        self.assertEqual(review_response.status_code, 200)
        artifact.refresh_from_db()
        self.assertEqual(artifact.status, AIArtifact.Status.APPROVED)

        outcome_response = self.client.post(
            reverse("api-outcome-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps(
                {
                    "measure": OutcomeScore.Measure.LEFS,
                    "measuredOn": "2026-05-02",
                    "score": "54",
                    "maximumScore": "",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(outcome_response.status_code, 201)
        self.assertEqual(OutcomeScore.objects.get().maximum_score, 80)

        tug_response = self.client.post(
            reverse("api-outcome-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps(
                {
                    "measure": OutcomeScore.Measure.TUG,
                    "measuredOn": "2026-05-03",
                    "score": "12.5",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(tug_response.status_code, 201)
        self.assertIsNone(tug_response.json()["trend"]["maximum"])

        no_consent_response = self.client.post(
            reverse("api-voice-capture-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps(
                {"consentConfirmed": True, "durationSeconds": 40, "transcript": "Reviewed text."}
            ),
            content_type="application/json",
        )
        self.assertEqual(no_consent_response.status_code, 409)
        Consent.objects.create(
            patient=self.patient,
            kind=Consent.Kind.VOICE,
            document_version="v1",
            status=Consent.Status.SIGNED,
            signature_name="Alex Patient",
            signed_at=timezone.now(),
            recorded_by=self.therapist,
        )
        voice_response = self.client.post(
            reverse("api-voice-capture-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps(
                {"consentConfirmed": True, "durationSeconds": 40, "transcript": "Reviewed text."}
            ),
            content_type="application/json",
        )
        self.assertEqual(voice_response.status_code, 201)
        self.assertTrue(
            AuditEvent.objects.filter(actor=self.therapist, action="voice_transcript.saved").exists()
        )

    def test_react_operations_workspace_hides_clinical_data_from_front_desk(self):
        scheduler = User.objects.create_user(
            username="react-front-desk",
            password="safe-test-password",
            organization=self.organization,
            role=User.Role.SCHEDULER,
        )
        self.client.force_login(scheduler)

        response = self.client.get(
            reverse("api-patient-workspace", kwargs={"patient_id": self.patient.pk})
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn("clinical", payload)
        self.assertIn("operations", payload)
        self.assertNotIn("diagnoses", payload["patient"])
        self.assertNotIn("precautions", payload["patient"])

        intake_response = self.client.post(
            reverse("api-intake-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps(
                {
                    "chiefComplaint": "Pain when climbing stairs.",
                    "functionalGoals": "Return to community walking.",
                    "relevantHistory": "Recorded through the approved intake process.",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(intake_response.status_code, 201)
        self.assertEqual(IntakeSubmission.objects.count(), 1)

    def test_react_audit_api_requires_an_authorized_review_role(self):
        self.client.force_login(self.therapist)
        self.assertEqual(self.client.get(reverse("api-audit-events")).status_code, 403)

        self.therapist.role = User.Role.COMPLIANCE
        self.therapist.save(update_fields=["role"])
        self.client.force_login(self.therapist)
        response = self.client.get(reverse("api-audit-events"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("events", response.json())

    def test_access_control_requires_administrator_role(self):
        self.client.force_login(self.therapist)
        response = self.client.get(reverse("access-control"))
        self.assertEqual(response.status_code, 403)

        response = self.client.get(reverse("employee-onboard"))
        self.assertEqual(response.status_code, 403)

    def test_tenant_admin_cannot_onboard_employee(self):
        self.therapist.role = User.Role.ADMIN
        self.therapist.save()
        self.client.force_login(self.therapist)

        response = self.client.post(
            reverse("employee-onboard"),
            {
                "username": "jamie-pt",
                "first_name": "Jamie",
                "last_name": "Therapist",
                "email": "jamie@example.test",
                "role": User.Role.THERAPIST,
                "credential": "PT-123456",
                "must_use_mfa": "on",
                "least_privilege_confirmed": "on",
                "password1": "Az9!TemporaryCredential2026",
                "password2": "Az9!TemporaryCredential2026",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="jamie-pt").exists())

    def test_tenant_admin_cannot_create_a_platform_super_admin(self):
        self.therapist.role = User.Role.ADMIN
        self.therapist.save()
        self.client.force_login(self.therapist)

        response = self.client.post(
            reverse("employee-onboard"),
            {
                "username": "platform-escalation-attempt",
                "first_name": "Taylor",
                "last_name": "Assistant",
                "email": "taylor@example.test",
                "role": User.Role.SUPER_ADMIN,
                "credential": "",
                "must_use_mfa": "on",
                "least_privilege_confirmed": "on",
                "password1": "Az9!TemporaryCredential2026",
                "password2": "Az9!TemporaryCredential2026",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="platform-escalation-attempt").exists())

    def test_tenant_admin_cannot_create_front_desk_user(self):
        self.therapist.role = User.Role.ADMIN
        self.therapist.save()
        self.client.force_login(self.therapist)

        response = self.client.post(
            reverse("employee-onboard"),
            {
                "username": "morgan-office",
                "first_name": "Morgan",
                "last_name": "Office",
                "email": "morgan@example.test",
                "role": User.Role.SCHEDULER,
                "credential": "",
                "must_use_mfa": "on",
                "least_privilege_confirmed": "on",
                "password1": "Az9!TemporaryCredential2026",
                "password2": "Az9!TemporaryCredential2026",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="morgan-office").exists())

    def test_platform_super_admin_creates_a_client_scoped_user(self):
        client = Organization.objects.create(
            name="Platform Client",
            slug="platform-client",
            client_number=1000,
        )
        other_client = Organization.objects.create(
            name="Other Client",
            slug="other-client",
            client_number=1001,
        )
        platform_admin = User(
            username="clinic_admin",
            role=User.Role.SUPER_ADMIN,
            is_superuser=True,
            is_staff=True,
        )
        platform_admin.set_password("safe-test-password")
        platform_admin.full_clean()
        platform_admin.save()
        self.client.force_login(platform_admin)

        response = self.client.post(
            reverse(
                "api-super-admin-client-users",
                kwargs={"client_number": client.client_number},
            ),
            data=json.dumps(
                {
                    "username": "scheduler-one",
                    "firstName": "Sam",
                    "lastName": "Scheduler",
                    "email": "sam@example.test",
                    "role": User.Role.SCHEDULER,
                    "credential": "",
                    "password": "Az9!TemporaryCredential2026",
                    "confirmPassword": "Az9!TemporaryCredential2026",
                    "mustUseMfa": True,
                    "organization": str(other_client.pk),
                    "isSuperuser": False,
                    "isStaff": False,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        account = User.objects.get(username="scheduler-one")
        self.assertEqual(account.organization, client)
        self.assertEqual(account.role, User.Role.SCHEDULER)
        self.assertFalse(account.is_superuser)
        self.assertFalse(account.is_staff)
        self.assertTrue(account.must_use_mfa)
        self.assertTrue(account.check_password("Az9!TemporaryCredential2026"))
        event = AuditEvent.objects.get(
            actor=platform_admin,
            action="client_user.created",
            object_id=account.pk,
        )
        self.assertEqual(event.organization, client)
        self.assertEqual(event.metadata["client_number"], client.client_number)
        self.assertNotIn("password", event.metadata)

    def test_tenant_admin_cannot_manage_another_client_user(self):
        self.therapist.role = User.Role.ADMIN
        self.therapist.save()
        other_org = Organization.objects.create(name="East Clinic", slug="east")
        other_admin = User.objects.create_user(
            username="east-admin",
            password="safe-test-password",
            organization=other_org,
            role=User.Role.ADMIN,
        )
        self.client.force_login(self.therapist)
        response = self.client.get(
            reverse("access-user-update", kwargs={"user_id": other_admin.pk})
        )
        self.assertEqual(response.status_code, 403)

    def test_tenant_admin_cannot_call_platform_client_user_api(self):
        client = Organization.objects.create(
            name="Protected Client",
            slug="protected-client",
            client_number=1000,
        )
        self.therapist.role = User.Role.ADMIN
        self.therapist.save(update_fields=["role"])
        self.client.force_login(self.therapist)

        response = self.client.get(
            reverse(
                "api-super-admin-client-users",
                kwargs={"client_number": client.client_number},
            )
        )
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            reverse(
                "api-super-admin-client-users",
                kwargs={"client_number": client.client_number},
            ),
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_platform_client_user_api_rejects_platform_privileges(self):
        client = Organization.objects.create(
            name="Role Client",
            slug="role-client",
            client_number=1000,
        )
        platform_admin = User(
            username="clinic_admin",
            role=User.Role.SUPER_ADMIN,
            is_superuser=True,
        )
        platform_admin.set_password("safe-test-password")
        platform_admin.full_clean()
        platform_admin.save()
        self.client.force_login(platform_admin)

        response = self.client.post(
            reverse(
                "api-super-admin-client-users",
                kwargs={"client_number": client.client_number},
            ),
            data=json.dumps(
                {
                    "username": "escalation-attempt",
                    "firstName": "Eve",
                    "lastName": "Escalation",
                    "email": "eve@example.test",
                    "role": User.Role.SUPER_ADMIN,
                    "password": "Az9!TemporaryCredential2026",
                    "confirmPassword": "Az9!TemporaryCredential2026",
                    "isSuperuser": True,
                    "isStaff": True,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("role", response.json()["errors"])
        self.assertIn("isSuperuser", response.json()["errors"])
        self.assertIn("isStaff", response.json()["errors"])
        self.assertFalse(User.objects.filter(username="escalation-attempt").exists())

    def test_platform_super_admin_can_sign_in_from_any_client_portal(self):
        client = Organization.objects.create(
            name="Portal Client",
            slug="portal-client",
            client_number=1000,
        )
        platform_admin = User(
            username="clinic_admin",
            role=User.Role.SUPER_ADMIN,
            is_superuser=True,
        )
        platform_admin.set_password("safe-test-password")
        platform_admin.full_clean()
        platform_admin.save()

        response = self.client.post(
            reverse("api-login"),
            data=json.dumps(
                {
                    "username": "clinic_admin",
                    "password": "safe-test-password",
                    "portalSlug": client.slug,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["user"]["capabilities"]["isSuperAdmin"])

        response = self.client.get(reverse("api-patients"))
        self.assertEqual(response.status_code, 403)

    def test_platform_super_admin_can_create_a_client_and_primary_admin(self):
        platform_admin = User(
            username="clinic_admin",
            role=User.Role.SUPER_ADMIN,
            is_superuser=True,
        )
        platform_admin.set_password("safe-test-password")
        platform_admin.full_clean()
        platform_admin.save()
        self.client.force_login(platform_admin)

        response = self.client.post(
            reverse("api-super-admin-client-create"),
            data=json.dumps(
                {
                    "clientName": "New Platform Client",
                    "clientEmail": "support@new-platform-client.example.test",
                    "addressLine1": "1 Platform Way",
                    "city": "Boston",
                    "state": "MA",
                    "zipCode": "02101",
                    "subscriptionTier": "professional",
                    "timezone": "America/New_York",
                    "adminFirstName": "New",
                    "adminLastName": "Administrator",
                    "adminEmail": "admin@new-platform-client.example.test",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        client = Organization.objects.get(name="New Platform Client")
        primary_admin = User.objects.get(
            username="admin@new-platform-client.example.test"
        )
        self.assertEqual(primary_admin.organization, client)
        self.assertEqual(primary_admin.role, User.Role.ADMIN)
        self.assertFalse(primary_admin.is_superuser)
        event = AuditEvent.objects.get(
            actor=platform_admin,
            action="client.created",
            object_id=client.pk,
        )
        self.assertEqual(event.organization, client)

        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ["admin@new-platform-client.example.test"])
        invitation_url = response.json()["invitationUrl"]
        self.assertIn(invitation_url, sent.body)
        from django.conf import settings
        self.assertTrue(invitation_url.startswith(settings.FRONTEND_BASE_URL))

    def test_resend_invite_emails_a_fresh_link_and_invalidates_the_old_one(self):
        platform_admin = User(username="clinic_admin", role=User.Role.SUPER_ADMIN, is_superuser=True)
        platform_admin.set_password("safe-test-password")
        platform_admin.full_clean()
        platform_admin.save()
        self.client.force_login(platform_admin)

        create_response = self.client.post(
            reverse("api-super-admin-client-create"),
            data=json.dumps({
                "clientName": "Resend Client", "clientEmail": "support@resend-client.example.test",
                "addressLine1": "1 Resend Way", "city": "Boston", "state": "MA", "zipCode": "02101",
                "subscriptionTier": "professional", "timezone": "America/New_York",
                "adminFirstName": "Resend", "adminLastName": "Admin", "adminEmail": "admin@resend-client.example.test",
            }),
            content_type="application/json",
        )
        client_number = create_response.json()["client"]["clientNumber"]
        original_invite = ClientInvitation.objects.get(user__username="admin@resend-client.example.test")
        mail.outbox.clear()

        response = self.client.post(reverse("api-super-admin-client-admin-resend-invite", kwargs={"client_number": client_number}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(response.json()["invitationUrl"], mail.outbox[0].body)

        original_invite.refresh_from_db()
        self.assertIsNotNone(original_invite.used_at)

    def test_invitation_email_failure_does_not_block_client_creation(self):
        platform_admin = User(username="clinic_admin", role=User.Role.SUPER_ADMIN, is_superuser=True)
        platform_admin.set_password("safe-test-password")
        platform_admin.full_clean()
        platform_admin.save()
        self.client.force_login(platform_admin)

        with patch("care.notifications.send_mail", side_effect=OSError("smtp unavailable")):
            response = self.client.post(
                reverse("api-super-admin-client-create"),
                data=json.dumps({
                    "clientName": "Resilient Client", "clientEmail": "support@resilient-client.example.test",
                    "addressLine1": "1 Resilient Way", "city": "Boston", "state": "MA", "zipCode": "02101",
                    "subscriptionTier": "professional", "timezone": "America/New_York",
                    "adminFirstName": "Resilient", "adminLastName": "Admin", "adminEmail": "admin@resilient-client.example.test",
                }),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Organization.objects.filter(name="Resilient Client").exists())

    def _platform_admin(self):
        platform_admin = User(
            username="clinic_admin",
            role=User.Role.SUPER_ADMIN,
            is_superuser=True,
        )
        platform_admin.set_password("safe-test-password")
        platform_admin.full_clean()
        platform_admin.save()
        return platform_admin

    def test_archive_blocks_access_without_deleting_data(self):
        platform_admin = self._platform_admin()
        self.organization.client_number = 5000
        self.organization.save(update_fields=["client_number"])
        self.client.force_login(platform_admin)

        response = self.client.delete(
            reverse(
                "api-super-admin-client-detail",
                kwargs={"client_number": self.organization.client_number},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.organization.refresh_from_db()
        self.assertIsNotNone(self.organization.archived_at)
        self.assertEqual(self.organization.archived_by, platform_admin)

        # Data is preserved.
        self.assertTrue(Patient.objects.filter(pk=self.patient.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.therapist.pk).exists())

        # The therapist can no longer sign in to this archived organization.
        login_response = self.client.post(
            reverse("api-login"),
            data=json.dumps({"username": "therapist", "password": "safe-test-password"}),
            content_type="application/json",
        )
        self.assertEqual(login_response.status_code, 403)
        self.assertEqual(login_response.json()["code"], "ORGANIZATION_ARCHIVED")

        # Re-archiving is rejected.
        second_response = self.client.delete(
            reverse(
                "api-super-admin-client-detail",
                kwargs={"client_number": self.organization.client_number},
            )
        )
        self.assertEqual(second_response.status_code, 409)

    def test_archived_clients_excluded_from_default_list(self):
        platform_admin = self._platform_admin()
        self.organization.client_number = 5001
        self.organization.save(update_fields=["client_number"])
        self.client.force_login(platform_admin)
        self.client.delete(
            reverse(
                "api-super-admin-client-detail",
                kwargs={"client_number": self.organization.client_number},
            )
        )

        default_response = self.client.get(reverse("api-super-admin-clients"))
        listed_numbers = {row["clientNumber"] for row in default_response.json()["clients"]}
        self.assertNotIn(self.organization.client_number, listed_numbers)

        included_response = self.client.get(
            reverse("api-super-admin-clients"), {"includeArchived": "true"}
        )
        listed_numbers = {row["clientNumber"] for row in included_response.json()["clients"]}
        self.assertIn(self.organization.client_number, listed_numbers)

    def test_client_edit_records_audit_event(self):
        platform_admin = self._platform_admin()
        self.organization.client_number = 5002
        self.organization.save(update_fields=["client_number"])
        self.client.force_login(platform_admin)

        response = self.client.patch(
            reverse(
                "api-super-admin-client-detail",
                kwargs={"client_number": self.organization.client_number},
            ),
            data=json.dumps(
                {
                    "clientName": self.organization.name,
                    "clientEmail": "updated@north-clinic.example.test",
                    "addressLine1": "1 North Way",
                    "city": "Boston",
                    "state": "MA",
                    "zipCode": "02101",
                    "subscriptionTier": self.organization.subscription_tier,
                    "timezone": self.organization.timezone,
                    "comments": "Updated by platform admin.",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        event = AuditEvent.objects.get(
            actor=platform_admin,
            action="client.updated",
            object_id=self.organization.pk,
        )
        self.assertIn("comments", event.metadata["changed_fields"])
        self.assertIn("support_email", event.metadata["changed_fields"])

    def test_client_audit_events_endpoint_excludes_clinical_events_and_requires_super_admin(self):
        platform_admin = self._platform_admin()
        self.organization.client_number = 5003
        self.organization.save(update_fields=["client_number"])
        record_audit_event(
            actor=self.therapist,
            action="patient.viewed",
            obj=self.patient,
            patient=self.patient,
        )

        self.client.force_login(self.therapist)
        denied_response = self.client.get(
            reverse(
                "api-super-admin-client-audit-events",
                kwargs={"client_number": self.organization.client_number},
            )
        )
        self.assertEqual(denied_response.status_code, 403)

        self.client.force_login(platform_admin)
        response = self.client.get(
            reverse(
                "api-super-admin-client-audit-events",
                kwargs={"client_number": self.organization.client_number},
            )
        )
        self.assertEqual(response.status_code, 200)
        actions = [event["action"] for event in response.json()["events"]]
        self.assertNotIn("patient.viewed", actions)

    def _create_client_via_api(self, platform_admin, name="Invitee Clinic", admin_email="ivy@invitee-clinic.example.test"):
        self.client.force_login(platform_admin)
        response = self.client.post(
            reverse("api-super-admin-client-create"),
            data=json.dumps(
                {
                    "clientName": name,
                    "clientEmail": "support@invitee-clinic.example.test",
                    "addressLine1": "1 Invitee Way",
                    "city": "Durham",
                    "state": "NC",
                    "zipCode": "27701",
                    "subscriptionTier": "professional",
                    "timezone": "America/New_York",
                    "adminFirstName": "Ivy",
                    "adminLastName": "Invitee",
                    "adminEmail": admin_email,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertIn("invitationUrl", payload)
        self.assertIn(payload["developmentInviteToken"], payload["invitationUrl"])
        self.client.logout()
        return payload

    def test_activation_flow_lets_new_admin_set_password_and_sign_in(self):
        platform_admin = self._platform_admin()
        payload = self._create_client_via_api(platform_admin)
        token = payload["developmentInviteToken"]

        preview_response = self.client.get(
            reverse("api-activate-invitation"), {"token": token}
        )
        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(preview_response.json()["email"], "ivy@invitee-clinic.example.test")
        self.assertEqual(preview_response.json()["organizationName"], "Invitee Clinic")

        activate_response = self.client.post(
            reverse("api-activate-invitation"),
            data=json.dumps({"token": token, "password": "Az9!BrandNewPassword2026"}),
            content_type="application/json",
        )
        self.assertEqual(activate_response.status_code, 200)
        activated_user = activate_response.json()["user"]
        self.assertEqual(activated_user["username"], "ivy@invitee-clinic.example.test")
        self.assertEqual(activated_user["organization"]["name"], "Invitee Clinic")

        # The session created by activation is authenticated as the new admin.
        me_response = self.client.get(reverse("api-me"))
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()["user"]["username"], "ivy@invitee-clinic.example.test")

        # The token is single-use.
        second_attempt = self.client.post(
            reverse("api-activate-invitation"),
            data=json.dumps({"token": token, "password": "Az9!AnotherPassword2026"}),
            content_type="application/json",
        )
        self.assertEqual(second_attempt.status_code, 410)

    def test_activation_rejects_short_password(self):
        platform_admin = self._platform_admin()
        payload = self._create_client_via_api(platform_admin)
        response = self.client.post(
            reverse("api-activate-invitation"),
            data=json.dumps({"token": payload["developmentInviteToken"], "password": "short"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_activation_blocked_when_organization_suspended(self):
        platform_admin = self._platform_admin()
        payload = self._create_client_via_api(platform_admin, name="Suspended Before Activation")
        org = Organization.objects.get(name="Suspended Before Activation")
        self.client.force_login(platform_admin)
        self.client.patch(
            reverse(
                "api-super-admin-client-status",
                kwargs={"client_number": org.client_number, "action": "suspend"},
            ),
            data=json.dumps({"reason": "Testing"}),
            content_type="application/json",
        )
        self.client.logout()

        response = self.client.post(
            reverse("api-activate-invitation"),
            data=json.dumps({"token": payload["developmentInviteToken"], "password": "Az9!BrandNewPassword2026"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "ORGANIZATION_SUSPENDED")

    def test_platform_wide_users_list_spans_every_client_and_requires_super_admin(self):
        platform_admin = self._platform_admin()
        self._create_client_via_api(platform_admin, name="Alpha Rehab", admin_email="alpha-admin@example.test")
        self._create_client_via_api(platform_admin, name="Beta Rehab", admin_email="beta-admin@example.test")

        self.client.force_login(self.therapist)
        denied = self.client.get(reverse("api-super-admin-users"))
        self.assertEqual(denied.status_code, 403)

        self.client.force_login(platform_admin)
        response = self.client.get(reverse("api-super-admin-users"))
        self.assertEqual(response.status_code, 200)
        usernames = {row["username"] for row in response.json()["users"]}
        self.assertIn("alpha-admin@example.test", usernames)
        self.assertIn("beta-admin@example.test", usernames)
        client_numbers = {row["clientNumber"] for row in response.json()["users"]}
        alpha_number = Organization.objects.get(name="Alpha Rehab").client_number
        beta_number = Organization.objects.get(name="Beta Rehab").client_number
        self.assertIn(alpha_number, client_numbers)
        self.assertIn(beta_number, client_numbers)

        filtered = self.client.get(reverse("api-super-admin-users"), {"clientNumber": str(alpha_number)})
        filtered_names = {row["clientName"] for row in filtered.json()["users"]}
        self.assertEqual(filtered_names, {"Alpha Rehab"})

    def test_platform_wide_user_create_targets_the_chosen_client(self):
        platform_admin = self._platform_admin()
        self._create_client_via_api(platform_admin, name="Gamma Rehab", admin_email="gamma-admin@example.test")
        client = Organization.objects.get(name="Gamma Rehab")
        self.client.force_login(platform_admin)

        response = self.client.post(
            reverse("api-super-admin-users"),
            data=json.dumps(
                {
                    "clientNumber": client.client_number,
                    "username": "new-therapist",
                    "firstName": "New",
                    "lastName": "Therapist",
                    "email": "new-therapist@example.test",
                    "role": User.Role.THERAPIST,
                    "password": "Az9!AnotherPassword2026",
                    "confirmPassword": "Az9!AnotherPassword2026",
                    "licenseNumber": "PT-3000",
                    "licenseIssuingState": "NY",
                    "licenseExpiresAt": (date.today() + timedelta(days=300)).isoformat(),
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        created = User.objects.get(username="new-therapist")
        self.assertEqual(created.organization, client)

        missing_client = self.client.post(
            reverse("api-super-admin-users"),
            data=json.dumps({"username": "orphan", "password": "Az9!AnotherPassword2026"}),
            content_type="application/json",
        )
        self.assertEqual(missing_client.status_code, 422)
        self.assertIn("clientNumber", missing_client.json()["errors"])

    def test_platform_user_list_is_paginated(self):
        platform_admin = self._platform_admin()
        client = Organization.objects.create(name="Pagination Rehab", slug="pagination-rehab", client_number=9001)
        for index in range(12):
            User.objects.create_user(
                username=f"page-user-{index}", password="safe-test-password",
                organization=client, role=User.Role.THERAPIST,
            )
        self.client.force_login(platform_admin)

        first_page = self.client.get(reverse("api-super-admin-users"), {"clientNumber": str(client.client_number), "pageSize": "10"})
        self.assertEqual(first_page.status_code, 200)
        payload = first_page.json()
        self.assertEqual(payload["total"], 12)
        self.assertEqual(payload["page"], 1)
        self.assertEqual(payload["pageSize"], 10)
        self.assertEqual(len(payload["users"]), 10)

        second_page = self.client.get(
            reverse("api-super-admin-users"), {"clientNumber": str(client.client_number), "pageSize": "10", "page": "2"}
        )
        self.assertEqual(len(second_page.json()["users"]), 2)
        first_ids = {row["id"] for row in payload["users"]}
        second_ids = {row["id"] for row in second_page.json()["users"]}
        self.assertEqual(first_ids & second_ids, set())

    def test_organization_admin_can_list_and_create_users_for_their_own_org(self):
        org_admin = User.objects.create_user(
            username="org-admin",
            password="safe-test-password",
            organization=self.organization,
            role=User.Role.ADMIN,
        )
        self.client.force_login(org_admin)

        response = self.client.post(
            reverse("api-org-users"),
            data=json.dumps(
                {
                    "username": "new-office-admin",
                    "firstName": "New",
                    "lastName": "OfficeAdmin",
                    "email": "new-office-admin@example.test",
                    "role": User.Role.SCHEDULER,
                    "password": "Az9!OrgAdminPassword2026",
                    "confirmPassword": "Az9!OrgAdminPassword2026",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        created = User.objects.get(username="new-office-admin")
        self.assertEqual(created.organization, self.organization)

        listing = self.client.get(reverse("api-org-users"))
        self.assertEqual(listing.status_code, 200)
        usernames = {row["username"] for row in listing.json()["users"]}
        self.assertIn("new-office-admin", usernames)
        self.assertIn("therapist", usernames)

    def test_organization_user_list_is_paginated(self):
        org_admin = User.objects.create_user(
            username="org-admin-paginated", password="safe-test-password",
            organization=self.organization, role=User.Role.ADMIN,
        )
        for index in range(12):
            User.objects.create_user(
                username=f"org-page-user-{index}", password="safe-test-password",
                organization=self.organization, role=User.Role.THERAPIST,
            )
        self.client.force_login(org_admin)

        first_page = self.client.get(reverse("api-org-users"), {"pageSize": "10"})
        self.assertEqual(first_page.status_code, 200)
        payload = first_page.json()
        self.assertGreaterEqual(payload["total"], 14)  # 12 new + org_admin + self.therapist
        self.assertEqual(payload["page"], 1)
        self.assertEqual(payload["pageSize"], 10)
        self.assertEqual(len(payload["users"]), 10)

        second_page = self.client.get(reverse("api-org-users"), {"pageSize": "10", "page": "2"})
        self.assertGreaterEqual(len(second_page.json()["users"]), 4)

    def test_organization_users_endpoint_ignores_any_client_hint_in_the_payload(self):
        other_org = Organization.objects.create(name="Other Org", slug="other-org-users")
        org_admin = User.objects.create_user(
            username="org-admin-2",
            password="safe-test-password",
            organization=self.organization,
            role=User.Role.ADMIN,
        )
        self.client.force_login(org_admin)

        response = self.client.post(
            reverse("api-org-users"),
            data=json.dumps(
                {
                    "clientNumber": 9999,
                    "organizationId": str(other_org.pk),
                    "username": "tenant-safe-user",
                    "firstName": "Tenant",
                    "lastName": "Safe",
                    "email": "tenant-safe@example.test",
                    "role": User.Role.THERAPIST,
                    "password": "Az9!TenantSafePassword2026",
                    "confirmPassword": "Az9!TenantSafePassword2026",
                    "licenseNumber": "PT-3001",
                    "licenseIssuingState": "NC",
                    "licenseExpiresAt": (date.today() + timedelta(days=300)).isoformat(),
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        created = User.objects.get(username="tenant-safe-user")
        self.assertEqual(created.organization, self.organization)
        self.assertNotEqual(created.organization, other_org)

    def test_non_admin_role_cannot_create_organization_users(self):
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-org-users"),
            data=json.dumps(
                {
                    "username": "blocked-user",
                    "password": "Az9!BlockedPassword2026",
                    "confirmPassword": "Az9!BlockedPassword2026",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="blocked-user").exists())

    def test_platform_super_admin_cannot_use_the_tenant_users_endpoint(self):
        platform_admin = self._platform_admin()
        self.client.force_login(platform_admin)
        response = self.client.get(reverse("api-org-users"))
        self.assertEqual(response.status_code, 403)

    def test_super_admin_can_edit_a_tenant_user(self):
        platform_admin = self._platform_admin()
        self.client.force_login(platform_admin)
        response = self.client.patch(
            reverse("api-super-admin-user-detail", kwargs={"user_id": self.therapist.pk}),
            data=json.dumps({"firstName": "Updated", "credential": "DPT", "role": User.Role.DIRECTOR}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.therapist.refresh_from_db()
        self.assertEqual(self.therapist.first_name, "Updated")
        self.assertEqual(self.therapist.credential, "DPT")
        self.assertEqual(self.therapist.role, User.Role.DIRECTOR)
        self.assertTrue(
            AuditEvent.objects.filter(actor=platform_admin, action="client_user.role_changed", object_id=self.therapist.pk).exists()
        )

    def test_super_admin_can_deactivate_and_reactivate_a_tenant_user(self):
        platform_admin = self._platform_admin()
        office_staff = User.objects.create_user(
            username="office-staff", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        self.client.force_login(platform_admin)

        response = self.client.patch(
            reverse("api-super-admin-user-detail", kwargs={"user_id": office_staff.pk}),
            data=json.dumps({"active": False}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        office_staff.refresh_from_db()
        self.assertFalse(office_staff.is_active)
        self.assertTrue(
            AuditEvent.objects.filter(action="client_user.deactivated", object_id=office_staff.pk).exists()
        )

        # A deactivated account cannot authenticate.
        login_attempt = self.client.post(
            reverse("api-login"),
            data=json.dumps({"username": "office-staff", "password": "safe-test-password"}),
            content_type="application/json",
        )
        self.assertEqual(login_attempt.status_code, 401)

        self.client.force_login(platform_admin)
        response = self.client.patch(
            reverse("api-super-admin-user-detail", kwargs={"user_id": office_staff.pk}),
            data=json.dumps({"active": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        office_staff.refresh_from_db()
        self.assertTrue(office_staff.is_active)
        self.assertTrue(
            AuditEvent.objects.filter(action="client_user.reactivated", object_id=office_staff.pk).exists()
        )

    def test_cannot_deactivate_the_only_active_organization_administrator(self):
        platform_admin = self._platform_admin()
        sole_admin = User.objects.create_user(
            username="sole-admin", password="safe-test-password", organization=self.organization, role=User.Role.ADMIN
        )
        self.client.force_login(platform_admin)
        response = self.client.patch(
            reverse("api-super-admin-user-detail", kwargs={"user_id": sole_admin.pk}),
            data=json.dumps({"active": False}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        sole_admin.refresh_from_db()
        self.assertTrue(sole_admin.is_active)

    def test_cannot_deactivate_a_therapist_with_an_active_caseload(self):
        platform_admin = self._platform_admin()
        self.client.force_login(platform_admin)
        response = self.client.patch(
            reverse("api-super-admin-user-detail", kwargs={"user_id": self.therapist.pk}),
            data=json.dumps({"active": False}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.therapist.refresh_from_db()
        self.assertTrue(self.therapist.is_active)

    def test_super_admin_can_soft_delete_a_tenant_user(self):
        platform_admin = self._platform_admin()
        staff = User.objects.create_user(
            username="soft-delete-me", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        self.client.force_login(platform_admin)

        response = self.client.delete(
            reverse("api-super-admin-user-detail", kwargs={"user_id": staff.pk}),
        )
        self.assertEqual(response.status_code, 200)
        staff.refresh_from_db()
        self.assertIsNotNone(staff.archived_at)
        self.assertFalse(staff.is_active)
        self.assertEqual(staff.archived_by, platform_admin)
        self.assertTrue(User.objects.filter(pk=staff.pk).exists())  # data preserved, not hard-deleted

        default_listing = self.client.get(reverse("api-super-admin-users"))
        self.assertNotIn(str(staff.pk), {row["id"] for row in default_listing.json()["users"]})
        archived_listing = self.client.get(reverse("api-super-admin-users"), {"status": "archived"})
        self.assertIn(str(staff.pk), {row["id"] for row in archived_listing.json()["users"]})

        second_attempt = self.client.delete(
            reverse("api-super-admin-user-detail", kwargs={"user_id": staff.pk}),
        )
        self.assertEqual(second_attempt.status_code, 409)

    def test_super_admin_can_restore_a_soft_deleted_tenant_user(self):
        platform_admin = self._platform_admin()
        staff = User.objects.create_user(
            username="restore-me", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        self.client.force_login(platform_admin)
        self.client.delete(reverse("api-super-admin-user-detail", kwargs={"user_id": staff.pk}))
        staff.refresh_from_db()
        self.assertIsNotNone(staff.archived_at)

        response = self.client.patch(
            reverse("api-super-admin-user-detail", kwargs={"user_id": staff.pk}),
            data=json.dumps({"active": True, "archive": False}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        staff.refresh_from_db()
        self.assertIsNone(staff.archived_at)
        self.assertIsNone(staff.archived_by)
        self.assertTrue(staff.is_active)

        default_listing = self.client.get(reverse("api-super-admin-users"))
        self.assertIn(str(staff.pk), {row["id"] for row in default_listing.json()["users"]})

    def test_super_admin_can_change_a_tenant_users_username_and_password(self):
        platform_admin = self._platform_admin()
        staff = User.objects.create_user(
            username="old-username", password="original-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        self.client.force_login(platform_admin)

        response = self.client.patch(
            reverse("api-super-admin-user-detail", kwargs={"user_id": staff.pk}),
            data=json.dumps({"username": "new-username", "password": "brand-new-password-123"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        staff.refresh_from_db()
        self.assertEqual(staff.username, "new-username")
        self.assertTrue(staff.check_password("brand-new-password-123"))
        self.assertTrue(staff.must_change_password)

    def test_admin_password_reset_forces_change_on_next_login(self):
        platform_admin = self._platform_admin()
        staff = User.objects.create_user(
            username="forced-change-target", password="original-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        self.client.force_login(platform_admin)
        self.client.patch(
            reverse("api-super-admin-user-detail", kwargs={"user_id": staff.pk}),
            data=json.dumps({"password": "admin-set-password-123"}),
            content_type="application/json",
        )
        staff.refresh_from_db()
        self.assertTrue(staff.must_change_password)
        self.client.logout()

        self.client.force_login(staff)
        blocked = self.client.get(reverse("api-dashboard"))
        self.assertEqual(blocked.status_code, 403)

        me_response = self.client.get(reverse("api-me"))
        self.assertTrue(me_response.json()["user"]["mustChangePassword"])

        change_response = self.client.post(
            reverse("api-change-password"),
            data=json.dumps({"newPassword": "my-own-new-password-456", "confirmPassword": "my-own-new-password-456"}),
            content_type="application/json",
        )
        self.assertEqual(change_response.status_code, 200)
        staff.refresh_from_db()
        self.assertFalse(staff.must_change_password)
        self.assertTrue(staff.check_password("my-own-new-password-456"))

        allowed = self.client.get(reverse("api-dashboard"))
        self.assertEqual(allowed.status_code, 200)

    def test_forced_password_change_rejects_mismatched_confirmation(self):
        staff = User.objects.create_user(
            username="mismatch-target",
            password="original-password",
            organization=self.organization,
            role=User.Role.SCHEDULER,
            must_change_password=True,
        )
        self.client.force_login(staff)
        response = self.client.post(
            reverse("api-change-password"),
            data=json.dumps({"newPassword": "my-own-new-password-456", "confirmPassword": "does-not-match"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        staff.refresh_from_db()
        self.assertTrue(staff.must_change_password)
        self.assertTrue(staff.check_password("original-password"))

    def test_super_admin_cannot_reuse_an_existing_username(self):
        platform_admin = self._platform_admin()
        User.objects.create_user(
            username="taken-username", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        staff = User.objects.create_user(
            username="other-username", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        self.client.force_login(platform_admin)
        response = self.client.patch(
            reverse("api-super-admin-user-detail", kwargs={"user_id": staff.pk}),
            data=json.dumps({"username": "taken-username"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)
        staff.refresh_from_db()
        self.assertEqual(staff.username, "other-username")

    def test_super_admin_password_reset_rejects_weak_password(self):
        platform_admin = self._platform_admin()
        staff = User.objects.create_user(
            username="weak-pw-target", password="original-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        self.client.force_login(platform_admin)
        response = self.client.patch(
            reverse("api-super-admin-user-detail", kwargs={"user_id": staff.pk}),
            data=json.dumps({"password": "123"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)
        staff.refresh_from_db()
        self.assertTrue(staff.check_password("original-password"))

    def test_non_super_admin_cannot_edit_or_delete_tenant_users(self):
        self.therapist.role = User.Role.ADMIN
        self.therapist.save(update_fields=["role"])
        target = User.objects.create_user(
            username="target-user", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        self.client.force_login(self.therapist)
        response = self.client.patch(
            reverse("api-super-admin-user-detail", kwargs={"user_id": target.pk}),
            data=json.dumps({"active": False}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.delete(reverse("api-super-admin-user-detail", kwargs={"user_id": target.pk}))
        self.assertEqual(response.status_code, 403)

    def test_organization_admin_can_edit_deactivate_reactivate_own_org_user(self):
        org_admin = User.objects.create_user(
            username="edit-admin", password="safe-test-password", organization=self.organization, role=User.Role.ADMIN
        )
        staff = User.objects.create_user(
            username="edit-target", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        self.client.force_login(org_admin)

        edit_response = self.client.patch(
            reverse("api-org-user-detail", kwargs={"user_id": staff.pk}),
            data=json.dumps({"firstName": "Renamed", "credential": "CMA"}),
            content_type="application/json",
        )
        self.assertEqual(edit_response.status_code, 200)
        staff.refresh_from_db()
        self.assertEqual(staff.first_name, "Renamed")
        self.assertEqual(staff.credential, "CMA")

        deactivate_response = self.client.patch(
            reverse("api-org-user-detail", kwargs={"user_id": staff.pk}),
            data=json.dumps({"active": False}),
            content_type="application/json",
        )
        self.assertEqual(deactivate_response.status_code, 200)
        staff.refresh_from_db()
        self.assertFalse(staff.is_active)

        reactivate_response = self.client.patch(
            reverse("api-org-user-detail", kwargs={"user_id": staff.pk}),
            data=json.dumps({"active": True}),
            content_type="application/json",
        )
        self.assertEqual(reactivate_response.status_code, 200)
        staff.refresh_from_db()
        self.assertTrue(staff.is_active)

    def test_organization_admin_can_soft_delete_own_org_user(self):
        org_admin = User.objects.create_user(
            username="delete-admin", password="safe-test-password", organization=self.organization, role=User.Role.ADMIN
        )
        staff = User.objects.create_user(
            username="delete-target", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        self.client.force_login(org_admin)
        response = self.client.delete(reverse("api-org-user-detail", kwargs={"user_id": staff.pk}))
        self.assertEqual(response.status_code, 200)
        staff.refresh_from_db()
        self.assertIsNotNone(staff.archived_at)
        self.assertFalse(staff.is_active)
        self.assertTrue(User.objects.filter(pk=staff.pk).exists())

        listing = self.client.get(reverse("api-org-users"))
        self.assertNotIn(str(staff.pk), {row["id"] for row in listing.json()["users"]})

    def test_organization_admin_can_restore_own_soft_deleted_user(self):
        org_admin = User.objects.create_user(
            username="restore-admin", password="safe-test-password", organization=self.organization, role=User.Role.ADMIN
        )
        staff = User.objects.create_user(
            username="restore-target", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        self.client.force_login(org_admin)
        self.client.delete(reverse("api-org-user-detail", kwargs={"user_id": staff.pk}))
        staff.refresh_from_db()
        self.assertIsNotNone(staff.archived_at)

        response = self.client.patch(
            reverse("api-org-user-detail", kwargs={"user_id": staff.pk}),
            data=json.dumps({"active": False, "archive": False}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        staff.refresh_from_db()
        self.assertIsNone(staff.archived_at)
        self.assertFalse(staff.is_active)

        listing = self.client.get(reverse("api-org-users"))
        self.assertIn(str(staff.pk), {row["id"] for row in listing.json()["users"]})

    def test_organization_admin_can_reset_another_users_password_and_username(self):
        org_admin = User.objects.create_user(
            username="pw-reset-admin", password="safe-test-password", organization=self.organization, role=User.Role.ADMIN
        )
        staff = User.objects.create_user(
            username="pw-reset-target", password="original-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        self.client.force_login(org_admin)
        response = self.client.patch(
            reverse("api-org-user-detail", kwargs={"user_id": staff.pk}),
            data=json.dumps({"username": "pw-reset-target-renamed", "password": "brand-new-password-123"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        staff.refresh_from_db()
        self.assertEqual(staff.username, "pw-reset-target-renamed")
        self.assertTrue(staff.check_password("brand-new-password-123"))

    def test_organization_admin_cannot_reset_their_own_password_via_edit(self):
        org_admin = User.objects.create_user(
            username="self-pw-admin", password="original-password", organization=self.organization, role=User.Role.ADMIN
        )
        self.client.force_login(org_admin)
        response = self.client.patch(
            reverse("api-org-user-detail", kwargs={"user_id": org_admin.pk}),
            data=json.dumps({"password": "brand-new-password-123"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)
        org_admin.refresh_from_db()
        self.assertTrue(org_admin.check_password("original-password"))

    def test_organization_admin_cannot_manage_users_in_another_org(self):
        org_admin = User.objects.create_user(
            username="isolated-admin", password="safe-test-password", organization=self.organization, role=User.Role.ADMIN
        )
        other_org = Organization.objects.create(name="Cross Org", slug="cross-org-users")
        other_user = User.objects.create_user(
            username="cross-org-user", password="safe-test-password", organization=other_org, role=User.Role.SCHEDULER
        )
        self.client.force_login(org_admin)
        response = self.client.patch(
            reverse("api-org-user-detail", kwargs={"user_id": other_user.pk}),
            data=json.dumps({"active": False}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        other_user.refresh_from_db()
        self.assertTrue(other_user.is_active)

    def test_organization_admin_cannot_deactivate_or_change_their_own_access(self):
        org_admin = User.objects.create_user(
            username="self-admin", password="safe-test-password", organization=self.organization, role=User.Role.ADMIN
        )
        self.client.force_login(org_admin)

        deactivate_self = self.client.patch(
            reverse("api-org-user-detail", kwargs={"user_id": org_admin.pk}),
            data=json.dumps({"active": False}),
            content_type="application/json",
        )
        self.assertEqual(deactivate_self.status_code, 422)
        self.assertIn("active", deactivate_self.json()["errors"])

        change_own_role = self.client.patch(
            reverse("api-org-user-detail", kwargs={"user_id": org_admin.pk}),
            data=json.dumps({"role": User.Role.SCHEDULER}),
            content_type="application/json",
        )
        self.assertEqual(change_own_role.status_code, 422)
        self.assertIn("role", change_own_role.json()["errors"])

        remove_own_mfa = self.client.patch(
            reverse("api-org-user-detail", kwargs={"user_id": org_admin.pk}),
            data=json.dumps({"mustUseMfa": False}),
            content_type="application/json",
        )
        self.assertEqual(remove_own_mfa.status_code, 422)
        self.assertIn("mustUseMfa", remove_own_mfa.json()["errors"])

        delete_self = self.client.delete(reverse("api-org-user-detail", kwargs={"user_id": org_admin.pk}))
        self.assertEqual(delete_self.status_code, 422)
        org_admin.refresh_from_db()
        self.assertTrue(org_admin.is_active)
        self.assertIsNone(org_admin.archived_at)

    def test_non_admin_role_cannot_use_organization_user_detail_endpoint(self):
        target = User.objects.create_user(
            username="protected-target", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        self.client.force_login(self.therapist)
        response = self.client.patch(
            reverse("api-org-user-detail", kwargs={"user_id": target.pk}),
            data=json.dumps({"active": False}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_super_admin_has_no_standing_clinical_access_even_with_a_grant(self):
        platform_admin = self._platform_admin()
        self.organization.client_number = 6000
        self.organization.save(update_fields=["client_number"])
        self.client.force_login(platform_admin)

        # Bare denial before requesting anything.
        denied = self.client.get(reverse("api-patients"))
        self.assertEqual(denied.status_code, 403)

        response = self.client.post(
            reverse("api-super-admin-privileged-access", kwargs={"client_number": self.organization.client_number}),
            data=json.dumps({"reason": "Investigating a billing support ticket.", "durationHours": 1}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)

        # A grant unlocks only the dedicated privileged-access endpoints, never
        # the normal tenant-scoped patient API.
        still_denied = self.client.get(reverse("api-patients"))
        self.assertEqual(still_denied.status_code, 403)

    def test_privileged_access_request_requires_reason_and_valid_duration(self):
        platform_admin = self._platform_admin()
        self.organization.client_number = 6001
        self.organization.save(update_fields=["client_number"])
        self.client.force_login(platform_admin)

        response = self.client.post(
            reverse("api-super-admin-privileged-access", kwargs={"client_number": self.organization.client_number}),
            data=json.dumps({"reason": "", "durationHours": 999}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("reason", response.json()["errors"])
        self.assertIn("durationHours", response.json()["errors"])
        self.assertFalse(PrivilegedAccessGrant.objects.filter(organization=self.organization).exists())

    def test_privileged_access_request_is_audited_and_unlocks_patient_reads(self):
        platform_admin = self._platform_admin()
        self.organization.client_number = 6002
        self.organization.save(update_fields=["client_number"])
        self.client.force_login(platform_admin)

        # No access before requesting.
        blocked = self.client.get(
            reverse("api-super-admin-privileged-patients", kwargs={"client_number": self.organization.client_number})
        )
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json()["code"], "PRIVILEGED_ACCESS_REQUIRED")

        response = self.client.post(
            reverse("api-super-admin-privileged-access", kwargs={"client_number": self.organization.client_number}),
            data=json.dumps({"reason": "Investigating a billing support ticket.", "durationHours": 4}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        grant_id = response.json()["grant"]["id"]
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=platform_admin, action="privileged_access.requested", object_id=grant_id
            ).exists()
        )

        list_response = self.client.get(
            reverse("api-super-admin-privileged-patients", kwargs={"client_number": self.organization.client_number})
        )
        self.assertEqual(list_response.status_code, 200)
        patient_ids = {row["id"] for row in list_response.json()["patients"]}
        self.assertIn(str(self.patient.pk), patient_ids)
        self.assertTrue(
            AuditEvent.objects.filter(actor=platform_admin, action="privileged_access.patient_list_viewed").exists()
        )

        detail_response = self.client.get(
            reverse(
                "api-super-admin-privileged-patient-detail",
                kwargs={"client_number": self.organization.client_number, "patient_id": self.patient.pk},
            )
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["patient"]["id"], str(self.patient.pk))
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=platform_admin,
                action="privileged_access.patient_viewed",
                patient=self.patient,
            ).exists()
        )

    def test_revoked_privileged_access_blocks_further_reads(self):
        platform_admin = self._platform_admin()
        self.organization.client_number = 6003
        self.organization.save(update_fields=["client_number"])
        self.client.force_login(platform_admin)

        create_response = self.client.post(
            reverse("api-super-admin-privileged-access", kwargs={"client_number": self.organization.client_number}),
            data=json.dumps({"reason": "Support investigation.", "durationHours": 24}),
            content_type="application/json",
        )
        grant_id = create_response.json()["grant"]["id"]

        revoke_response = self.client.patch(
            reverse(
                "api-super-admin-privileged-access-revoke",
                kwargs={"client_number": self.organization.client_number, "grant_id": grant_id},
            )
        )
        self.assertEqual(revoke_response.status_code, 200)
        self.assertTrue(
            AuditEvent.objects.filter(actor=platform_admin, action="privileged_access.revoked", object_id=grant_id).exists()
        )

        blocked_after_revoke = self.client.get(
            reverse("api-super-admin-privileged-patients", kwargs={"client_number": self.organization.client_number})
        )
        self.assertEqual(blocked_after_revoke.status_code, 403)

        second_revoke = self.client.patch(
            reverse(
                "api-super-admin-privileged-access-revoke",
                kwargs={"client_number": self.organization.client_number, "grant_id": grant_id},
            )
        )
        self.assertEqual(second_revoke.status_code, 409)

    def test_expired_privileged_access_blocks_reads(self):
        platform_admin = self._platform_admin()
        self.organization.client_number = 6004
        self.organization.save(update_fields=["client_number"])
        PrivilegedAccessGrant.objects.create(
            organization=self.organization,
            actor=platform_admin,
            reason="Old investigation.",
            expires_at=timezone.now() - timedelta(hours=1),
        )
        self.client.force_login(platform_admin)
        response = self.client.get(
            reverse("api-super-admin-privileged-patients", kwargs={"client_number": self.organization.client_number})
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "PRIVILEGED_ACCESS_REQUIRED")

    def test_privileged_access_grant_does_not_extend_to_another_client(self):
        platform_admin = self._platform_admin()
        self.organization.client_number = 6005
        self.organization.save(update_fields=["client_number"])
        other_org = Organization.objects.create(name="Other Privileged Org", slug="other-privileged-org", client_number=6006)
        other_patient = Patient.objects.create(
            organization=other_org, first_name="Other", last_name="Patient", date_of_birth="1990-01-01"
        )
        self.client.force_login(platform_admin)
        self.client.post(
            reverse("api-super-admin-privileged-access", kwargs={"client_number": self.organization.client_number}),
            data=json.dumps({"reason": "Investigation for this client only.", "durationHours": 1}),
            content_type="application/json",
        )

        cross_client_response = self.client.get(
            reverse(
                "api-super-admin-privileged-patient-detail",
                kwargs={"client_number": other_org.client_number, "patient_id": other_patient.pk},
            )
        )
        self.assertEqual(cross_client_response.status_code, 403)

    def test_non_super_admin_cannot_use_privileged_access_endpoints(self):
        self.organization.client_number = 6007
        self.organization.save(update_fields=["client_number"])
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-super-admin-privileged-access", kwargs={"client_number": self.organization.client_number}),
            data=json.dumps({"reason": "Attempted escalation.", "durationHours": 1}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_scheduling_role_can_create_a_patient_without_clinical_fields(self):
        scheduler = User.objects.create_user(
            username="front-desk", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        self.client.force_login(scheduler)
        response = self.client.post(
            reverse("api-patients"),
            data=json.dumps(
                {
                    "firstName": "Jordan",
                    "lastName": "New",
                    "dateOfBirth": "1988-04-02",
                    "phone": "555-0100",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        created = Patient.objects.get(first_name="Jordan", last_name="New")
        self.assertEqual(created.organization, self.organization)
        self.assertEqual(created.diagnoses, "")

    def test_non_clinical_role_cannot_set_diagnoses_on_create(self):
        scheduler = User.objects.create_user(
            username="front-desk-2", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        self.client.force_login(scheduler)
        response = self.client.post(
            reverse("api-patients"),
            data=json.dumps(
                {"firstName": "Blocked", "lastName": "Attempt", "dateOfBirth": "1988-04-02", "diagnoses": "Should not save"}
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Patient.objects.filter(first_name="Blocked").exists())

    def test_biller_cannot_create_a_patient(self):
        biller = User.objects.create_user(
            username="biller-1", password="safe-test-password", organization=self.organization, role=User.Role.BILLER
        )
        self.client.force_login(biller)
        response = self.client.post(
            reverse("api-patients"),
            data=json.dumps({"firstName": "No", "lastName": "Access", "dateOfBirth": "1988-04-02"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_create_patient_requires_name_and_dob(self):
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-patients"),
            data=json.dumps({"firstName": "", "lastName": "", "dateOfBirth": ""}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)
        for field in ("firstName", "lastName", "dateOfBirth"):
            self.assertIn(field, response.json()["errors"])

    def test_scheduler_can_update_demographics_but_not_diagnoses(self):
        scheduler = User.objects.create_user(
            username="front-desk-3", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        self.client.force_login(scheduler)

        ok_response = self.client.patch(
            reverse("api-patient-detail", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"phone": "555-9999"}),
            content_type="application/json",
        )
        self.assertEqual(ok_response.status_code, 200)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.phone, "555-9999")

        blocked_response = self.client.patch(
            reverse("api-patient-detail", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"diagnoses": "Attempted clinical edit"}),
            content_type="application/json",
        )
        self.assertEqual(blocked_response.status_code, 403)
        self.patient.refresh_from_db()
        self.assertNotEqual(self.patient.diagnoses, "Attempted clinical edit")

    def test_therapist_can_update_diagnoses_and_change_is_audited(self):
        self.client.force_login(self.therapist)
        response = self.client.patch(
            reverse("api-patient-detail", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"diagnoses": "Updated diagnosis text"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.diagnoses, "Updated diagnosis text")
        event = AuditEvent.objects.get(actor=self.therapist, action="patient.updated", object_id=self.patient.pk)
        self.assertIn("diagnoses", event.metadata["changed_fields"])
        # No clinical narrative leaks into the audit trail metadata.
        self.assertNotIn("Updated diagnosis text", json.dumps(event.metadata))

    def test_delete_deactivates_rather_than_hard_deletes(self):
        self.client.force_login(self.therapist)
        response = self.client.delete(
            reverse("api-patient-detail", kwargs={"patient_id": self.patient.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.status, Patient.Status.INACTIVE)
        self.assertTrue(Patient.objects.filter(pk=self.patient.pk).exists())

        second_response = self.client.delete(
            reverse("api-patient-detail", kwargs={"patient_id": self.patient.pk})
        )
        self.assertEqual(second_response.status_code, 409)

    def test_assigned_therapist_must_belong_to_the_same_organization(self):
        other_org = Organization.objects.create(name="Cross Org Patients", slug="cross-org-patients")
        outside_therapist = User.objects.create_user(
            username="outside-therapist", password="safe-test-password", organization=other_org, role=User.Role.THERAPIST
        )
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-patients"),
            data=json.dumps(
                {
                    "firstName": "Cross",
                    "lastName": "OrgTest",
                    "dateOfBirth": "1988-04-02",
                    "assignedTherapistId": str(outside_therapist.pk),
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("assignedTherapistId", response.json()["errors"])

    def test_staff_options_returns_only_org_scoped_clinical_staff(self):
        other_org = Organization.objects.create(name="Other Staff Org", slug="other-staff-org")
        User.objects.create_user(
            username="other-org-therapist", password="safe-test-password", organization=other_org, role=User.Role.THERAPIST
        )
        self.client.force_login(self.therapist)
        response = self.client.get(reverse("api-staff-options"))
        self.assertEqual(response.status_code, 200)
        names = {row["displayName"] for row in response.json()["staff"]}
        self.assertNotIn("other-org-therapist", names)

    def _org_admin(self):
        return User.objects.create_user(
            username="clinic-admin-1", password="safe-test-password", organization=self.organization, role=User.Role.ADMIN
        )

    def test_admin_can_create_update_and_deactivate_a_location(self):
        admin = self._org_admin()
        self.client.force_login(admin)

        create_response = self.client.post(
            reverse("api-locations"),
            data=json.dumps({"name": "Downtown Clinic", "city": "Raleigh", "state": "NC", "timezone": "America/New_York"}),
            content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 201)
        location_id = create_response.json()["location"]["id"]
        self.assertTrue(Location.objects.filter(pk=location_id, organization=self.organization).exists())

        update_response = self.client.patch(
            reverse("api-location-detail", kwargs={"location_id": location_id}),
            data=json.dumps({"phone": "555-2000"}),
            content_type="application/json",
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["location"]["phone"], "555-2000")

        deactivate_response = self.client.delete(
            reverse("api-location-detail", kwargs={"location_id": location_id})
        )
        self.assertEqual(deactivate_response.status_code, 200)
        self.assertFalse(deactivate_response.json()["location"]["isActive"])
        self.assertTrue(Location.objects.filter(pk=location_id).exists())

        second_deactivate = self.client.delete(
            reverse("api-location-detail", kwargs={"location_id": location_id})
        )
        self.assertEqual(second_deactivate.status_code, 409)

    def test_non_admin_cannot_manage_locations(self):
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-locations"),
            data=json.dumps({"name": "Blocked Location"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_locations_are_scoped_to_the_callers_organization(self):
        other_org = Organization.objects.create(name="Other Location Org", slug="other-location-org")
        other_location = Location.objects.create(organization=other_org, name="Other Org Location")
        admin = self._org_admin()
        self.client.force_login(admin)
        response = self.client.get(reverse("api-location-detail", kwargs={"location_id": other_location.pk}))
        self.assertEqual(response.status_code, 404)

    def test_admin_can_manage_appointment_types(self):
        admin = self._org_admin()
        self.client.force_login(admin)

        create_response = self.client.post(
            reverse("api-appointment-types"),
            data=json.dumps({"name": "New Patient Eval", "defaultDurationMinutes": 60}),
            content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 201)
        type_id = create_response.json()["appointmentType"]["id"]
        self.assertTrue(AppointmentType.objects.filter(pk=type_id, organization=self.organization).exists())

        duplicate_response = self.client.post(
            reverse("api-appointment-types"),
            data=json.dumps({"name": "New Patient Eval"}),
            content_type="application/json",
        )
        self.assertEqual(duplicate_response.status_code, 422)

        invalid_duration = self.client.post(
            reverse("api-appointment-types"),
            data=json.dumps({"name": "Bad Duration", "defaultDurationMinutes": 0}),
            content_type="application/json",
        )
        self.assertEqual(invalid_duration.status_code, 422)

        deactivate_response = self.client.delete(
            reverse("api-appointment-type-detail", kwargs={"appointment_type_id": type_id})
        )
        self.assertEqual(deactivate_response.status_code, 200)
        self.assertFalse(deactivate_response.json()["appointmentType"]["isActive"])

    def test_operational_report_requires_admin_and_returns_real_counts(self):
        self.client.force_login(self.therapist)
        denied = self.client.get(reverse("api-operational-report"))
        self.assertEqual(denied.status_code, 403)

        admin = self._org_admin()
        Patient.objects.create(
            organization=self.organization, first_name="Recent", last_name="Patient", date_of_birth="1990-01-01"
        )
        ClinicalNote.objects.create(
            patient=self.patient,
            therapist=self.therapist,
            note_type=ClinicalNote.Type.DAILY,
            status=ClinicalNote.Status.SIGNED,
            objective="x",
            assessment="x",
            plan="x",
            signature_name="Therapist",
            signed_at=timezone.now(),
            finalization_attestation=True,
        )
        self.client.force_login(admin)
        response = self.client.get(reverse("api-operational-report"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["windowDays"], 30)
        self.assertGreaterEqual(payload["newPatients"], 1)
        self.assertGreaterEqual(payload["notes"]["signed"], 1)
        self.assertIsInstance(payload["caseloadByProvider"], list)
        self.assertTrue(any(row["id"] == str(self.therapist.pk) for row in payload["caseloadByProvider"]))

    def test_therapist_can_upload_list_and_download_a_document(self):
        self.client.force_login(self.therapist)
        upload = SimpleUploadedFile("outside_imaging.pdf", b"%PDF-1.4 fake pdf content", content_type="application/pdf")
        response = self.client.post(
            reverse("api-patient-documents", kwargs={"patient_id": self.patient.pk}),
            data={"file": upload, "title": "Outside imaging report", "description": "MRI from referring provider."},
        )
        self.assertEqual(response.status_code, 201)
        document_id = response.json()["document"]["id"]
        document = PatientDocument.objects.get(pk=document_id)
        self.assertEqual(document.patient, self.patient)
        self.assertEqual(document.uploaded_by, self.therapist)

        # The stored file must live outside MEDIA_ROOT, in the private root.
        from django.conf import settings as django_settings

        self.assertEqual(str(document.file.storage.location), str(django_settings.PRIVATE_MEDIA_ROOT))
        self.assertNotEqual(str(document.file.storage.location), str(django_settings.MEDIA_ROOT))

        list_response = self.client.get(
            reverse("api-patient-documents", kwargs={"patient_id": self.patient.pk})
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()["documents"]), 1)
        self.assertEqual(list_response.json()["documents"][0]["title"], "Outside imaging report")

        download_response = self.client.get(
            reverse(
                "api-patient-document-download",
                kwargs={"patient_id": self.patient.pk, "document_id": document_id},
            )
        )
        self.assertEqual(download_response.status_code, 200)
        content = b"".join(download_response.streaming_content)
        self.assertIn(b"fake pdf content", content)
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.therapist, action="patient_document.downloaded", object_id=document_id
            ).exists()
        )

    def test_document_upload_rejects_disallowed_file_type(self):
        self.client.force_login(self.therapist)
        upload = SimpleUploadedFile("script.exe", b"MZ fake executable", content_type="application/octet-stream")
        response = self.client.post(
            reverse("api-patient-documents", kwargs={"patient_id": self.patient.pk}),
            data={"file": upload, "title": "Suspicious file"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertFalse(PatientDocument.objects.filter(title="Suspicious file").exists())

    def test_document_upload_rejects_oversized_file(self):
        self.client.force_login(self.therapist)
        oversized = SimpleUploadedFile("huge.pdf", b"0" * (16 * 1024 * 1024), content_type="application/pdf")
        response = self.client.post(
            reverse("api-patient-documents", kwargs={"patient_id": self.patient.pk}),
            data={"file": oversized, "title": "Too big"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("file", response.json()["errors"])

    def test_therapist_cannot_upload_document_for_an_unassigned_patient(self):
        other_therapist = User.objects.create_user(
            username="other-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST
        )
        unassigned_patient = Patient.objects.create(
            organization=self.organization,
            first_name="Unassigned",
            last_name="Patient",
            date_of_birth="1990-01-01",
            assigned_therapist=other_therapist,
        )
        self.client.force_login(self.therapist)
        upload = SimpleUploadedFile("file.pdf", b"%PDF-1.4 x", content_type="application/pdf")
        response = self.client.post(
            reverse("api-patient-documents", kwargs={"patient_id": unassigned_patient.pk}),
            data={"file": upload, "title": "Blocked"},
        )
        self.assertEqual(response.status_code, 403)

    def test_scheduler_cannot_upload_documents(self):
        scheduler = User.objects.create_user(
            username="doc-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        self.client.force_login(scheduler)
        upload = SimpleUploadedFile("file.pdf", b"%PDF-1.4 x", content_type="application/pdf")
        response = self.client.post(
            reverse("api-patient-documents", kwargs={"patient_id": self.patient.pk}),
            data={"file": upload, "title": "Blocked"},
        )
        self.assertEqual(response.status_code, 403)

    def test_uploaded_document_is_not_reachable_through_the_public_media_url(self):
        self.client.force_login(self.therapist)
        upload = SimpleUploadedFile("private.pdf", b"%PDF-1.4 secret", content_type="application/pdf")
        response = self.client.post(
            reverse("api-patient-documents", kwargs={"patient_id": self.patient.pk}),
            data={"file": upload, "title": "Private"},
        )
        document = PatientDocument.objects.get(pk=response.json()["document"]["id"])
        # The relative storage path (e.g. patient_documents/<id>/<uuid>.pdf) must
        # not be resolvable under the public /media/ route.
        public_url_response = self.client.get("/media/" + document.file.name)
        self.assertEqual(public_url_response.status_code, 404)

    def test_scheduler_can_collect_payments_but_not_create_superbills(self):
        scheduler = User.objects.create_user(
            username="front-desk-payments", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        self.client.force_login(scheduler)

        payment_response = self.client.post(
            reverse("api-payment-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps(
                {
                    "amount": "45.00",
                    "receivedOn": "2026-05-01",
                    "status": "received",
                    "paymentProcessorReference": "ref-12345",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(payment_response.status_code, 201)
        self.assertTrue(PaymentRecord.objects.filter(patient=self.patient, recorded_by=scheduler).exists())

        superbill_response = self.client.post(
            reverse("api-superbill-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"serviceDate": "2026-05-01", "codes": ["97110"], "amount": "80.00", "status": "draft"}),
            content_type="application/json",
        )
        self.assertEqual(superbill_response.status_code, 403)

    def test_patient_workspace_gives_scheduler_payments_but_not_superbills(self):
        scheduler = User.objects.create_user(
            username="front-desk-workspace", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        PaymentRecord.objects.create(
            patient=self.patient, recorded_by=scheduler, amount="45.00", received_on="2026-05-01", payment_processor_reference="ref-1"
        )
        self.client.force_login(scheduler)
        response = self.client.get(reverse("api-patient-workspace", kwargs={"patient_id": self.patient.pk}))
        self.assertEqual(response.status_code, 200)
        operations = response.json()["operations"]
        self.assertTrue(operations["canCollectPayments"])
        self.assertFalse(operations["canManageBilling"])
        self.assertIn("payments", operations)
        self.assertNotIn("superbills", operations)

    def test_scheduler_can_create_and_update_a_referral(self):
        scheduler = User.objects.create_user(
            username="front-desk-referrals", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        self.client.force_login(scheduler)
        create_response = self.client.post(
            reverse("api-referral-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps(
                {
                    "direction": Referral.Direction.OUTGOING,
                    "providerName": "Dr. Outside Specialist",
                    "providerContact": "555-0199",
                    "reason": "Suspected rotator cuff tear.",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 201)
        referral_id = create_response.json()["referral"]["id"]
        self.assertTrue(Referral.objects.filter(pk=referral_id, patient=self.patient, created_by=scheduler).exists())

        update_response = self.client.post(
            reverse("api-referral-status-update", kwargs={"referral_id": referral_id}),
            data=json.dumps({"status": Referral.Status.SCHEDULED}),
            content_type="application/json",
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["referral"]["status"], Referral.Status.SCHEDULED)

    def test_biller_cannot_manage_referrals(self):
        biller = User.objects.create_user(
            username="biller-referrals", password="safe-test-password", organization=self.organization, role=User.Role.BILLER
        )
        self.client.force_login(biller)
        response = self.client.post(
            reverse("api-referral-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"providerName": "Blocked Provider"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_seed_demo_clients_creates_isolated_tenants(self):
        self._platform_admin()
        call_command("seed_demo_clients", staff_password="Az9!DemoStaffPassword2026")

        source_motion = Organization.objects.get(name="Source Motion PT")
        total_motion = Organization.objects.get(name="Total Motion PT")
        self.assertEqual(source_motion.client_number, 1000)
        self.assertEqual(total_motion.client_number, 1001)

        triangle = Organization.objects.get(name="Triangle Rehab Center")
        self.assertEqual(triangle.status, Organization.Status.SUSPENDED)

        source_therapist = User.objects.get(
            organization=source_motion, role=User.Role.THERAPIST
        )
        total_patients = Patient.objects.filter(organization=total_motion)
        self.assertEqual(total_patients.count(), 4)

        self.client.force_login(source_therapist)
        response = self.client.get(
            reverse("api-patient-detail", kwargs={"patient_id": total_patients.first().pk})
        )
        self.assertEqual(response.status_code, 404)

        source_provider = Provider.objects.get(organization=source_motion)
        self.assertTrue(source_provider.online_booking_enabled)
        self.assertEqual(ProviderAvailability.objects.filter(provider=source_provider).count(), 10)
        self.assertTrue(
            BookingConfiguration.objects.get(organization=source_motion).online_booking_enabled
        )
        self.assertEqual(Appointment.objects.filter(patient__organization=source_motion).count(), 8)
        self.assertTrue(
            ClinicalNote.objects.filter(
                patient__organization=source_motion, status=ClinicalNote.Status.SIGNED
            ).exists()
        )
        self.assertTrue(
            ClinicalNote.objects.filter(
                patient__organization=source_motion, status=ClinicalNote.Status.DRAFT
            ).exists()
        )


class PublicBookingTests(TestCase):
    """Public, unauthenticated booking API — care/availability.py + care/booking.py."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Riverside PT", slug="riverside-pt", timezone="America/Los_Angeles"
        )
        self.config = BookingConfiguration.objects.create(
            organization=self.organization,
            online_booking_enabled=True,
            min_notice_hours=4,
            max_advance_days=90,
            slot_interval_minutes=15,
        )
        self.location = Location.objects.create(
            organization=self.organization,
            name="Riverside PT - Main",
            city="Riverside",
            state="CA",
            zip_code="92501",
            timezone="America/Los_Angeles",
        )
        self.therapist_user = User.objects.create_user(
            username="riverside-therapist",
            password="safe-test-password",
            organization=self.organization,
            role=User.Role.THERAPIST,
        )
        self.provider = Provider.objects.create(
            organization=self.organization,
            user=self.therapist_user,
            first_name="Jamie",
            last_name="Rivera",
            specialty="Orthopedic PT",
            license_number="PT-77001",
            online_booking_enabled=True,
        )
        self.provider.locations.add(self.location)
        self.appointment_type = AppointmentType.objects.create(
            organization=self.organization,
            name="Initial Evaluation",
            default_duration_minutes=45,
            online_booking_enabled=True,
        )
        ProviderAppointmentType.objects.create(
            provider=self.provider, appointment_type=self.appointment_type, active=True
        )

        # 14 days out and a weekday, comfortably clear of min_notice_hours/max_advance_days.
        self.target_date = timezone.localdate() + timedelta(days=14)
        while self.target_date.weekday() > 4:
            self.target_date += timedelta(days=1)
        ProviderAvailability.objects.create(
            provider=self.provider,
            location=self.location,
            day_of_week=self.target_date.weekday(),
            start_time="09:00",
            end_time="12:00",
            active=True,
        )

    def _availability(self, **params):
        query = {
            "location_id": str(self.location.pk),
            "appointment_type_id": str(self.appointment_type.pk),
            "date": self.target_date.isoformat(),
        }
        query.update(params)
        url = reverse("api-public-availability", kwargs={"slug": self.organization.slug}) + "?" + "&".join(
            f"{key}={value}" for key, value in query.items()
        )
        return self.client.get(url)

    def _slots_for_provider(self, response):
        for entry in response.json()["providers"]:
            if entry["provider"]["id"] == str(self.provider.pk):
                return entry["slots"]
        return []

    def _book(self, start_iso, **overrides):
        payload = {
            "organizationSlug": self.organization.slug,
            "locationId": str(self.location.pk),
            "appointmentTypeId": str(self.appointment_type.pk),
            "providerId": str(self.provider.pk),
            "startDatetime": start_iso,
            "isNewPatient": True,
            "patient": {
                "firstName": "Casey",
                "lastName": "Booker",
                "dateOfBirth": "1990-01-15",
                "email": "casey.booker@example.com",
                "phone": "555-0101",
            },
            "reasonForVisit": "Right knee pain",
        }
        payload.update(overrides)
        return self.client.post(
            reverse("api-public-bookings"), data=json.dumps(payload), content_type="application/json"
        )

    def test_slots_returned_within_working_hours_with_no_conflicts(self):
        response = self._availability()
        self.assertEqual(response.status_code, 200)
        slots = self._slots_for_provider(response)
        self.assertTrue(slots)
        first_start = datetime.fromisoformat(slots[0]["start"])
        local_start = timezone.localtime(first_start, ZoneInfo("America/Los_Angeles"))
        self.assertEqual((local_start.hour, local_start.minute), (9, 0))

    def test_existing_appointment_blocks_overlapping_slots(self):
        patient = Patient.objects.create(
            organization=self.organization, first_name="Existing", last_name="Patient", date_of_birth="1985-02-01"
        )
        tz = ZoneInfo("America/Los_Angeles")
        starts_at = timezone.make_aware(datetime.combine(self.target_date, time(9, 0)), tz)
        Appointment.objects.create(
            patient=patient,
            therapist=self.therapist_user,
            provider=self.provider,
            location_detail=self.location,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=45),
            created_by=self.therapist_user,
        )
        slots = self._slots_for_provider(self._availability())
        starts = {datetime.fromisoformat(slot["start"]) for slot in slots}
        self.assertNotIn(starts_at, starts)
        self.assertIn(starts_at + timedelta(minutes=45), starts)

    def test_provider_time_off_blocks_slots(self):
        tz = ZoneInfo("America/Los_Angeles")
        off_start = timezone.make_aware(datetime.combine(self.target_date, time(10, 0)), tz)
        ProviderTimeOff.objects.create(
            provider=self.provider, start_datetime=off_start, end_datetime=off_start + timedelta(hours=1)
        )
        slots = self._slots_for_provider(self._availability())
        starts = {datetime.fromisoformat(slot["start"]) for slot in slots}
        self.assertNotIn(off_start, starts)
        self.assertIn(off_start - timedelta(minutes=45), starts)
        self.assertIn(off_start + timedelta(hours=1), starts)

    def test_location_closure_blocks_all_slots(self):
        tz = ZoneInfo("America/Los_Angeles")
        day_start = timezone.make_aware(datetime.combine(self.target_date, time.min), tz)
        LocationClosure.objects.create(
            location=self.location, start_datetime=day_start, end_datetime=day_start + timedelta(days=1), reason="Holiday"
        )
        slots = self._slots_for_provider(self._availability())
        self.assertEqual(slots, [])

    def test_cross_organization_provider_is_rejected(self):
        other_org = Organization.objects.create(name="Other Org", slug="other-org-booking")
        other_provider = Provider.objects.create(
            organization=other_org, first_name="Out", last_name="Sider", online_booking_enabled=True
        )
        response = self._availability(provider_id=str(other_provider.pk))
        self.assertEqual(response.status_code, 404)

    def test_cross_organization_appointment_type_is_rejected(self):
        other_org = Organization.objects.create(name="Other Org", slug="other-org-appt-type")
        other_type = AppointmentType.objects.create(
            organization=other_org, name="Other Type", online_booking_enabled=True
        )
        response = self._availability(appointment_type_id=str(other_type.pk))
        self.assertEqual(response.status_code, 404)

    def test_double_booking_the_same_slot_returns_conflict(self):
        slots = self._slots_for_provider(self._availability())
        start_iso = slots[0]["start"]

        first = self._book(start_iso)
        self.assertEqual(first.status_code, 201)
        confirmation = first.json()["confirmationNumber"]
        self.assertTrue(confirmation.startswith("APT-"))

        second = self._book(start_iso, patient={
            "firstName": "Riley", "lastName": "Second", "dateOfBirth": "1992-03-03",
        })
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["code"], "SLOT_NO_LONGER_AVAILABLE")

    def test_cancelled_appointment_releases_its_slot(self):
        slots = self._slots_for_provider(self._availability())
        start_iso = slots[0]["start"]
        response = self._book(start_iso)
        self.assertEqual(response.status_code, 201)
        appointment_id = response.json()["appointment"]["id"]

        appointment = Appointment.objects.get(pk=appointment_id)
        appointment.status = Appointment.Status.CANCELLED
        appointment.save()

        slots_after = self._slots_for_provider(self._availability())
        self.assertIn(start_iso, [slot["start"] for slot in slots_after])

    def test_suspended_organization_disables_public_booking(self):
        self.organization.status = Organization.Status.SUSPENDED
        self.organization.save()
        response = self.client.get(reverse("api-public-organization", kwargs={"slug": self.organization.slug}))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self._availability().status_code, 404)

    def test_inactive_provider_yields_no_availability(self):
        self.provider.is_active = False
        self.provider.save()
        slots = self._slots_for_provider(self._availability())
        self.assertEqual(slots, [])

    def test_appointment_type_disabled_for_online_booking_is_not_listed(self):
        AppointmentType.objects.create(
            organization=self.organization, name="Internal Only", online_booking_enabled=False
        )
        response = self.client.get(
            reverse("api-public-appointment-types", kwargs={"slug": self.organization.slug})
        )
        names = [entry["name"] for entry in response.json()["appointmentTypes"]]
        self.assertIn("Initial Evaluation", names)
        self.assertNotIn("Internal Only", names)

    def test_provider_not_linked_to_service_is_not_returned_as_eligible(self):
        unlinked_provider = Provider.objects.create(
            organization=self.organization, first_name="Not", last_name="Linked", online_booking_enabled=True
        )
        unlinked_provider.locations.add(self.location)
        url = (
            reverse("api-public-providers", kwargs={"slug": self.organization.slug})
            + f"?location_id={self.location.pk}&appointment_type_id={self.appointment_type.pk}"
        )
        response = self.client.get(url)
        ids = [entry["id"] for entry in response.json()["providers"]]
        self.assertIn(str(self.provider.pk), ids)
        self.assertNotIn(str(unlinked_provider.pk), ids)

    def test_timezone_conversion_uses_the_locations_own_timezone(self):
        self.location.timezone = "America/New_York"
        self.location.save()
        ProviderAvailability.objects.filter(provider=self.provider, location=self.location).update(
            start_time="09:00", end_time="12:00"
        )
        slots = self._slots_for_provider(self._availability())
        first_start = datetime.fromisoformat(slots[0]["start"])
        local_start = timezone.localtime(first_start, ZoneInfo("America/New_York"))
        self.assertEqual((local_start.hour, local_start.minute), (9, 0))

    def test_buffer_time_is_respected_around_existing_appointments(self):
        tz = ZoneInfo("America/Los_Angeles")
        starts_at = timezone.make_aware(datetime.combine(self.target_date, time(9, 0)), tz)
        patient = Patient.objects.create(
            organization=self.organization, first_name="Buffer", last_name="Patient", date_of_birth="1980-01-01"
        )
        Appointment.objects.create(
            patient=patient,
            therapist=self.therapist_user,
            provider=self.provider,
            location_detail=self.location,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=45),
            created_by=self.therapist_user,
        )

        slots_without_buffer = self._slots_for_provider(self._availability())
        starts_without_buffer = {datetime.fromisoformat(slot["start"]) for slot in slots_without_buffer}
        self.assertIn(starts_at + timedelta(minutes=45), starts_without_buffer)

        self.appointment_type.buffer_before_minutes = 15
        self.appointment_type.save()
        slots_with_buffer = self._slots_for_provider(self._availability())
        starts_with_buffer = {datetime.fromisoformat(slot["start"]) for slot in slots_with_buffer}
        self.assertNotIn(starts_at + timedelta(minutes=45), starts_with_buffer)
        self.assertIn(starts_at + timedelta(minutes=60), starts_with_buffer)

    def test_min_notice_hours_enforced(self):
        self.config.min_notice_hours = 24 * 20
        self.config.save()
        slots = self._slots_for_provider(self._availability())
        self.assertEqual(slots, [])

    def test_max_advance_days_enforced(self):
        self.config.max_advance_days = 5
        self.config.save()
        slots = self._slots_for_provider(self._availability())
        self.assertEqual(slots, [])


class ChangePasswordTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Change Password Clinic", slug="change-password-clinic")
        self.user = User.objects.create_user(
            username="pw-change-user", password="OriginalPass1234",
            organization=self.organization, role=User.Role.THERAPIST,
        )
        self.super_admin = User.objects.create_user(
            username="pw-change-super", password="OriginalSuperPass1234",
            role=User.Role.SUPER_ADMIN, is_superuser=True, is_staff=True, organization=None,
        )

    def test_user_can_change_their_own_password(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("api-change-password"),
            data=json.dumps({"currentPassword": "OriginalPass1234", "newPassword": "BrandNewPass5678"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("BrandNewPass5678"))
        self.assertTrue(
            AuditEvent.objects.filter(organization=self.organization, action="user.password_changed").exists()
        )

    def test_change_password_rejects_wrong_current_password(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("api-change-password"),
            data=json.dumps({"currentPassword": "wrong-password", "newPassword": "BrandNewPass5678"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OriginalPass1234"))

    def test_change_password_rejects_short_new_password(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("api-change-password"),
            data=json.dumps({"currentPassword": "OriginalPass1234", "newPassword": "short"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OriginalPass1234"))

    def test_super_admin_can_change_password_without_an_organization(self):
        self.client.force_login(self.super_admin)
        response = self.client.post(
            reverse("api-change-password"),
            data=json.dumps({"currentPassword": "OriginalSuperPass1234", "newPassword": "BrandNewSuperPass5678"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.super_admin.refresh_from_db()
        self.assertTrue(self.super_admin.check_password("BrandNewSuperPass5678"))

    def test_change_password_requires_authentication(self):
        response = self.client.post(
            reverse("api-change-password"),
            data=json.dumps({"currentPassword": "x", "newPassword": "BrandNewPass5678"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)


class UserAccountStatusTests(TestCase):
    """ACTIVE / INACTIVE / LOCKED_OUT / SUSPENDED / DELETED account status:
    login gating, admin actions, self-protection, tenant isolation, and audit.
    """

    def setUp(self):
        self.organization = Organization.objects.create(name="Status Clinic", slug="status-clinic")
        self.admin = User.objects.create_user(
            username="status-admin", password="safe-test-password", organization=self.organization, role=User.Role.ADMIN
        )
        self.second_admin = User.objects.create_user(
            username="status-admin-2", password="safe-test-password", organization=self.organization, role=User.Role.ADMIN
        )
        self.staff = User.objects.create_user(
            username="status-staff", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )

    def _platform_admin(self):
        platform_admin = User(username="platform-admin", role=User.Role.SUPER_ADMIN, is_superuser=True)
        platform_admin.set_password("safe-test-password")
        platform_admin.full_clean()
        platform_admin.save()
        return platform_admin

    def _login(self, username, password):
        return self.client.post(
            reverse("api-login"),
            data=json.dumps({"username": username, "password": password}),
            content_type="application/json",
        )

    # -- login gating per status -------------------------------------------------

    def test_active_user_can_sign_in(self):
        response = self._login("status-staff", "safe-test-password")
        self.assertEqual(response.status_code, 200)

    def test_inactive_user_cannot_sign_in(self):
        self.staff.status = User.Status.INACTIVE
        self.staff.is_active = False
        self.staff.save(update_fields=["status", "is_active"])
        response = self._login("status-staff", "safe-test-password")
        self.assertEqual(response.status_code, 401)

    def test_locked_out_user_cannot_sign_in(self):
        self.staff.status = User.Status.LOCKED_OUT
        self.staff.is_active = False
        self.staff.locked_at = timezone.now()
        self.staff.locked_until = timezone.now() + timedelta(minutes=15)
        self.staff.save(update_fields=["status", "is_active", "locked_at", "locked_until"])
        response = self._login("status-staff", "safe-test-password")
        self.assertEqual(response.status_code, 401)

    def test_suspended_user_cannot_sign_in(self):
        self.staff.status = User.Status.SUSPENDED
        self.staff.is_active = False
        self.staff.suspended_at = timezone.now()
        self.staff.save(update_fields=["status", "is_active", "suspended_at"])
        response = self._login("status-staff", "safe-test-password")
        self.assertEqual(response.status_code, 401)

    def test_deleted_user_cannot_sign_in(self):
        self.staff.status = User.Status.DELETED
        self.staff.is_active = False
        self.staff.archived_at = timezone.now()
        self.staff.save(update_fields=["status", "is_active", "archived_at"])
        response = self._login("status-staff", "safe-test-password")
        self.assertEqual(response.status_code, 401)

    def test_lockout_expiration_allows_login_again(self):
        self.staff.status = User.Status.LOCKED_OUT
        self.staff.is_active = False
        self.staff.locked_at = timezone.now() - timedelta(minutes=20)
        self.staff.locked_until = timezone.now() - timedelta(minutes=5)
        self.staff.failed_login_attempts = 5
        self.staff.save(update_fields=["status", "is_active", "locked_at", "locked_until", "failed_login_attempts"])
        response = self._login("status-staff", "safe-test-password")
        self.assertEqual(response.status_code, 200)
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.status, User.Status.ACTIVE)
        self.assertEqual(self.staff.failed_login_attempts, 0)

    def test_five_failed_attempts_locks_the_account(self):
        for _ in range(5):
            response = self._login("status-staff", "wrong-password")
            self.assertEqual(response.status_code, 401)
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.status, User.Status.LOCKED_OUT)
        self.assertEqual(self.staff.failed_login_attempts, 5)
        self.assertIsNotNone(self.staff.locked_until)
        self.assertTrue(AuditEvent.objects.filter(organization=self.organization, action="USER_LOCKED").exists())

    def test_successful_login_resets_failed_attempts(self):
        for _ in range(3):
            self._login("status-staff", "wrong-password")
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.failed_login_attempts, 3)
        response = self._login("status-staff", "safe-test-password")
        self.assertEqual(response.status_code, 200)
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.failed_login_attempts, 0)

    # -- admin actions -------------------------------------------------------

    def test_admin_can_deactivate_and_activate_a_user(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("api-org-user-status-action", kwargs={"user_id": self.staff.pk}),
            data=json.dumps({"action": "deactivate"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.status, User.Status.INACTIVE)
        self.assertFalse(self.staff.is_active)
        self.assertTrue(AuditEvent.objects.filter(action="USER_DEACTIVATED", object_id=self.staff.pk).exists())

        response = self.client.post(
            reverse("api-org-user-status-action", kwargs={"user_id": self.staff.pk}),
            data=json.dumps({"action": "activate"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.status, User.Status.ACTIVE)
        self.assertTrue(self.staff.is_active)

    def test_admin_can_suspend_and_reactivate_a_user(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("api-org-user-status-action", kwargs={"user_id": self.staff.pk}),
            data=json.dumps({"action": "suspend", "reason": "Policy violation"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.status, User.Status.SUSPENDED)
        self.assertEqual(self.staff.suspension_reason, "Policy violation")
        self.assertEqual(self.staff.suspended_by, self.admin)

        response = self.client.post(
            reverse("api-org-user-status-action", kwargs={"user_id": self.staff.pk}),
            data=json.dumps({"action": "reactivate"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.status, User.Status.ACTIVE)
        self.assertEqual(self.staff.suspension_reason, "")

    def test_admin_can_unlock_a_locked_account(self):
        self.staff.status = User.Status.LOCKED_OUT
        self.staff.is_active = False
        self.staff.failed_login_attempts = 5
        self.staff.locked_at = timezone.now()
        self.staff.locked_until = timezone.now() + timedelta(minutes=15)
        self.staff.save(update_fields=["status", "is_active", "failed_login_attempts", "locked_at", "locked_until"])
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("api-org-user-status-action", kwargs={"user_id": self.staff.pk}),
            data=json.dumps({"action": "unlock"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.status, User.Status.ACTIVE)
        self.assertTrue(self.staff.is_active)
        self.assertEqual(self.staff.failed_login_attempts, 0)
        self.assertIsNone(self.staff.locked_until)
        self.assertTrue(AuditEvent.objects.filter(action="USER_UNLOCKED", object_id=self.staff.pk).exists())

    def test_unauthorized_staff_cannot_unlock_users(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("api-org-user-status-action", kwargs={"user_id": self.staff.pk}),
            data=json.dumps({"action": "unlock"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_platform_super_admin_can_delete_and_restore_a_user(self):
        platform_admin = self._platform_admin()
        self.client.force_login(platform_admin)
        response = self.client.post(
            reverse("api-super-admin-user-status-action", kwargs={"user_id": self.staff.pk}),
            data=json.dumps({"action": "delete"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.status, User.Status.DELETED)
        self.assertIsNotNone(self.staff.archived_at)
        self.assertTrue(User.objects.filter(pk=self.staff.pk).exists())

        response = self.client.post(
            reverse("api-super-admin-user-status-action", kwargs={"user_id": self.staff.pk}),
            data=json.dumps({"action": "restore"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.status, User.Status.ACTIVE)
        self.assertIsNone(self.staff.archived_at)
        self.assertTrue(self.staff.is_active)

    # -- self-protection -------------------------------------------------------

    def test_admin_cannot_change_their_own_account_status(self):
        self.client.force_login(self.admin)
        for action in ("deactivate", "suspend"):
            response = self.client.post(
                reverse("api-org-user-status-action", kwargs={"user_id": self.admin.pk}),
                data=json.dumps({"action": action}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 422)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.status, User.Status.ACTIVE)

    # -- tenant isolation -------------------------------------------------------

    def test_tenant_isolation_prevents_cross_org_status_changes(self):
        other_org = Organization.objects.create(name="Other Clinic", slug="other-status-clinic")
        other_admin = User.objects.create_user(
            username="other-admin", password="safe-test-password", organization=other_org, role=User.Role.ADMIN
        )
        self.client.force_login(other_admin)
        response = self.client.post(
            reverse("api-org-user-status-action", kwargs={"user_id": self.staff.pk}),
            data=json.dumps({"action": "deactivate"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.status, User.Status.ACTIVE)

    # -- mid-session revocation -------------------------------------------------

    def test_deactivating_a_user_immediately_blocks_their_existing_session(self):
        """Django's ModelBackend re-checks `is_active` on every request (not
        just at login), so an existing session stops working on its very next
        request once an admin deactivates the account — no extra code needed
        for this; it's already how the framework's default backend behaves.
        """
        self.client.force_login(self.staff)
        ok_response = self.client.get(reverse("api-dashboard"))
        self.assertEqual(ok_response.status_code, 200)

        self.staff.status = User.Status.INACTIVE
        self.staff.is_active = False
        self.staff.save(update_fields=["status", "is_active"])

        blocked_response = self.client.get(reverse("api-dashboard"))
        self.assertEqual(blocked_response.status_code, 401)

    # -- list filtering -------------------------------------------------------

    def test_status_filters_in_organization_user_list(self):
        self.staff.status = User.Status.SUSPENDED
        self.staff.is_active = False
        self.staff.suspended_at = timezone.now()
        self.staff.save(update_fields=["status", "is_active", "suspended_at"])
        self.client.force_login(self.admin)

        # The default (unfiltered) list still includes suspended/inactive/locked
        # accounts — like a soft-deleted user, only DELETED is hidden unless asked for.
        default_listing = self.client.get(reverse("api-org-users"))
        self.assertIn(str(self.staff.pk), {row["id"] for row in default_listing.json()["users"]})

        suspended_listing = self.client.get(reverse("api-org-users"), {"status": "suspended"})
        ids = {row["id"] for row in suspended_listing.json()["users"]}
        self.assertIn(str(self.staff.pk), ids)
        row = next(row for row in suspended_listing.json()["users"] if row["id"] == str(self.staff.pk))
        self.assertEqual(row["status"], "suspended")
        self.assertEqual(row["statusLabel"], "Suspended")


class SessionManagementTests(TestCase):
    """Per-device session tracking: concurrency limits, revocation on new
    login, account-status/password integration, idle/absolute timeout, and
    self-service session management. Each "browser" is a separate `Client()`
    instance sharing no cookies with the others.
    """

    def setUp(self):
        self.organization = Organization.objects.create(name="Session Clinic", slug="session-clinic")
        self.admin = User.objects.create_user(
            username="session-admin", password="safe-test-password", organization=self.organization, role=User.Role.ADMIN
        )
        self.scheduler = User.objects.create_user(
            username="session-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        self.therapist = User.objects.create_user(
            username="session-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST
        )

    def _login(self, client, username, password="safe-test-password"):
        return client.post(
            reverse("api-login"),
            data=json.dumps({"username": username, "password": password}),
            content_type="application/json",
        )

    def test_new_login_revokes_previous_session_for_single_session_role(self):
        browser_a = Client()
        browser_b = Client()
        self.assertEqual(self._login(browser_a, "session-scheduler").status_code, 200)
        ok = browser_a.get(reverse("api-dashboard"))
        self.assertEqual(ok.status_code, 200)

        self.assertEqual(self._login(browser_b, "session-scheduler").status_code, 200)

        blocked = browser_a.get(reverse("api-dashboard"))
        self.assertEqual(blocked.status_code, 401)
        self.assertEqual(blocked.json().get("code"), "NEW_LOGIN")
        self.assertIn("another browser or device", blocked.json()["detail"])

        still_ok = browser_b.get(reverse("api-dashboard"))
        self.assertEqual(still_ok.status_code, 200)

    def test_role_with_two_session_limit_keeps_both(self):
        browser_a = Client()
        browser_b = Client()
        self._login(browser_a, "session-therapist")
        self._login(browser_b, "session-therapist")
        self.assertEqual(browser_a.get(reverse("api-dashboard")).status_code, 200)
        self.assertEqual(browser_b.get(reverse("api-dashboard")).status_code, 200)

    def test_third_login_revokes_oldest_session_for_two_session_role(self):
        browser_a = Client()
        browser_b = Client()
        browser_c = Client()
        self._login(browser_a, "session-therapist")
        self._login(browser_b, "session-therapist")
        self._login(browser_c, "session-therapist")

        self.assertEqual(browser_a.get(reverse("api-dashboard")).status_code, 401)
        self.assertEqual(browser_b.get(reverse("api-dashboard")).status_code, 200)
        self.assertEqual(browser_c.get(reverse("api-dashboard")).status_code, 200)

    def test_suspending_a_user_revokes_their_active_session(self):
        browser = Client()
        self._login(browser, "session-scheduler")
        self.assertEqual(browser.get(reverse("api-dashboard")).status_code, 200)

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("api-org-user-status-action", kwargs={"user_id": self.scheduler.pk}),
            data=json.dumps({"action": "suspend", "reason": "test"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        blocked = browser.get(reverse("api-dashboard"))
        self.assertEqual(blocked.status_code, 401)
        self.assertEqual(blocked.json().get("code"), "ACCOUNT_SUSPENDED")

    def test_deactivating_a_user_revokes_their_session(self):
        browser = Client()
        self._login(browser, "session-scheduler")
        self.client.force_login(self.admin)
        self.client.post(
            reverse("api-org-user-status-action", kwargs={"user_id": self.scheduler.pk}),
            data=json.dumps({"action": "deactivate"}),
            content_type="application/json",
        )
        response = browser.get(reverse("api-dashboard"))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json().get("code"), "ACCOUNT_DEACTIVATED")

    def test_deleting_a_user_revokes_their_session(self):
        browser = Client()
        self._login(browser, "session-therapist")
        self.client.force_login(self.admin)
        self.client.post(
            reverse("api-org-user-status-action", kwargs={"user_id": self.therapist.pk}),
            data=json.dumps({"action": "delete"}),
            content_type="application/json",
        )
        response = browser.get(reverse("api-dashboard"))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json().get("code"), "ACCOUNT_DELETED")

    def test_admin_password_reset_revokes_all_of_the_users_sessions(self):
        browser = Client()
        self._login(browser, "session-scheduler")
        self.assertEqual(browser.get(reverse("api-dashboard")).status_code, 200)

        self.client.force_login(self.admin)
        response = self.client.patch(
            reverse("api-org-user-detail", kwargs={"user_id": self.scheduler.pk}),
            data=json.dumps({"password": "brand-new-password-123"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        blocked = browser.get(reverse("api-dashboard"))
        self.assertEqual(blocked.status_code, 401)
        self.assertEqual(blocked.json().get("code"), "PASSWORD_RESET")

    def test_self_service_password_change_keeps_current_session_revokes_others(self):
        # Use the therapist role (session limit 2) so both logins survive —
        # a 1-session role would revoke browser_a the instant browser_b logs
        # in, unrelated to what this test is actually checking.
        browser_a = Client()
        browser_b = Client()
        self._login(browser_a, "session-therapist")
        self._login(browser_b, "session-therapist")

        response = browser_a.post(
            reverse("api-change-password"),
            data=json.dumps({"currentPassword": "safe-test-password", "newPassword": "brand-new-password-456"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        self.assertEqual(browser_a.get(reverse("api-dashboard")).status_code, 200)
        blocked = browser_b.get(reverse("api-dashboard"))
        self.assertEqual(blocked.status_code, 401)
        self.assertEqual(blocked.json().get("code"), "PASSWORD_CHANGED")

    def test_admin_can_sign_user_out_of_all_devices(self):
        browser_a = Client()
        browser_b = Client()
        self._login(browser_a, "session-therapist")
        self._login(browser_b, "session-therapist")

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("api-org-user-revoke-sessions", kwargs={"user_id": self.therapist.pk}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["revokedCount"], 2)
        self.assertTrue(AuditEvent.objects.filter(action="SESSION_REVOKED", object_id__in=[
            s.pk for s in UserSession.objects.filter(user=self.therapist)
        ]).exists())

        self.assertEqual(browser_a.get(reverse("api-dashboard")).status_code, 401)
        self.assertEqual(browser_b.get(reverse("api-dashboard")).status_code, 401)

    def test_self_service_session_listing_and_revocation(self):
        browser_a = Client()
        browser_b = Client()
        self._login(browser_a, "session-therapist")
        self._login(browser_b, "session-therapist")

        listing = browser_a.get(reverse("api-my-sessions"))
        self.assertEqual(listing.status_code, 200)
        sessions = listing.json()["sessions"]
        self.assertEqual(len(sessions), 2)
        current = next(s for s in sessions if s["isCurrent"])
        other = next(s for s in sessions if not s["isCurrent"])

        revoke_response = browser_a.post(reverse("api-revoke-my-session", kwargs={"session_id": other["id"]}))
        self.assertEqual(revoke_response.status_code, 200)
        self.assertEqual(browser_b.get(reverse("api-dashboard")).status_code, 401)
        self.assertEqual(browser_a.get(reverse("api-dashboard")).status_code, 200)

        cannot_revoke_self = browser_a.post(reverse("api-revoke-my-session", kwargs={"session_id": current["id"]}))
        self.assertEqual(cannot_revoke_self.status_code, 400)

    def test_revoke_all_other_sessions_keeps_current(self):
        browser_a = Client()
        browser_b = Client()
        browser_c = Client()
        self._login(browser_a, "session-therapist")
        self._login(browser_b, "session-therapist")
        # third login would normally revoke the oldest (browser_a) under the
        # 2-session limit, so revoke browser_b's own "others" instead here
        response = browser_b.post(reverse("api-revoke-my-other-sessions"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(browser_b.get(reverse("api-dashboard")).status_code, 200)
        self.assertEqual(browser_a.get(reverse("api-dashboard")).status_code, 401)

    def test_logout_revokes_the_current_session(self):
        browser = Client()
        self._login(browser, "session-scheduler")
        session = UserSession.objects.get(user=self.scheduler)
        self.assertTrue(session.is_active)
        browser.post(reverse("api-logout"))
        session.refresh_from_db()
        self.assertIsNotNone(session.revoked_at)
        self.assertEqual(session.revoked_reason, UserSession.RevokedReason.USER_LOGOUT)

    def test_idle_timeout_ends_the_session(self):
        browser = Client()
        self._login(browser, "session-scheduler")
        session = UserSession.objects.get(user=self.scheduler)
        session.last_activity_at = timezone.now() - timedelta(minutes=20)
        session.save(update_fields=["last_activity_at"])

        response = browser.get(reverse("api-dashboard"))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json().get("code"), "IDLE_TIMEOUT")
        session.refresh_from_db()
        self.assertEqual(session.revoked_reason, UserSession.RevokedReason.IDLE_TIMEOUT)

    def test_absolute_timeout_ends_the_session(self):
        browser = Client()
        self._login(browser, "session-scheduler")
        session = UserSession.objects.get(user=self.scheduler)
        session.expires_at = timezone.now() - timedelta(minutes=1)
        session.save(update_fields=["expires_at"])

        response = browser.get(reverse("api-dashboard"))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json().get("code"), "ABSOLUTE_TIMEOUT")

    def test_untracked_legacy_session_is_not_blocked(self):
        """`force_login()` bypasses the login() view entirely, so no
        UserSession row exists for it — this must fail open, not break every
        other test in the suite that relies on `force_login()`.
        """
        self.client.force_login(self.scheduler)
        response = self.client.get(reverse("api-dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(UserSession.objects.filter(user=self.scheduler).exists())

    def test_account_lockout_revokes_an_existing_session(self):
        browser = Client()
        self._login(browser, "session-scheduler")
        self.assertEqual(browser.get(reverse("api-dashboard")).status_code, 200)

        attacker = Client()
        for _ in range(5):
            self._login(attacker, "session-scheduler", password="wrong-password")

        response = browser.get(reverse("api-dashboard"))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json().get("code"), "ACCOUNT_LOCKED")

    def test_organization_admin_cannot_revoke_sessions_for_another_orgs_user(self):
        other_org = Organization.objects.create(name="Other Session Org", slug="other-session-org")
        other_admin = User.objects.create_user(
            username="other-session-admin", password="safe-test-password", organization=other_org, role=User.Role.ADMIN
        )
        self.client.force_login(other_admin)
        response = self.client.post(
            reverse("api-org-user-revoke-sessions", kwargs={"user_id": self.scheduler.pk}),
        )
        self.assertEqual(response.status_code, 404)


class LicenseExpirationTests(TestCase):
    """PT/PTA license onboarding, expiry alerts, and auto-suspend."""

    def setUp(self):
        self.organization = Organization.objects.create(name="License Clinic", slug="license-clinic")
        self.admin = User.objects.create_user(
            username="license-admin", password="safe-test-password", organization=self.organization, role=User.Role.ADMIN
        )
        self.therapist = User.objects.create_user(
            username="license-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST
        )
        self.license = UserLicense.objects.create(
            user=self.therapist, license_number="PT-1000", issuing_state="NC",
            expires_at=date.today() + timedelta(days=200),
            verification_status=UserLicense.VerificationStatus.VERIFIED,
        )

    def _login(self, username, password="safe-test-password"):
        return self.client.post(
            reverse("api-login"),
            data=json.dumps({"username": username, "password": password}),
            content_type="application/json",
        )

    def _create_payload(self, **overrides):
        payload = {
            "username": "new-therapist",
            "firstName": "New",
            "lastName": "Therapist",
            "email": "new-therapist@example.com",
            "role": User.Role.THERAPIST,
            "password": "another-safe-password9",
            "confirmPassword": "another-safe-password9",
            "licenseNumber": "PT-2000",
            "licenseIssuingState": "CA",
            "licenseExpiresAt": (date.today() + timedelta(days=30)).isoformat(),
        }
        payload.update(overrides)
        return payload

    # -- onboarding validation ----------------------------------------------

    def test_creating_a_therapist_requires_license_fields(self):
        self.client.force_login(self.admin)
        payload = self._create_payload(licenseNumber="", licenseIssuingState="", licenseExpiresAt="")
        response = self.client.post(
            reverse("api-org-users"), data=json.dumps(payload), content_type="application/json"
        )
        self.assertEqual(response.status_code, 422)
        errors = response.json()["errors"]
        self.assertIn("licenseNumber", errors)
        self.assertIn("licenseIssuingState", errors)
        self.assertIn("licenseExpiresAt", errors)

    def test_creating_a_therapist_with_license_fields_succeeds(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("api-org-users"), data=json.dumps(self._create_payload()), content_type="application/json"
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()["user"]
        self.assertEqual(len(body["licenses"]), 1)
        self.assertEqual(body["licenses"][0]["licenseNumber"], "PT-2000")
        self.assertEqual(body["licenses"][0]["issuingState"], "CA")
        self.assertEqual(body["licenseAlertStatus"], "expiring_soon")

    def test_creating_a_scheduler_does_not_require_license_fields(self):
        self.client.force_login(self.admin)
        payload = self._create_payload(
            username="new-scheduler", role=User.Role.SCHEDULER,
            licenseNumber="", licenseIssuingState="", licenseExpiresAt="",
        )
        response = self.client.post(
            reverse("api-org-users"), data=json.dumps(payload), content_type="application/json"
        )
        self.assertEqual(response.status_code, 201)

    def test_invalid_license_date_format_is_rejected(self):
        self.client.force_login(self.admin)
        payload = self._create_payload(licenseExpiresAt="not-a-date")
        response = self.client.post(
            reverse("api-org-users"), data=json.dumps(payload), content_type="application/json"
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("licenseExpiresAt", response.json()["errors"])

    # -- license_alert_status / license_days_remaining -----------------------

    def test_license_alert_status_boundaries(self):
        self.license.expires_at = date.today() + timedelta(days=90)
        self.license.save(update_fields=["expires_at"])
        self.assertEqual(self.therapist.license_alert_status, "expiring_soon")
        self.license.expires_at = date.today() + timedelta(days=91)
        self.license.save(update_fields=["expires_at"])
        self.assertEqual(self.therapist.license_alert_status, "valid")
        self.license.expires_at = date.today() + timedelta(days=14)
        self.license.save(update_fields=["expires_at"])
        self.assertEqual(self.therapist.license_alert_status, "critical")
        self.license.expires_at = date.today() - timedelta(days=1)
        self.license.save(update_fields=["expires_at"])
        self.assertEqual(self.therapist.license_alert_status, "expired")
        self.license.delete()
        self.assertEqual(self.therapist.license_alert_status, "none")

    def test_license_alert_status_is_none_for_non_clinician_roles(self):
        scheduler = User.objects.create_user(
            username="license-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        UserLicense.objects.create(
            user=scheduler, license_number="X-1", issuing_state="NC", expires_at=date.today() - timedelta(days=1)
        )
        self.assertEqual(scheduler.license_alert_status, "none")

    # -- auto-suspend on login -------------------------------------------------

    def test_login_auto_suspends_a_therapist_with_an_expired_license(self):
        self.license.expires_at = date.today() - timedelta(days=1)
        self.license.save(update_fields=["expires_at"])
        response = self._login("license-therapist")
        self.assertEqual(response.status_code, 401)
        self.therapist.refresh_from_db()
        self.assertEqual(self.therapist.status, User.Status.SUSPENDED)
        self.assertFalse(self.therapist.is_active)
        self.assertIsNone(self.therapist.suspended_by)
        event = AuditEvent.objects.get(action="USER_LICENSE_EXPIRED", object_id=self.therapist.pk)
        self.assertIsNone(event.actor)
        self.assertEqual(event.metadata["expired_licenses"][0]["license_number"], "PT-1000")

    def test_login_does_not_suspend_a_therapist_with_a_valid_license(self):
        response = self._login("license-therapist")
        self.assertEqual(response.status_code, 200)
        self.therapist.refresh_from_db()
        self.assertEqual(self.therapist.status, User.Status.ACTIVE)

    def test_non_clinician_role_with_a_stray_past_date_is_never_auto_suspended(self):
        scheduler = User.objects.create_user(
            username="license-scheduler-2", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        UserLicense.objects.create(
            user=scheduler, license_number="X-2", issuing_state="NC", expires_at=date.today() - timedelta(days=1)
        )
        response = self._login("license-scheduler-2")
        self.assertEqual(response.status_code, 200)
        scheduler.refresh_from_db()
        self.assertEqual(scheduler.status, User.Status.ACTIVE)

    def test_expired_license_auto_suspend_revokes_active_sessions(self):
        self._login("license-therapist")
        self.assertTrue(UserSession.objects.filter(user=self.therapist, revoked_at__isnull=True).exists())
        self.license.expires_at = date.today() - timedelta(days=1)
        self.license.save(update_fields=["expires_at"])
        self._login("license-therapist")
        self.assertFalse(UserSession.objects.filter(user=self.therapist, revoked_at__isnull=True).exists())

    # -- auto-suspend via admin list view (lazy sweep) --------------------------

    def test_org_admin_list_view_sweeps_and_suspends_an_expired_therapist(self):
        self.license.expires_at = date.today() - timedelta(days=1)
        self.license.save(update_fields=["expires_at"])
        self.client.force_login(self.admin)
        response = self.client.get(reverse("api-org-users"))
        self.assertEqual(response.status_code, 200)
        body = {user["id"]: user for user in response.json()["users"]}
        self.assertEqual(body[str(self.therapist.pk)]["status"], "suspended")
        self.therapist.refresh_from_db()
        self.assertEqual(self.therapist.status, User.Status.SUSPENDED)

    def test_super_admin_list_view_sweeps_across_all_clients(self):
        platform_admin = User(username="license-platform-admin", role=User.Role.SUPER_ADMIN, is_superuser=True)
        platform_admin.set_password("safe-test-password")
        platform_admin.full_clean()
        platform_admin.save()
        self.license.expires_at = date.today() - timedelta(days=1)
        self.license.save(update_fields=["expires_at"])
        self.client.force_login(platform_admin)
        response = self.client.get(reverse("api-super-admin-users"))
        self.assertEqual(response.status_code, 200)
        self.therapist.refresh_from_db()
        self.assertEqual(self.therapist.status, User.Status.SUSPENDED)

    # -- editing license fields ------------------------------------------------

    def test_editing_license_expiration_updates_the_field_and_resets_verification(self):
        self.client.force_login(self.admin)
        new_date = (date.today() + timedelta(days=10)).isoformat()
        response = self.client.patch(
            reverse("api-org-user-license-detail", kwargs={"user_id": self.therapist.pk, "license_id": self.license.pk}),
            data=json.dumps({"expiresAt": new_date}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.license.refresh_from_db()
        self.assertEqual(self.license.expires_at.isoformat(), new_date)
        self.assertEqual(self.license.verification_status, UserLicense.VerificationStatus.PENDING_VERIFICATION)
        self.therapist.refresh_from_db()
        self.assertEqual(self.therapist.status, User.Status.ACTIVE)

    def test_renewing_a_license_on_a_suspended_user_does_not_auto_reactivate(self):
        self.license.expires_at = date.today() - timedelta(days=1)
        self.license.save(update_fields=["expires_at"])
        self._login("license-therapist")
        self.therapist.refresh_from_db()
        self.assertEqual(self.therapist.status, User.Status.SUSPENDED)

        self.client.force_login(self.admin)
        new_date = (date.today() + timedelta(days=365)).isoformat()
        response = self.client.patch(
            reverse("api-org-user-license-detail", kwargs={"user_id": self.therapist.pk, "license_id": self.license.pk}),
            data=json.dumps({"expiresAt": new_date}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.license.refresh_from_db()
        self.assertEqual(self.license.expires_at.isoformat(), new_date)
        self.therapist.refresh_from_db()
        self.assertEqual(self.therapist.status, User.Status.SUSPENDED)

    # -- management command -----------------------------------------------------

    def test_check_license_expirations_command_sweeps_multiple_organizations(self):
        other_org = Organization.objects.create(name="Other License Clinic", slug="other-license-clinic")
        other_therapist = User.objects.create_user(
            username="other-license-therapist", password="safe-test-password", organization=other_org, role=User.Role.ASSISTANT
        )
        UserLicense.objects.create(
            user=other_therapist, license_number="PTA-999", issuing_state="TX", expires_at=date.today() - timedelta(days=5)
        )
        self.license.expires_at = date.today() - timedelta(days=1)
        self.license.save(update_fields=["expires_at"])

        call_command("check_license_expirations")

        self.therapist.refresh_from_db()
        other_therapist.refresh_from_db()
        self.assertEqual(self.therapist.status, User.Status.SUSPENDED)
        self.assertEqual(other_therapist.status, User.Status.SUSPENDED)


class PlanOfCareAlertTests(TestCase):
    """Patient.plan_of_care_alert_tier/color_bucket and the corresponding
    patient_compliance_findings() entries, mirroring UserLicense's already-
    tested expiry-alert pattern."""

    def setUp(self):
        self.organization = Organization.objects.create(name="POC Clinic", slug="poc-clinic")
        self.therapist = User.objects.create_user(
            username="poc-therapist", password="safe-test-password",
            organization=self.organization, role=User.Role.THERAPIST,
        )
        self.patient = Patient.objects.create(
            organization=self.organization,
            first_name="Jordan",
            last_name="Patient",
            date_of_birth="1990-05-01",
            assigned_therapist=self.therapist,
        )

    def _note_with_poc_end(self, end_date, service_date=None):
        return ClinicalNote.objects.create(
            patient=self.patient,
            therapist=self.therapist,
            note_type=ClinicalNote.Type.EVALUATION,
            service_date=service_date or date.today(),
            objective="Objective findings.",
            assessment="Assessment.",
            plan="Plan.",
            plan_of_care_start=date.today() - timedelta(days=30),
            plan_of_care_end=end_date,
            frequency_per_week=2,
            duration_weeks=6,
        )

    def test_patient_with_no_documented_plan_of_care_has_no_alert(self):
        self.assertIsNone(self.patient.plan_of_care_end_date)
        self.assertEqual(self.patient.plan_of_care_alert_tier, "none")
        self.assertEqual(self.patient.plan_of_care_color_bucket, "none")

    def test_plan_of_care_alert_tier_boundaries(self):
        note = self._note_with_poc_end(date.today() + timedelta(days=30))
        self.assertEqual(self.patient.plan_of_care_alert_tier, "expiring_30")
        self.assertEqual(self.patient.plan_of_care_color_bucket, "expiring_soon")

        note.plan_of_care_end = date.today() + timedelta(days=31)
        note.save(update_fields=["plan_of_care_end"])
        self.assertEqual(self.patient.plan_of_care_alert_tier, "valid")
        self.assertEqual(self.patient.plan_of_care_color_bucket, "valid")

        note.plan_of_care_end = date.today() + timedelta(days=14)
        note.save(update_fields=["plan_of_care_end"])
        self.assertEqual(self.patient.plan_of_care_alert_tier, "critical_14")
        self.assertEqual(self.patient.plan_of_care_color_bucket, "critical")

        note.plan_of_care_end = date.today() - timedelta(days=1)
        note.save(update_fields=["plan_of_care_end"])
        self.assertEqual(self.patient.plan_of_care_alert_tier, "expired")
        self.assertEqual(self.patient.plan_of_care_color_bucket, "expired")

    def test_active_plan_of_care_ignores_notes_without_poc_fields(self):
        self._note_with_poc_end(
            date.today() + timedelta(days=60), service_date=date.today() - timedelta(days=10)
        )
        ClinicalNote.objects.create(
            patient=self.patient,
            therapist=self.therapist,
            note_type=ClinicalNote.Type.DAILY,
            service_date=date.today(),
            objective="Objective findings.",
            assessment="Assessment.",
            plan="Plan.",
        )
        # The most recent note overall has no plan_of_care_end — the older
        # evaluation note's POC window should still be the one that counts.
        self.assertEqual(
            self.patient.plan_of_care_end_date, date.today() + timedelta(days=60)
        )

    def test_expired_plan_of_care_is_a_blocking_compliance_finding(self):
        self._note_with_poc_end(date.today() - timedelta(days=1))
        findings = {f.code: f for f in patient_compliance_findings(self.patient)}
        self.assertIn("poc_expired", findings)
        self.assertTrue(findings["poc_expired"].finalization_blocker)

    def test_expiring_plan_of_care_is_a_non_blocking_compliance_finding(self):
        self._note_with_poc_end(date.today() + timedelta(days=7))
        findings = {f.code: f for f in patient_compliance_findings(self.patient)}
        self.assertIn("poc_expiring_soon", findings)
        self.assertFalse(findings["poc_expiring_soon"].finalization_blocker)
        self.assertEqual(findings["poc_expiring_soon"].severity, "high")

    def test_valid_plan_of_care_has_no_compliance_finding(self):
        self._note_with_poc_end(date.today() + timedelta(days=90))
        codes = {f.code for f in patient_compliance_findings(self.patient)}
        self.assertNotIn("poc_expiring_soon", codes)
        self.assertNotIn("poc_expired", codes)


class UserLicenseTests(TestCase):
    """Multiple licenses per PT/PTA, document upload/verification, and the
    verify-before-reactivate requirement."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Multi License Clinic", slug="multi-license-clinic")
        self.admin = User.objects.create_user(
            username="ml-admin", password="safe-test-password", organization=self.organization, role=User.Role.ADMIN
        )
        self.therapist = User.objects.create_user(
            username="ml-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST
        )
        self.license = UserLicense.objects.create(
            user=self.therapist, license_number="PT-100", issuing_state="NC",
            expires_at=date.today() + timedelta(days=200),
        )

    def _licenses_url(self):
        return reverse("api-org-user-licenses", kwargs={"user_id": self.therapist.pk})

    def _license_detail_url(self, license=None):
        return reverse(
            "api-org-user-license-detail",
            kwargs={"user_id": self.therapist.pk, "license_id": (license or self.license).pk},
        )

    def _document_url(self, license=None):
        return reverse(
            "api-org-user-license-document",
            kwargs={"user_id": self.therapist.pk, "license_id": (license or self.license).pk},
        )

    def _verify_url(self, license=None):
        return reverse(
            "api-org-user-license-verify",
            kwargs={"user_id": self.therapist.pk, "license_id": (license or self.license).pk},
        )

    # -- multi-license CRUD -------------------------------------------------

    def test_admin_can_add_a_second_license_for_a_different_state(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            self._licenses_url(),
            data=json.dumps({"licenseNumber": "PT-200", "issuingState": "VA", "expiresAt": (date.today() + timedelta(days=100)).isoformat()}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.therapist.licenses.count(), 2)

    def test_duplicate_license_for_same_state_and_number_is_rejected(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            self._licenses_url(),
            data=json.dumps({"licenseNumber": "PT-100", "issuingState": "NC", "expiresAt": (date.today() + timedelta(days=100)).isoformat()}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)

    def test_admin_can_delete_a_license(self):
        self.client.force_login(self.admin)
        response = self.client.delete(self._license_detail_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.therapist.licenses.count(), 0)

    # -- document upload / download -----------------------------------------

    def test_admin_can_upload_a_license_document(self):
        self.client.force_login(self.admin)
        upload = SimpleUploadedFile("license.pdf", b"%PDF-1.4 fake license document", content_type="application/pdf")
        response = self.client.post(self._document_url(), {"file": upload})
        self.assertEqual(response.status_code, 201)
        self.license.refresh_from_db()
        self.assertTrue(bool(self.license.document))
        self.assertEqual(self.license.verification_status, UserLicense.VerificationStatus.PENDING_VERIFICATION)

    def test_unsupported_document_type_is_rejected(self):
        self.client.force_login(self.admin)
        upload = SimpleUploadedFile("script.exe", b"MZ fake executable", content_type="application/octet-stream")
        response = self.client.post(self._document_url(), {"file": upload})
        self.assertEqual(response.status_code, 422)

    def test_admin_can_download_an_uploaded_license_document(self):
        self.client.force_login(self.admin)
        upload = SimpleUploadedFile("license.pdf", b"%PDF-1.4 fake license document", content_type="application/pdf")
        self.client.post(self._document_url(), {"file": upload})
        response = self.client.get(self._document_url())
        self.assertEqual(response.status_code, 200)

    def test_another_organizations_admin_cannot_download_this_license_document(self):
        self.client.force_login(self.admin)
        upload = SimpleUploadedFile("license.pdf", b"%PDF-1.4 fake license document", content_type="application/pdf")
        self.client.post(self._document_url(), {"file": upload})
        self.client.logout()

        other_org = Organization.objects.create(name="Other Multi License Clinic", slug="other-multi-license-clinic")
        other_admin = User.objects.create_user(
            username="ml-other-admin", password="safe-test-password", organization=other_org, role=User.Role.ADMIN
        )
        self.client.force_login(other_admin)
        response = self.client.get(self._document_url())
        self.assertEqual(response.status_code, 404)

    # -- verification ---------------------------------------------------------

    def test_verifying_requires_a_document_first(self):
        self.client.force_login(self.admin)
        response = self.client.post(self._verify_url(), data=json.dumps({}), content_type="application/json")
        self.assertEqual(response.status_code, 422)

    def test_admin_can_verify_a_license_with_a_document(self):
        self.client.force_login(self.admin)
        upload = SimpleUploadedFile("license.pdf", b"%PDF-1.4 fake license document", content_type="application/pdf")
        self.client.post(self._document_url(), {"file": upload})
        response = self.client.post(
            self._verify_url(), data=json.dumps({"notes": "Checked against the state board site."}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        self.license.refresh_from_db()
        self.assertEqual(self.license.verification_status, UserLicense.VerificationStatus.VERIFIED)
        self.assertEqual(self.license.verified_by, self.admin)
        self.assertIsNotNone(self.license.verified_at)
        event = AuditEvent.objects.get(action="provider_license.verified", object_id=self.license.pk)
        self.assertEqual(event.actor, self.admin)

    def test_non_admin_cannot_verify_a_license(self):
        scheduler = User.objects.create_user(
            username="ml-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        self.client.force_login(scheduler)
        response = self.client.post(self._verify_url(), data=json.dumps({}), content_type="application/json")
        self.assertEqual(response.status_code, 403)

    # -- escalating alert tiers -------------------------------------------------

    def test_alert_tier_escalates_at_each_threshold(self):
        cases = [
            (91, "valid"), (90, "expiring_90"), (60, "expiring_60"), (30, "expiring_30"),
            (14, "critical_14"), (7, "critical_7"), (0, "critical_7"), (-1, "expired"),
        ]
        for days, expected_tier in cases:
            self.license.expires_at = date.today() + timedelta(days=days)
            self.assertEqual(self.license.alert_tier, expected_tier, msg=f"days={days}")

    # -- auto-suspend across multiple licenses -----------------------------------

    def test_auto_suspend_fires_when_any_one_of_several_licenses_expires(self):
        UserLicense.objects.create(
            user=self.therapist, license_number="PT-200", issuing_state="VA", expires_at=date.today() + timedelta(days=100)
        )
        self.license.expires_at = date.today() - timedelta(days=1)
        self.license.save(update_fields=["expires_at"])
        response = self.client.post(
            reverse("api-login"),
            data=json.dumps({"username": "ml-therapist", "password": "safe-test-password"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        self.therapist.refresh_from_db()
        self.assertEqual(self.therapist.status, User.Status.SUSPENDED)

    # -- verify-before-reactivate ------------------------------------------------

    def test_reactivate_is_blocked_until_a_verified_current_license_exists(self):
        from care.user_management import suspend_user

        suspend_user(self.therapist, self.admin, reason="test")
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("api-org-user-status-action", kwargs={"user_id": self.therapist.pk}),
            data=json.dumps({"action": "reactivate"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.therapist.refresh_from_db()
        self.assertEqual(self.therapist.status, User.Status.SUSPENDED)

    def test_reactivate_succeeds_once_a_current_license_is_verified(self):
        from care.user_management import suspend_user

        suspend_user(self.therapist, self.admin, reason="test")
        self.client.force_login(self.admin)
        upload = SimpleUploadedFile("license.pdf", b"%PDF-1.4 fake license document", content_type="application/pdf")
        self.client.post(self._document_url(), {"file": upload})
        self.client.post(self._verify_url(), data=json.dumps({}), content_type="application/json")

        response = self.client.post(
            reverse("api-org-user-status-action", kwargs={"user_id": self.therapist.pk}),
            data=json.dumps({"action": "reactivate"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.therapist.refresh_from_db()
        self.assertEqual(self.therapist.status, User.Status.ACTIVE)

    def test_reactivate_is_blocked_when_a_different_license_is_still_expired(self):
        """Even with one verified, current license, reactivation must stay
        blocked while another of this provider's licenses is still expired —
        symmetric with suspend firing on ANY expired license, so reactivating
        never immediately flaps back to suspended on the next list sweep."""
        from care.user_management import suspend_user

        UserLicense.objects.create(
            user=self.therapist, license_number="PT-200", issuing_state="VA", expires_at=date.today() - timedelta(days=1)
        )
        suspend_user(self.therapist, self.admin, reason="test")
        self.client.force_login(self.admin)
        upload = SimpleUploadedFile("license.pdf", b"%PDF-1.4 fake license document", content_type="application/pdf")
        self.client.post(self._document_url(license=self.license), {"file": upload})
        self.client.post(self._verify_url(license=self.license), data=json.dumps({}), content_type="application/json")

        response = self.client.post(
            reverse("api-org-user-status-action", kwargs={"user_id": self.therapist.pk}),
            data=json.dumps({"action": "reactivate"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.therapist.refresh_from_db()
        self.assertEqual(self.therapist.status, User.Status.SUSPENDED)


class DocumentationApiTests(TestCase):
    """React-facing clinical documentation API: create/view/edit/sign/addendum
    for ClinicalNote, and the Documentation landing page's list endpoint."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Doc Clinic", slug="doc-clinic")
        self.admin = User.objects.create_user(
            username="doc-admin", password="safe-test-password", organization=self.organization, role=User.Role.ADMIN
        )
        self.therapist = User.objects.create_user(
            username="doc-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST
        )
        self.other_therapist = User.objects.create_user(
            username="doc-other-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST
        )
        self.scheduler = User.objects.create_user(
            username="doc-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Dana", last_name="Doc",
            date_of_birth="1990-01-01", assigned_therapist=self.therapist, diagnoses="Low back pain",
        )

    def _complete_note_payload(self, **overrides):
        payload = {
            "subjective": "Reports improved tolerance.",
            "objective": "Walked 300 feet with no assistive device.",
            "assessment": "Improved gait tolerance.",
            "plan": "Continue plan of care and reassess next visit.",
        }
        payload.update(overrides)
        return payload

    def test_therapist_can_create_a_note_for_their_patient(self):
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-note-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"noteType": ClinicalNote.Type.DAILY}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()["note"]
        self.assertEqual(body["status"], "draft")
        self.assertEqual(ClinicalNote.objects.filter(patient=self.patient).count(), 1)

    def test_scheduler_cannot_create_a_note(self):
        self.client.force_login(self.scheduler)
        response = self.client.post(
            reverse("api-note-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"noteType": ClinicalNote.Type.DAILY}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_creating_a_note_for_an_appointment_that_already_has_one_returns_the_existing_note(self):
        appointment = Appointment.objects.create(
            patient=self.patient, therapist=self.therapist, kind=Appointment.Kind.FOLLOW_UP,
            starts_at=timezone.now(), ends_at=timezone.now() + timedelta(minutes=30),
            created_by=self.therapist,
        )
        existing = ClinicalNote.objects.create(
            patient=self.patient, therapist=self.therapist, appointment=appointment, note_type=ClinicalNote.Type.DAILY,
        )
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-note-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"noteType": ClinicalNote.Type.DAILY, "appointmentId": str(appointment.pk)}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["note"]["id"], str(existing.pk))
        self.assertEqual(ClinicalNote.objects.filter(appointment=appointment).count(), 1)

    def test_author_can_edit_their_own_draft_note(self):
        note = ClinicalNote.objects.create(patient=self.patient, therapist=self.therapist, note_type=ClinicalNote.Type.DAILY)
        self.client.force_login(self.therapist)
        response = self.client.patch(
            reverse("api-note-detail", kwargs={"note_id": note.pk}),
            data=json.dumps({"subjective": "Updated subjective."}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        note.refresh_from_db()
        self.assertEqual(note.subjective, "Updated subjective.")

    def test_another_therapist_cannot_edit_someone_elses_draft_note(self):
        note = ClinicalNote.objects.create(patient=self.patient, therapist=self.therapist, note_type=ClinicalNote.Type.DAILY)
        self.client.force_login(self.other_therapist)
        response = self.client.patch(
            reverse("api-note-detail", kwargs={"note_id": note.pk}),
            data=json.dumps({"subjective": "Should not be allowed."}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_can_edit_any_draft_note_in_their_org(self):
        note = ClinicalNote.objects.create(patient=self.patient, therapist=self.therapist, note_type=ClinicalNote.Type.DAILY)
        self.client.force_login(self.admin)
        response = self.client.patch(
            reverse("api-note-detail", kwargs={"note_id": note.pk}),
            data=json.dumps({"subjective": "Admin edit."}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

    def test_signed_note_cannot_be_edited_via_api(self):
        note = ClinicalNote.objects.create(
            patient=self.patient, therapist=self.therapist, note_type=ClinicalNote.Type.DAILY,
            status=ClinicalNote.Status.SIGNED, signature_name="Doc Therapist",
            signed_at=timezone.now(), finalization_attestation=True,
        )
        self.client.force_login(self.therapist)
        response = self.client.patch(
            reverse("api-note-detail", kwargs={"note_id": note.pk}),
            data=json.dumps({"subjective": "Should be blocked."}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_sign_happy_path_records_signature_and_audit(self):
        note = ClinicalNote.objects.create(
            patient=self.patient, therapist=self.therapist, note_type=ClinicalNote.Type.DAILY,
            **self._complete_note_payload(),
        )
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-note-sign", kwargs={"note_id": note.pk}),
            data=json.dumps({"attestation": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        note.refresh_from_db()
        self.assertEqual(note.status, ClinicalNote.Status.SIGNED)
        self.assertTrue(AuditEvent.objects.filter(action="note.signed", object_id=note.pk).exists())

    def test_signing_a_note_completes_its_linked_appointment(self):
        appointment = Appointment.objects.create(
            patient=self.patient, therapist=self.therapist, kind=Appointment.Kind.FOLLOW_UP,
            starts_at=timezone.now(), ends_at=timezone.now() + timedelta(minutes=30),
            created_by=self.therapist, status=Appointment.Status.CHECKED_IN,
        )
        note = ClinicalNote.objects.create(
            patient=self.patient, therapist=self.therapist, appointment=appointment, note_type=ClinicalNote.Type.DAILY,
            **self._complete_note_payload(),
        )
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-note-sign", kwargs={"note_id": note.pk}),
            data=json.dumps({"attestation": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.COMPLETED)

    def test_signing_a_note_does_not_revive_a_cancelled_appointment(self):
        appointment = Appointment.objects.create(
            patient=self.patient, therapist=self.therapist, kind=Appointment.Kind.FOLLOW_UP,
            starts_at=timezone.now(), ends_at=timezone.now() + timedelta(minutes=30),
            created_by=self.therapist, status=Appointment.Status.CANCELLED,
        )
        note = ClinicalNote.objects.create(
            patient=self.patient, therapist=self.therapist, appointment=appointment, note_type=ClinicalNote.Type.DAILY,
            **self._complete_note_payload(),
        )
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-note-sign", kwargs={"note_id": note.pk}),
            data=json.dumps({"attestation": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.CANCELLED)

    def test_sign_blocked_by_compliance_findings(self):
        note = ClinicalNote.objects.create(patient=self.patient, therapist=self.therapist, note_type=ClinicalNote.Type.DAILY)
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-note-sign", kwargs={"note_id": note.pk}),
            data=json.dumps({"attestation": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        note.refresh_from_db()
        self.assertEqual(note.status, ClinicalNote.Status.DRAFT)

    def test_sign_denied_for_wrong_role(self):
        note = ClinicalNote.objects.create(
            patient=self.patient, therapist=self.therapist, note_type=ClinicalNote.Type.DAILY,
            **self._complete_note_payload(),
        )
        self.client.force_login(self.scheduler)
        response = self.client.post(
            reverse("api-note-sign", kwargs={"note_id": note.pk}),
            data=json.dumps({"attestation": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_documentation_list_supports_quick_filters(self):
        ClinicalNote.objects.create(patient=self.patient, therapist=self.therapist, note_type=ClinicalNote.Type.DAILY, status=ClinicalNote.Status.DRAFT)
        ClinicalNote.objects.create(
            patient=self.patient, therapist=self.other_therapist, note_type=ClinicalNote.Type.DAILY,
            status=ClinicalNote.Status.SIGNED, signature_name="Other", signed_at=timezone.now(), finalization_attestation=True,
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse("api-documentation-list"), {"quick": "drafts"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["notes"][0]["status"], "draft")

        response = self.client.get(reverse("api-documentation-list"), {"quick": "completed"})
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["notes"][0]["status"], "signed")

    def test_documentation_list_is_tenant_isolated(self):
        other_org = Organization.objects.create(name="Other Doc Clinic", slug="other-doc-clinic")
        other_admin = User.objects.create_user(
            username="other-doc-admin", password="safe-test-password", organization=other_org, role=User.Role.ADMIN
        )
        other_therapist = User.objects.create_user(
            username="other-doc-therapist", password="safe-test-password", organization=other_org, role=User.Role.THERAPIST
        )
        other_patient = Patient.objects.create(
            organization=other_org, first_name="Other", last_name="Patient",
            date_of_birth="1990-01-01", assigned_therapist=other_therapist,
        )
        ClinicalNote.objects.create(patient=other_patient, therapist=other_therapist, note_type=ClinicalNote.Type.DAILY)
        ClinicalNote.objects.create(patient=self.patient, therapist=self.therapist, note_type=ClinicalNote.Type.DAILY)

        self.client.force_login(self.admin)
        response = self.client.get(reverse("api-documentation-list"))
        self.assertEqual(response.json()["total"], 1)

        self.client.logout()
        self.client.force_login(other_admin)
        response = self.client.get(reverse("api-documentation-list"))
        self.assertEqual(response.json()["total"], 1)

    def test_addendum_only_allowed_on_signed_notes(self):
        draft_note = ClinicalNote.objects.create(patient=self.patient, therapist=self.therapist, note_type=ClinicalNote.Type.DAILY)
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-note-addendum-create", kwargs={"note_id": draft_note.pk}),
            data=json.dumps({"reason": "Clarify", "body": "More detail."}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

        signed_note = ClinicalNote.objects.create(
            patient=self.patient, therapist=self.therapist, note_type=ClinicalNote.Type.DAILY,
            status=ClinicalNote.Status.SIGNED, signature_name="Doc Therapist",
            signed_at=timezone.now(), finalization_attestation=True,
        )
        response = self.client.post(
            reverse("api-note-addendum-create", kwargs={"note_id": signed_note.pk}),
            data=json.dumps({"reason": "Clarify measurement", "body": "Measured in feet."}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(NoteAddendum.objects.filter(note=signed_note).count(), 1)
        signed_note.refresh_from_db()
        self.assertEqual(signed_note.status, ClinicalNote.Status.SIGNED)

    def test_interventions_bulk_replace_sums_minutes_correctly(self):
        note = ClinicalNote.objects.create(patient=self.patient, therapist=self.therapist, note_type=ClinicalNote.Type.DAILY)
        self.client.force_login(self.therapist)
        response = self.client.put(
            reverse("api-note-interventions-replace", kwargs={"note_id": note.pk}),
            data=json.dumps({"items": [
                {"description": "Therapeutic exercise", "minutes": 25, "isTimed": True},
                {"description": "Manual therapy", "minutes": 15, "isTimed": True},
            ]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        items = response.json()["interventionItems"]
        self.assertEqual(len(items), 2)
        self.assertEqual(sum(item["minutes"] for item in items), 40)

    def test_interventions_cannot_be_changed_once_signed(self):
        note = ClinicalNote.objects.create(
            patient=self.patient, therapist=self.therapist, note_type=ClinicalNote.Type.DAILY,
            status=ClinicalNote.Status.SIGNED, signature_name="Doc Therapist",
            signed_at=timezone.now(), finalization_attestation=True,
        )
        self.client.force_login(self.therapist)
        response = self.client.put(
            reverse("api-note-interventions-replace", kwargs={"note_id": note.pk}),
            data=json.dumps({"items": [{"description": "Should be blocked", "minutes": 10}]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)


class PtaCosignTests(TestCase):
    """PTA-authored notes requiring a supervising PT/Director cosignature —
    org-configurable via `Organization.pta_cosign_required`."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Cosign Clinic", slug="cosign-clinic")
        self.admin = User.objects.create_user(
            username="cosign-admin", password="safe-test-password", organization=self.organization, role=User.Role.ADMIN
        )
        self.supervising_therapist = User.objects.create_user(
            username="cosign-pt", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST
        )
        self.pta = User.objects.create_user(
            username="cosign-pta", password="safe-test-password", organization=self.organization, role=User.Role.ASSISTANT
        )
        # `Patient.assigned_therapist` is a single FK — the existing chart-access
        # model (`access.patients_for`) scopes a plain THERAPIST/ASSISTANT to only
        # their own assigned patients, so under today's architecture the realistic
        # cosigning actor for a PTA's assigned patient is ADMIN/DIRECTOR (org-wide
        # clinical access), not an unrelated peer THERAPIST — this test assigns
        # accordingly rather than working around access.py, which this feature
        # must not change.
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Cody", last_name="Cosign",
            date_of_birth="1990-01-01", assigned_therapist=self.pta,
        )

    def _complete_note_payload(self):
        return {
            "subjective": "Reports improved tolerance.",
            "objective": "Walked 300 feet with no assistive device.",
            "assessment": "Improved gait tolerance.",
            "plan": "Continue plan of care and reassess next visit.",
        }

    def test_pta_authored_note_requires_cosign_by_default(self):
        self.assertTrue(self.organization.pta_cosign_required)
        self.client.force_login(self.pta)
        response = self.client.post(
            reverse("api-note-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"noteType": ClinicalNote.Type.DAILY}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["note"]["cosignRequired"])

    def test_pta_sign_lands_on_review_required_when_cosign_required(self):
        note = ClinicalNote.objects.create(
            patient=self.patient, therapist=self.pta, note_type=ClinicalNote.Type.DAILY,
            cosign_required=True, **self._complete_note_payload(),
        )
        self.client.force_login(self.pta)
        response = self.client.post(
            reverse("api-note-sign", kwargs={"note_id": note.pk}),
            data=json.dumps({"attestation": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        note.refresh_from_db()
        self.assertEqual(note.status, ClinicalNote.Status.REVIEW_REQUIRED)
        self.assertTrue(note.finalization_attestation)

    def test_admin_can_cosign_and_note_becomes_signed(self):
        # Under the existing access.patients_for scoping (unchanged by this
        # feature), an admin/director has org-wide clinical access regardless
        # of `Patient.assigned_therapist` — the realistic cosigning actor for
        # a PTA's own assigned patient.
        appointment = Appointment.objects.create(
            patient=self.patient, therapist=self.pta, kind=Appointment.Kind.FOLLOW_UP,
            starts_at=timezone.now(), ends_at=timezone.now() + timedelta(minutes=30),
            created_by=self.pta, status=Appointment.Status.CHECKED_IN,
        )
        note = ClinicalNote.objects.create(
            patient=self.patient, therapist=self.pta, appointment=appointment, note_type=ClinicalNote.Type.DAILY,
            status=ClinicalNote.Status.REVIEW_REQUIRED, cosign_required=True,
            signature_name="Cosign Pta", signed_at=timezone.now(), finalization_attestation=True,
            **self._complete_note_payload(),
        )
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("api-note-cosign", kwargs={"note_id": note.pk}),
            data=json.dumps({}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        note.refresh_from_db()
        self.assertEqual(note.status, ClinicalNote.Status.SIGNED)
        self.assertEqual(note.cosigned_by, self.admin)
        self.assertIsNotNone(note.cosigned_at)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.COMPLETED)

    def test_pta_sign_goes_straight_to_signed_when_org_opts_out(self):
        self.organization.pta_cosign_required = False
        self.organization.save(update_fields=["pta_cosign_required"])
        note = ClinicalNote.objects.create(
            patient=self.patient, therapist=self.pta, note_type=ClinicalNote.Type.DAILY,
            cosign_required=False, **self._complete_note_payload(),
        )
        self.client.force_login(self.pta)
        response = self.client.post(
            reverse("api-note-sign", kwargs={"note_id": note.pk}),
            data=json.dumps({"attestation": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        note.refresh_from_db()
        self.assertEqual(note.status, ClinicalNote.Status.SIGNED)

    def test_self_cosign_denied(self):
        note = ClinicalNote.objects.create(
            patient=self.patient, therapist=self.pta, note_type=ClinicalNote.Type.DAILY,
            status=ClinicalNote.Status.REVIEW_REQUIRED, cosign_required=True,
            signature_name="Cosign Pta", signed_at=timezone.now(), finalization_attestation=True,
            **self._complete_note_payload(),
        )
        self.client.force_login(self.pta)
        response = self.client.post(
            reverse("api-note-cosign", kwargs={"note_id": note.pk}),
            data=json.dumps({}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_wrong_role_cannot_cosign(self):
        scheduler = User.objects.create_user(
            username="cosign-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER
        )
        note = ClinicalNote.objects.create(
            patient=self.patient, therapist=self.pta, note_type=ClinicalNote.Type.DAILY,
            status=ClinicalNote.Status.REVIEW_REQUIRED, cosign_required=True,
            signature_name="Cosign Pta", signed_at=timezone.now(), finalization_attestation=True,
            **self._complete_note_payload(),
        )
        self.client.force_login(scheduler)
        response = self.client.post(
            reverse("api-note-cosign", kwargs={"note_id": note.pk}),
            data=json.dumps({}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)


class SuperAdminDashboardTests(TestCase):
    """GET /api/v1/super-admin/dashboard/ — platform-wide aggregate counts."""

    def _platform_admin(self):
        platform_admin = User(username="dash-super-admin", role=User.Role.SUPER_ADMIN, is_superuser=True)
        platform_admin.set_password("safe-test-password")
        platform_admin.full_clean()
        platform_admin.save()
        return platform_admin

    def setUp(self):
        self.super_admin = self._platform_admin()
        self.active_org = Organization.objects.create(name="Dash Active Clinic", slug="dash-active", client_number=9100)
        self.suspended_org = Organization.objects.create(
            name="Dash Suspended Clinic", slug="dash-suspended", client_number=9101,
            status=Organization.Status.SUSPENDED,
        )
        self.archived_org = Organization.objects.create(
            name="Dash Archived Clinic", slug="dash-archived", client_number=9102,
            archived_at=timezone.now(),
        )

    def test_dashboard_requires_super_admin(self):
        org_admin = User.objects.create_user(
            username="dash-org-admin", password="safe-test-password", organization=self.active_org, role=User.Role.ADMIN,
        )
        self.client.force_login(org_admin)
        response = self.client.get(reverse("api-super-admin-dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_dashboard_counts_organizations_by_status_and_excludes_archived_from_live_counts(self):
        self.client.force_login(self.super_admin)
        response = self.client.get(reverse("api-super-admin-dashboard"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertGreaterEqual(body["organizations"]["total"], 3)
        self.assertGreaterEqual(body["organizations"]["active"], 1)
        self.assertGreaterEqual(body["organizations"]["suspended"], 1)
        self.assertGreaterEqual(body["organizations"]["archived"], 1)

    def test_dashboard_excludes_archived_organizations_users_and_patients(self):
        User.objects.create_user(
            username="dash-archived-therapist", password="safe-test-password",
            organization=self.archived_org, role=User.Role.THERAPIST,
        )
        Patient.objects.create(
            organization=self.archived_org, first_name="Ghost", last_name="Patient", date_of_birth="1990-01-01",
        )
        User.objects.create_user(
            username="dash-active-therapist", password="safe-test-password",
            organization=self.active_org, role=User.Role.THERAPIST,
        )
        Patient.objects.create(
            organization=self.active_org, first_name="Real", last_name="Patient", date_of_birth="1990-01-01",
        )

        self.client.force_login(self.super_admin)
        body = self.client.get(reverse("api-super-admin-dashboard")).json()

        self.assertGreaterEqual(body["users"]["total"], 1)
        self.assertGreaterEqual(body["patientsTotal"], 1)

    def test_dashboard_buckets_credential_alerts_by_expiry(self):
        therapist = User.objects.create_user(
            username="dash-license-therapist", password="safe-test-password",
            organization=self.active_org, role=User.Role.THERAPIST,
        )
        UserLicense.objects.create(
            user=therapist, license_number="EXP-1", issuing_state="NC",
            expires_at=date.today() - timedelta(days=1),
        )
        UserLicense.objects.create(
            user=therapist, license_number="VALID-1", issuing_state="NC",
            expires_at=date.today() + timedelta(days=200),
        )

        self.client.force_login(self.super_admin)
        body = self.client.get(reverse("api-super-admin-dashboard")).json()

        self.assertGreaterEqual(body["credentialAlerts"]["expired"], 1)
        self.assertGreaterEqual(body["credentialAlerts"]["valid"], 1)

    def test_dashboard_failed_login_trend_reflects_a_real_failed_attempt(self):
        User.objects.create_user(
            username="dash-fail-login", password="a-real-password-123456",
            organization=self.active_org, role=User.Role.SCHEDULER,
        )
        response = self.client.post(
            reverse("api-login"),
            data=json.dumps({"username": "dash-fail-login", "password": "wrong-password"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

        self.client.force_login(self.super_admin)
        body = self.client.get(reverse("api-super-admin-dashboard")).json()

        total_failed = sum(row["count"] for row in body["failedLoginTrend"])
        self.assertGreaterEqual(total_failed, 1)
        activity_actions = {row["action"] for row in body["recentUserActivity"]}
        self.assertIn("LOGIN_FAILED", activity_actions)

    def test_dashboard_recent_organizations_include_client_number(self):
        self.client.force_login(self.super_admin)
        body = self.client.get(reverse("api-super-admin-dashboard")).json()
        client_numbers = {row["clientNumber"] for row in body["recentOrganizations"]}
        self.assertIn(self.active_org.client_number, client_numbers)
        self.assertNotIn(self.archived_org.client_number, client_numbers)


class SuperAdminCredentialDashboardTests(TestCase):
    """GET /api/v1/super-admin/credentials/ — cross-org PT/PTA license roster."""

    def _platform_admin(self):
        platform_admin = User(username="cred-super-admin", role=User.Role.SUPER_ADMIN, is_superuser=True)
        platform_admin.set_password("safe-test-password")
        platform_admin.full_clean()
        platform_admin.save()
        return platform_admin

    def setUp(self):
        self.super_admin = self._platform_admin()
        self.organization = Organization.objects.create(name="Credential Clinic", slug="credential-clinic", client_number=9200)
        self.archived_org = Organization.objects.create(
            name="Credential Archived Clinic", slug="credential-archived", client_number=9201,
            archived_at=timezone.now(),
        )
        self.therapist = User.objects.create_user(
            username="cred-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
            first_name="Casey", last_name="Rivera",
        )

    def test_credential_dashboard_requires_super_admin(self):
        org_admin = User.objects.create_user(
            username="cred-org-admin", password="safe-test-password", organization=self.organization, role=User.Role.ADMIN,
        )
        self.client.force_login(org_admin)
        response = self.client.get(reverse("api-super-admin-credentials"))
        self.assertEqual(response.status_code, 403)

    def test_credential_dashboard_excludes_valid_licenses_by_default(self):
        UserLicense.objects.create(
            user=self.therapist, license_number="EXP-1", issuing_state="NC",
            expires_at=date.today() - timedelta(days=1),
        )
        UserLicense.objects.create(
            user=self.therapist, license_number="VALID-1", issuing_state="NC",
            expires_at=date.today() + timedelta(days=300),
        )
        self.client.force_login(self.super_admin)

        default_body = self.client.get(reverse("api-super-admin-credentials")).json()
        default_numbers = {row["licenseNumber"] for row in default_body["licenses"]}
        self.assertIn("EXP-1", default_numbers)
        self.assertNotIn("VALID-1", default_numbers)

        full_body = self.client.get(reverse("api-super-admin-credentials"), {"includeValid": "true"}).json()
        full_numbers = {row["licenseNumber"] for row in full_body["licenses"]}
        self.assertIn("EXP-1", full_numbers)
        self.assertIn("VALID-1", full_numbers)

    def test_credential_dashboard_reports_required_action_and_provider_details(self):
        UserLicense.objects.create(
            user=self.therapist, license_number="EXP-2", issuing_state="TX",
            expires_at=date.today() - timedelta(days=5),
        )
        self.client.force_login(self.super_admin)
        body = self.client.get(reverse("api-super-admin-credentials")).json()
        row = next(row for row in body["licenses"] if row["licenseNumber"] == "EXP-2")
        self.assertEqual(row["colorBucket"], "expired")
        self.assertIn("Renew", row["requiredAction"])
        self.assertEqual(row["providerName"], "Casey Rivera")
        self.assertEqual(row["clientNumber"], self.organization.client_number)
        self.assertEqual(row["issuingState"], "TX")

    def test_credential_dashboard_excludes_archived_organizations(self):
        archived_therapist = User.objects.create_user(
            username="cred-archived-therapist", password="safe-test-password",
            organization=self.archived_org, role=User.Role.THERAPIST,
        )
        UserLicense.objects.create(
            user=archived_therapist, license_number="ARCHIVED-EXP", issuing_state="NC",
            expires_at=date.today() - timedelta(days=1),
        )
        self.client.force_login(self.super_admin)
        body = self.client.get(reverse("api-super-admin-credentials"), {"includeValid": "true"}).json()
        license_numbers = {row["licenseNumber"] for row in body["licenses"]}
        self.assertNotIn("ARCHIVED-EXP", license_numbers)

    def test_credential_dashboard_includes_location_when_provider_profile_exists(self):
        location = Location.objects.create(organization=self.organization, name="Main Clinic")
        provider = Provider.objects.create(
            organization=self.organization, user=self.therapist, first_name="Casey", last_name="Rivera",
        )
        provider.locations.add(location)
        UserLicense.objects.create(
            user=self.therapist, license_number="LOC-1", issuing_state="NC",
            expires_at=date.today() - timedelta(days=1),
        )
        self.client.force_login(self.super_admin)
        body = self.client.get(reverse("api-super-admin-credentials")).json()
        row = next(row for row in body["licenses"] if row["licenseNumber"] == "LOC-1")
        self.assertEqual(row["location"], "Main Clinic")

    def test_credential_dashboard_bucket_filter(self):
        UserLicense.objects.create(
            user=self.therapist, license_number="EXP-3", issuing_state="NC",
            expires_at=date.today() - timedelta(days=1),
        )
        UserLicense.objects.create(
            user=self.therapist, license_number="SOON-1", issuing_state="NC",
            expires_at=date.today() + timedelta(days=20),
        )
        self.client.force_login(self.super_admin)
        body = self.client.get(reverse("api-super-admin-credentials"), {"bucket": "expired"}).json()
        numbers = {row["licenseNumber"] for row in body["licenses"]}
        self.assertIn("EXP-3", numbers)
        self.assertNotIn("SOON-1", numbers)


class OrganizationEntitlementTests(TestCase):
    """care.entitlements — the reusable feature-entitlement check, independent
    of any HTTP view."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Entitlement Clinic", slug="entitlement-clinic")
        self.ai_scribe = Feature.objects.create(code="ai_scribe", name="AI Scribe")
        self.billing = Feature.objects.create(code="billing", name="Billing")
        self.plan = SubscriptionPlan.objects.create(code="pro-test", name="Pro Test", provider_seat_limit=10)
        self.plan.features.add(self.ai_scribe)

    def test_organization_without_subscription_is_unrestricted(self):
        from care.entitlements import organization_has_feature

        self.assertTrue(organization_has_feature(self.organization, "ai_scribe"))
        self.assertTrue(organization_has_feature(self.organization, "anything_at_all"))

    def test_active_subscription_grants_only_its_own_features(self):
        from care.entitlements import organization_feature_codes, organization_has_feature

        subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=self.plan, status=OrganizationSubscription.Status.ACTIVE,
        )
        subscription.features.add(self.ai_scribe)

        self.assertTrue(organization_has_feature(self.organization, "ai_scribe"))
        self.assertFalse(organization_has_feature(self.organization, "billing"))
        self.assertEqual(organization_feature_codes(self.organization), {"ai_scribe"})

    def test_inactive_subscription_grants_nothing(self):
        from care.entitlements import organization_feature_codes, organization_has_feature

        subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=self.plan, status=OrganizationSubscription.Status.SUSPENDED,
        )
        subscription.features.add(self.ai_scribe)

        self.assertFalse(organization_has_feature(self.organization, "ai_scribe"))
        self.assertEqual(organization_feature_codes(self.organization), set())


class SuperAdminSubscriptionApiTests(TestCase):
    """GET/PATCH /api/v1/super-admin/clients/<n>/subscription/."""

    def _platform_admin(self):
        platform_admin = User(username="sub-super-admin", role=User.Role.SUPER_ADMIN, is_superuser=True)
        platform_admin.set_password("safe-test-password")
        platform_admin.full_clean()
        platform_admin.save()
        return platform_admin

    def setUp(self):
        self.super_admin = self._platform_admin()
        self.organization = Organization.objects.create(name="Sub Clinic", slug="sub-clinic", client_number=9300)
        self.ai_scribe = Feature.objects.create(code="ai_scribe", name="AI Scribe")
        self.billing = Feature.objects.create(code="billing", name="Billing")
        self.starter = SubscriptionPlan.objects.create(code="starter-test", name="Starter Test", provider_seat_limit=3)
        self.starter.features.add(self.billing)
        self.pro = SubscriptionPlan.objects.create(code="pro-test", name="Pro Test", provider_seat_limit=10)
        self.pro.features.add(self.ai_scribe, self.billing)

    def test_subscription_requires_super_admin(self):
        org_admin = User.objects.create_user(
            username="sub-org-admin", password="safe-test-password", organization=self.organization, role=User.Role.ADMIN,
        )
        self.client.force_login(org_admin)
        response = self.client.get(reverse("api-super-admin-client-subscription", kwargs={"client_number": self.organization.client_number}))
        self.assertEqual(response.status_code, 403)

    def test_get_returns_null_subscription_when_unassigned(self):
        self.client.force_login(self.super_admin)
        body = self.client.get(reverse("api-super-admin-client-subscription", kwargs={"client_number": self.organization.client_number})).json()
        self.assertIsNone(body["subscription"])
        self.assertTrue(any(plan["code"] == "starter-test" for plan in body["plans"]))

    def test_assigning_a_plan_creates_subscription_with_plan_features(self):
        self.client.force_login(self.super_admin)
        response = self.client.patch(
            reverse("api-super-admin-client-subscription", kwargs={"client_number": self.organization.client_number}),
            data=json.dumps({"planCode": "starter-test", "status": "active"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()["subscription"]
        self.assertEqual(body["planCode"], "starter-test")
        self.assertEqual(set(body["featureCodes"]), {"billing"})

    def test_changing_plan_resets_features_to_new_plan_baseline(self):
        self.client.force_login(self.super_admin)
        self.client.patch(
            reverse("api-super-admin-client-subscription", kwargs={"client_number": self.organization.client_number}),
            data=json.dumps({"planCode": "starter-test", "status": "active"}),
            content_type="application/json",
        )
        response = self.client.patch(
            reverse("api-super-admin-client-subscription", kwargs={"client_number": self.organization.client_number}),
            data=json.dumps({"planCode": "pro-test"}),
            content_type="application/json",
        )
        body = response.json()["subscription"]
        self.assertEqual(set(body["featureCodes"]), {"ai_scribe", "billing"})

    def test_explicit_features_override_without_requiring_a_plan_change(self):
        self.client.force_login(self.super_admin)
        self.client.patch(
            reverse("api-super-admin-client-subscription", kwargs={"client_number": self.organization.client_number}),
            data=json.dumps({"planCode": "pro-test", "status": "active"}),
            content_type="application/json",
        )
        response = self.client.patch(
            reverse("api-super-admin-client-subscription", kwargs={"client_number": self.organization.client_number}),
            data=json.dumps({"features": ["billing"]}),
            content_type="application/json",
        )
        body = response.json()["subscription"]
        self.assertEqual(set(body["featureCodes"]), {"billing"})
        self.assertEqual(body["planCode"], "pro-test")

    def test_invalid_plan_code_is_rejected(self):
        self.client.force_login(self.super_admin)
        response = self.client.patch(
            reverse("api-super-admin-client-subscription", kwargs={"client_number": self.organization.client_number}),
            data=json.dumps({"planCode": "not-a-real-plan"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)


class AiScribeEntitlementEnforcementTests(TestCase):
    """POST /api/v1/patients/<id>/drafts/ — the concrete proof that feature
    entitlement is enforced server-side, not just hidden in the UI."""

    def setUp(self):
        self.organization = Organization.objects.create(name="AI Scribe Clinic", slug="ai-scribe-clinic")
        self.therapist = User.objects.create_user(
            username="ai-scribe-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Drafts", last_name="Patient", date_of_birth="1990-01-01",
            assigned_therapist=self.therapist,
        )
        self.ai_scribe = Feature.objects.create(code="ai_scribe", name="AI Scribe")
        self.other_feature = Feature.objects.create(code="billing", name="Billing")

    def _request_draft(self):
        self.client.force_login(self.therapist)
        return self.client.post(
            reverse("api-draft-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"kind": "progress"}),
            content_type="application/json",
        )

    def test_draft_allowed_when_organization_has_no_subscription(self):
        response = self._request_draft()
        self.assertEqual(response.status_code, 201)

    def test_draft_blocked_when_subscription_lacks_ai_scribe(self):
        plan = SubscriptionPlan.objects.create(code="no-ai-plan", name="No AI Plan", provider_seat_limit=5)
        plan.features.add(self.other_feature)
        subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=plan, status=OrganizationSubscription.Status.ACTIVE,
        )
        subscription.features.add(self.other_feature)

        response = self._request_draft()
        self.assertEqual(response.status_code, 403)

    def test_draft_allowed_when_subscription_grants_ai_scribe(self):
        plan = SubscriptionPlan.objects.create(code="ai-plan", name="AI Plan", provider_seat_limit=5)
        plan.features.add(self.ai_scribe)
        subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=plan, status=OrganizationSubscription.Status.ACTIVE,
        )
        subscription.features.add(self.ai_scribe)

        response = self._request_draft()
        self.assertEqual(response.status_code, 201)


class AdditionalFeatureEntitlementEnforcementTests(TestCase):
    """Same enforcement pattern as AiScribeEntitlementEnforcementTests, for
    the other features that already have a real endpoint to gate: a
    subscription that grants everything except the feature under test must
    block that one endpoint with 403."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Feature Gate Clinic", slug="feature-gate-clinic")
        self.therapist = User.objects.create_user(
            username="fg-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        self.scheduler = User.objects.create_user(
            username="fg-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER,
        )
        self.biller = User.objects.create_user(
            username="fg-biller", password="safe-test-password", organization=self.organization, role=User.Role.BILLER,
        )
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Gate", last_name="Patient", date_of_birth="1990-01-01",
            assigned_therapist=self.therapist,
        )
        self.decoy_feature = Feature.objects.create(code="advanced_analytics", name="Advanced Analytics")

    def _subscription_without(self, *excluded_codes: str):
        """An active subscription granting every currently-gated feature
        except the ones named — proves the block is feature-specific, not
        just "no subscription at all"."""
        all_codes = {"outcome_measures", "hep", "crm", "billing"}
        granted_codes = all_codes - set(excluded_codes)
        plan = SubscriptionPlan.objects.create(code=f"partial-{'-'.join(excluded_codes)}", name="Partial Plan", provider_seat_limit=5)
        granted_features = [Feature.objects.get_or_create(code=code, defaults={"name": code})[0] for code in granted_codes]
        plan.features.add(self.decoy_feature, *granted_features)
        subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=plan, status=OrganizationSubscription.Status.ACTIVE,
        )
        subscription.features.add(self.decoy_feature, *granted_features)
        return subscription

    def test_outcome_create_blocked_without_outcome_measures_feature(self):
        self._subscription_without("outcome_measures")
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-outcome-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_home_program_create_blocked_without_hep_feature(self):
        self._subscription_without("hep")
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-home-program-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_referral_create_blocked_without_crm_feature(self):
        self._subscription_without("crm")
        self.client.force_login(self.scheduler)
        response = self.client.post(
            reverse("api-referral-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_superbill_create_blocked_without_billing_feature(self):
        self._subscription_without("billing")
        self.client.force_login(self.biller)
        response = self.client.post(
            reverse("api-superbill-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_outcome_create_allowed_when_feature_granted(self):
        self._subscription_without("hep")  # grants outcome_measures, withholds an unrelated one
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-outcome-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps(
                {"measure": "lefs", "score": "60", "maximumScore": "80", "measuredOn": date.today().isoformat()}
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)


class EpisodeOfCareTests(TestCase):
    """EpisodeOfCare — creation, tenant isolation, and its optional link from
    Appointment/ClinicalNote (both must belong to the same patient)."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Episode Clinic", slug="episode-clinic")
        self.other_organization = Organization.objects.create(name="Other Episode Clinic", slug="other-episode-clinic")
        self.therapist = User.objects.create_user(
            username="episode-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Episode", last_name="Patient", date_of_birth="1990-01-01",
            assigned_therapist=self.therapist,
        )
        self.other_patient = Patient.objects.create(
            organization=self.other_organization, first_name="Other", last_name="Patient", date_of_birth="1990-01-01",
        )

    def test_create_episode_via_api(self):
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-episode-of-care-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"diagnosis": "Right knee ACL repair", "status": "active"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()["episodeOfCare"]
        self.assertEqual(body["diagnosis"], "Right knee ACL repair")
        self.assertEqual(body["status"], "active")
        episode = EpisodeOfCare.objects.get(pk=body["id"])
        self.assertEqual(episode.organization_id, self.organization.id)
        self.assertEqual(episode.created_by, self.therapist)

    def test_cannot_create_episode_for_a_patient_in_another_organization(self):
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-episode-of-care-create", kwargs={"patient_id": self.other_patient.pk}),
            data=json.dumps({"diagnosis": "Should not be reachable"}),
            content_type="application/json",
        )
        self.assertIn(response.status_code, (403, 404))
        self.assertFalse(EpisodeOfCare.objects.filter(diagnosis="Should not be reachable").exists())

    def test_episode_end_date_before_start_date_is_rejected(self):
        episode = EpisodeOfCare(
            organization=self.organization, patient=self.patient, created_by=self.therapist,
            start_date=date.today(), end_date=date.today() - timedelta(days=1),
        )
        with self.assertRaises(ValidationError):
            episode.full_clean()

    def test_episode_from_a_different_patient_is_rejected_on_the_note(self):
        episode = EpisodeOfCare.objects.create(
            organization=self.other_organization, patient=self.other_patient, created_by=self.therapist,
        )
        note = ClinicalNote(
            patient=self.patient, therapist=self.therapist, note_type=ClinicalNote.Type.DAILY,
            episode_of_care=episode,
        )
        with self.assertRaises(ValidationError):
            note.full_clean()

    def test_note_create_api_attaches_a_valid_episode(self):
        episode = EpisodeOfCare.objects.create(organization=self.organization, patient=self.patient, created_by=self.therapist)
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-note-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"noteType": "daily", "episodeOfCareId": str(episode.pk)}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["note"]["episodeOfCareId"], str(episode.pk))

    def test_note_create_api_rejects_another_patients_episode(self):
        foreign_episode = EpisodeOfCare.objects.create(
            organization=self.other_organization, patient=self.other_patient, created_by=self.therapist,
        )
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-note-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"noteType": "daily", "episodeOfCareId": str(foreign_episode.pk)}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_appointment_create_api_attaches_a_valid_episode(self):
        episode = EpisodeOfCare.objects.create(organization=self.organization, patient=self.patient, created_by=self.therapist)
        scheduler = User.objects.create_user(
            username="episode-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER,
        )
        self.client.force_login(scheduler)
        starts_at = timezone.now().replace(microsecond=0) + timedelta(days=1)
        response = self.client.post(
            reverse("api-appointment-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps(
                {
                    "therapistId": str(self.therapist.pk),
                    "startsAt": starts_at.isoformat(),
                    "endsAt": (starts_at + timedelta(minutes=30)).isoformat(),
                    "kind": "follow_up",
                    "episodeOfCareId": str(episode.pk),
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["appointment"]["episodeOfCareId"], str(episode.pk))

    def test_workspace_bundle_lists_episodes_of_care(self):
        EpisodeOfCare.objects.create(
            organization=self.organization, patient=self.patient, created_by=self.therapist, diagnosis="Low back pain",
        )
        self.client.force_login(self.therapist)
        response = self.client.get(reverse("api-patient-workspace", kwargs={"patient_id": self.patient.pk}))
        self.assertEqual(response.status_code, 200)
        diagnoses = {row["diagnosis"] for row in response.json()["clinical"]["episodesOfCare"]}
        self.assertIn("Low back pain", diagnoses)

    def test_get_lists_episodes_for_the_patient(self):
        EpisodeOfCare.objects.create(
            organization=self.organization, patient=self.patient, created_by=self.therapist, diagnosis="Get-list diagnosis",
        )
        self.client.force_login(self.therapist)
        response = self.client.get(reverse("api-episode-of-care-create", kwargs={"patient_id": self.patient.pk}))
        self.assertEqual(response.status_code, 200)
        diagnoses = {row["diagnosis"] for row in response.json()["episodesOfCare"]}
        self.assertIn("Get-list diagnosis", diagnoses)

    def test_get_episodes_excludes_another_patients_records(self):
        EpisodeOfCare.objects.create(
            organization=self.other_organization, patient=self.other_patient, created_by=self.therapist, diagnosis="Foreign diagnosis",
        )
        self.client.force_login(self.therapist)
        response = self.client.get(reverse("api-episode-of-care-create", kwargs={"patient_id": self.patient.pk}))
        diagnoses = {row["diagnosis"] for row in response.json()["episodesOfCare"]}
        self.assertNotIn("Foreign diagnosis", diagnoses)


class AuthorizationTests(TestCase):
    """Authorization — creation, tenant isolation, visit/date alert tiers,
    and the concurrency-safe auto-decrement of visits_used when a linked
    appointment's note is signed."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Auth Clinic", slug="auth-clinic")
        self.other_organization = Organization.objects.create(name="Other Auth Clinic", slug="other-auth-clinic")
        self.therapist = User.objects.create_user(
            username="auth-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        self.biller = User.objects.create_user(
            username="auth-biller", password="safe-test-password", organization=self.organization, role=User.Role.BILLER,
        )
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Auth", last_name="Patient", date_of_birth="1990-01-01",
            assigned_therapist=self.therapist,
        )
        self.other_patient = Patient.objects.create(
            organization=self.other_organization, first_name="Other", last_name="Patient", date_of_birth="1990-01-01",
        )

    def test_create_authorization_via_api(self):
        self.client.force_login(self.biller)
        response = self.client.post(
            reverse("api-authorization-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps(
                {
                    "insuranceName": "Blue Shield",
                    "authorizationNumber": "AUTH-100",
                    "visitsApproved": 10,
                    "startDate": date.today().isoformat(),
                    "expiresAt": (date.today() + timedelta(days=60)).isoformat(),
                    "status": "active",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()["authorization"]
        self.assertEqual(body["visitsApproved"], 10)
        self.assertEqual(body["visitsRemaining"], 10)
        self.assertEqual(body["colorBucket"], "valid")

    def test_cannot_create_authorization_for_a_patient_in_another_organization(self):
        self.client.force_login(self.biller)
        response = self.client.post(
            reverse("api-authorization-create", kwargs={"patient_id": self.other_patient.pk}),
            data=json.dumps({"visitsApproved": 10, "expiresAt": (date.today() + timedelta(days=30)).isoformat()}),
            content_type="application/json",
        )
        self.assertIn(response.status_code, (403, 404))

    def test_scheduler_cannot_create_authorization(self):
        scheduler = User.objects.create_user(
            username="auth-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER,
        )
        self.client.force_login(scheduler)
        response = self.client.post(
            reverse("api-authorization-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"visitsApproved": 10, "expiresAt": (date.today() + timedelta(days=30)).isoformat()}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_visits_used_cannot_exceed_visits_approved(self):
        authorization = Authorization(
            organization=self.organization, patient=self.patient, created_by=self.biller,
            visits_approved=5, visits_used=6, expires_at=date.today() + timedelta(days=30),
        )
        with self.assertRaises(ValidationError):
            authorization.full_clean()

    def test_visit_alert_tier_escalates_as_visits_are_consumed(self):
        authorization = Authorization.objects.create(
            organization=self.organization, patient=self.patient, created_by=self.biller,
            visits_approved=10, visits_used=4, expires_at=date.today() + timedelta(days=90),
        )
        self.assertEqual(authorization.visits_remaining, 6)
        self.assertEqual(authorization.visit_alert_tier, "ok")

        authorization.visits_used = 5  # 5 remaining
        authorization.save(update_fields=["visits_used"])
        self.assertEqual(authorization.visit_alert_tier, "warning_5")

        authorization.visits_used = 7  # 3 remaining
        authorization.save(update_fields=["visits_used"])
        self.assertEqual(authorization.visit_alert_tier, "critical_3")

        authorization.visits_used = 9  # 1 remaining
        authorization.save(update_fields=["visits_used"])
        self.assertEqual(authorization.visit_alert_tier, "critical_1")

        authorization.visits_used = 10  # 0 remaining
        authorization.save(update_fields=["visits_used"])
        self.assertEqual(authorization.visit_alert_tier, "exhausted")
        self.assertEqual(authorization.overall_color_bucket, "expired")

    def test_date_alert_tier_reuses_the_shared_expiry_scale(self):
        authorization = Authorization.objects.create(
            organization=self.organization, patient=self.patient, created_by=self.biller,
            visits_approved=20, expires_at=date.today() - timedelta(days=1),
        )
        self.assertEqual(authorization.date_alert_tier, "expired")
        self.assertEqual(authorization.overall_color_bucket, "expired")

    def test_authorization_from_a_different_patient_is_rejected_on_the_appointment(self):
        foreign_authorization = Authorization.objects.create(
            organization=self.other_organization, patient=self.other_patient, created_by=self.therapist,
            visits_approved=10, expires_at=date.today() + timedelta(days=30),
        )
        appointment = Appointment(
            patient=self.patient, therapist=self.therapist, authorization=foreign_authorization,
            starts_at=timezone.now() + timedelta(days=1), ends_at=timezone.now() + timedelta(days=1, minutes=30),
            created_by=self.therapist,
        )
        with self.assertRaises(ValidationError):
            appointment.full_clean()

    def test_signing_a_note_decrements_the_linked_authorizations_visits_used(self):
        authorization = Authorization.objects.create(
            organization=self.organization, patient=self.patient, created_by=self.biller,
            visits_approved=10, visits_used=0, status=Authorization.Status.ACTIVE,
            expires_at=date.today() + timedelta(days=60),
        )
        appointment = Appointment.objects.create(
            patient=self.patient, therapist=self.therapist, authorization=authorization,
            starts_at=timezone.now() - timedelta(hours=1), ends_at=timezone.now() - timedelta(minutes=30),
            created_by=self.therapist, status=Appointment.Status.CHECKED_IN,
        )
        note = ClinicalNote.objects.create(
            patient=self.patient, therapist=self.therapist, appointment=appointment, note_type=ClinicalNote.Type.DAILY,
            objective="Objective findings.", assessment="Assessment.", plan="Plan.",
        )
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-note-sign", kwargs={"note_id": note.pk}),
            data=json.dumps({"attestation": True}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        authorization.refresh_from_db()
        appointment.refresh_from_db()
        self.assertEqual(authorization.visits_used, 1)
        self.assertEqual(authorization.visits_remaining, 9)
        self.assertEqual(appointment.status, Appointment.Status.COMPLETED)

    def test_signing_a_note_does_not_exceed_visits_approved(self):
        authorization = Authorization.objects.create(
            organization=self.organization, patient=self.patient, created_by=self.biller,
            visits_approved=1, visits_used=1, status=Authorization.Status.ACTIVE,
            expires_at=date.today() + timedelta(days=60),
        )
        appointment = Appointment.objects.create(
            patient=self.patient, therapist=self.therapist, authorization=authorization,
            starts_at=timezone.now() - timedelta(hours=1), ends_at=timezone.now() - timedelta(minutes=30),
            created_by=self.therapist, status=Appointment.Status.CHECKED_IN,
        )
        note = ClinicalNote.objects.create(
            patient=self.patient, therapist=self.therapist, appointment=appointment, note_type=ClinicalNote.Type.DAILY,
            objective="Objective findings.", assessment="Assessment.", plan="Plan.",
        )
        self.client.force_login(self.therapist)
        self.client.post(
            reverse("api-note-sign", kwargs={"note_id": note.pk}),
            data=json.dumps({"attestation": True}), content_type="application/json",
        )
        authorization.refresh_from_db()
        self.assertEqual(authorization.visits_used, 1)  # unchanged — already exhausted

    def test_billing_role_sees_authorizations_in_workspace_bundle(self):
        Authorization.objects.create(
            organization=self.organization, patient=self.patient, created_by=self.biller,
            visits_approved=10, expires_at=date.today() + timedelta(days=60), authorization_number="AUTH-WORKSPACE",
        )
        self.client.force_login(self.biller)
        response = self.client.get(reverse("api-patient-workspace", kwargs={"patient_id": self.patient.pk}))
        self.assertEqual(response.status_code, 200)
        numbers = {row["authorizationNumber"] for row in response.json()["operations"]["authorizations"]}
        self.assertIn("AUTH-WORKSPACE", numbers)

    def test_get_lists_authorizations_for_the_patient(self):
        Authorization.objects.create(
            organization=self.organization, patient=self.patient, created_by=self.biller,
            visits_approved=8, expires_at=date.today() + timedelta(days=30), authorization_number="AUTH-LIST",
        )
        self.client.force_login(self.biller)
        response = self.client.get(reverse("api-authorization-create", kwargs={"patient_id": self.patient.pk}))
        self.assertEqual(response.status_code, 200)
        numbers = {row["authorizationNumber"] for row in response.json()["authorizations"]}
        self.assertIn("AUTH-LIST", numbers)

    def test_get_authorizations_excludes_another_patients_records(self):
        Authorization.objects.create(
            organization=self.other_organization, patient=self.other_patient, created_by=self.therapist,
            visits_approved=8, expires_at=date.today() + timedelta(days=30), authorization_number="AUTH-FOREIGN",
        )
        self.client.force_login(self.biller)
        response = self.client.get(reverse("api-authorization-create", kwargs={"patient_id": self.patient.pk}))
        numbers = {row["authorizationNumber"] for row in response.json()["authorizations"]}
        self.assertNotIn("AUTH-FOREIGN", numbers)


class CodingSuggestionTests(TestCase):
    """AI Coding Assistance: deterministic CPT/unit suggestions from
    documented interventions. Covers the prompt's non-negotiable rules —
    suggestion only, never autonomous — plus tenant isolation and audit."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Coding Clinic", slug="coding-clinic")
        self.therapist = User.objects.create_user(
            username="coding-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Cody", last_name="Coder",
            date_of_birth="1990-01-01", assigned_therapist=self.therapist, diagnoses="Rotator cuff tendinopathy",
        )
        self.note = ClinicalNote.objects.create(
            patient=self.patient, therapist=self.therapist, note_type=ClinicalNote.Type.DAILY,
            assessment="Improved shoulder ROM and decreased pain with activity.",
        )
        self.ai_scribe = Feature.objects.create(code="ai_scribe", name="AI Scribe")

        self.other_organization = Organization.objects.create(name="Other Coding Clinic", slug="other-coding-clinic")
        self.other_therapist = User.objects.create_user(
            username="other-coding-therapist", password="safe-test-password", organization=self.other_organization, role=User.Role.THERAPIST,
        )

    def _add_interventions(self, note=None):
        note = note or self.note
        NoteIntervention.objects.create(
            note=note, description="Therapeutic exercise", minutes=25, is_timed=True,
            category=NoteIntervention.Category.THERAPEUTIC_EXERCISE, order=0,
        )
        NoteIntervention.objects.create(
            note=note, description="Manual therapy", minutes=15, is_timed=True,
            category=NoteIntervention.Category.MANUAL_THERAPY, order=1,
        )
        NoteIntervention.objects.create(
            note=note, description="Patient education on posture", minutes=5, is_timed=True,
            category=NoteIntervention.Category.PATIENT_EDUCATION, order=2,
        )

    # -- unit-level correctness -------------------------------------------------

    def test_suggestions_map_categories_to_cpt_codes_with_eight_minute_units(self):
        self._add_interventions()
        result = coding_suggestions(self.note)
        codes = {row["code"]: row for row in result["cptSuggestions"]}
        self.assertEqual(codes["97110"]["minutes"], 25)
        self.assertEqual(codes["97110"]["suggestedUnits"], 2)  # 8-22=1, 23-37=2
        self.assertEqual(codes["97140"]["minutes"], 15)
        self.assertEqual(codes["97140"]["suggestedUnits"], 1)
        self.assertNotIn("patient_education", codes)  # deliberately uncoded
        self.assertEqual(result["totalTimedMinutes"], 40)

    def test_suggestions_flag_documentation_gaps(self):
        empty_note = ClinicalNote.objects.create(patient=self.patient, therapist=self.therapist, note_type=ClinicalNote.Type.DAILY)
        result = coding_suggestions(empty_note)
        self.assertIn("No treatment interventions are documented on this note.", result["documentationGaps"])
        self.assertEqual(result["cptSuggestions"], [])
        self.assertEqual(result["totalSuggestedUnits"], 0)

    def test_suggestions_never_fabricate_a_code_for_uncategorized_minutes(self):
        NoteIntervention.objects.create(note=self.note, description="Uncategorized work", minutes=30, is_timed=True, order=0)
        result = coding_suggestions(self.note)
        self.assertEqual(result["cptSuggestions"], [])
        self.assertTrue(any("no intervention category" in gap for gap in result["documentationGaps"]))

    # -- API: generation, audit, and suggestion-only semantics -------------------

    def test_therapist_can_generate_coding_suggestions_for_their_note(self):
        self._add_interventions()
        self.client.force_login(self.therapist)
        response = self.client.post(reverse("api-note-coding-suggestions-create", kwargs={"note_id": self.note.pk}))
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["artifact"]["kind"], "coding")
        self.assertIn("Suggested", body["codingSuggestions"]["disclaimer"])
        artifact = AIArtifact.objects.get(pk=body["artifact"]["id"])
        self.assertEqual(artifact.source_note_ids, [str(self.note.pk)])
        self.assertEqual(artifact.status, AIArtifact.Status.DRAFT)

    def test_generating_coding_suggestions_records_an_audit_event(self):
        self._add_interventions()
        self.client.force_login(self.therapist)
        self.client.post(reverse("api-note-coding-suggestions-create", kwargs={"note_id": self.note.pk}))
        self.assertTrue(AuditEvent.objects.filter(action="ai_coding_suggestion.created", patient=self.patient).exists())

    def test_other_tenant_therapist_cannot_generate_suggestions_for_this_note(self):
        self.client.force_login(self.other_therapist)
        response = self.client.post(reverse("api-note-coding-suggestions-create", kwargs={"note_id": self.note.pk}))
        self.assertEqual(response.status_code, 403)

    def test_coding_suggestions_blocked_without_ai_scribe_entitlement(self):
        plan = SubscriptionPlan.objects.create(code="no-ai-coding-plan", name="No AI Plan", provider_seat_limit=5)
        other_feature = Feature.objects.create(code="billing", name="Billing")
        plan.features.add(other_feature)
        subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=plan, status=OrganizationSubscription.Status.ACTIVE,
        )
        subscription.features.add(other_feature)
        self.client.force_login(self.therapist)
        response = self.client.post(reverse("api-note-coding-suggestions-create", kwargs={"note_id": self.note.pk}))
        self.assertEqual(response.status_code, 403)

    def test_coding_artifact_cannot_be_applied_to_become_a_note(self):
        """A coding artifact must never turn into a signed (or even draft)
        clinical note by itself — it is a suggestion, not documentation."""
        self._add_interventions()
        artifact = AIArtifact.objects.create(
            patient=self.patient, requested_by=self.therapist, kind=AIArtifact.Kind.CODING,
            source_note_ids=[str(self.note.pk)], source_fingerprint="test", draft_text="Suggested codes.",
        )
        artifact.status = AIArtifact.Status.APPROVED
        artifact.save()
        note_count_before = ClinicalNote.objects.count()
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-draft-review", kwargs={"artifact_id": artifact.pk}),
            data=json.dumps({"action": "apply"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(ClinicalNote.objects.count(), note_count_before)

    def test_ai_cannot_sign_a_note_or_submit_a_claim_via_coding_suggestions(self):
        """Generating (and even approving) a coding suggestion must never
        sign the source note or create a billing claim on its own."""
        self._add_interventions()
        self.client.force_login(self.therapist)
        response = self.client.post(reverse("api-note-coding-suggestions-create", kwargs={"note_id": self.note.pk}))
        artifact_id = response.json()["artifact"]["id"]
        self.client.post(
            reverse("api-draft-review", kwargs={"artifact_id": artifact_id}),
            data=json.dumps({"action": "approve"}),
            content_type="application/json",
        )
        self.note.refresh_from_db()
        self.assertEqual(self.note.status, ClinicalNote.Status.DRAFT)
        self.assertFalse(Superbill.objects.filter(clinician=self.therapist).exists())


class AiDraftSectionReviewTests(TestCase):
    """Section-level review of AI-drafted content: a therapist can accept,
    edit, or reject each section independently, and only accepted/edited
    sections are ever copied into the applied note — never the whole draft
    blindly, and never anything still pending review."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Section Review Clinic", slug="section-review-clinic")
        self.therapist = User.objects.create_user(
            username="section-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        self.admin = User.objects.create_user(
            username="section-admin", password="safe-test-password", organization=self.organization, role=User.Role.ADMIN,
        )
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Sasha", last_name="Sections",
            date_of_birth="1990-01-01", assigned_therapist=self.therapist,
        )
        ClinicalNote.objects.create(
            patient=self.patient, therapist=self.therapist, note_type=ClinicalNote.Type.DAILY,
            status=ClinicalNote.Status.SIGNED, objective="Walked 300 feet with no assistive device.",
            assessment="Improved gait tolerance.", plan="Continue plan of care.",
            signature_name="Therapist", signed_at="2026-01-02T12:00:00Z", finalization_attestation=True,
        )

    def _create_progress_draft(self):
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-draft-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"kind": AIArtifact.Kind.PROGRESS}),
            content_type="application/json",
        )
        return response.json()["artifact"]

    def _section_review(self, artifact_id, section_key, status, reviewed_text=None):
        body = {"action": "section_review", "sectionKey": section_key, "sectionStatus": status}
        if reviewed_text is not None:
            body["reviewedText"] = reviewed_text
        return self.client.post(
            reverse("api-draft-review", kwargs={"artifact_id": artifact_id}),
            data=json.dumps(body),
            content_type="application/json",
        )

    def test_progress_draft_creation_returns_pending_sections(self):
        artifact = self._create_progress_draft()
        keys = {section["key"] for section in artifact["sections"]}
        self.assertEqual(keys, {"priorEvidence", "activeGoals", "outcomeTrends", "synthesisGuidance"})
        self.assertTrue(all(section["status"] == "pending" for section in artifact["sections"]))
        self.assertIn("Improved gait tolerance", artifact["sections"][0]["draftText"] + artifact["draftText"])

    def test_therapist_can_accept_a_section(self):
        artifact = self._create_progress_draft()
        response = self._section_review(artifact["id"], "activeGoals", "accepted")
        self.assertEqual(response.status_code, 200)
        section = next(s for s in response.json()["artifact"]["sections"] if s["key"] == "activeGoals")
        self.assertEqual(section["status"], "accepted")

    def test_therapist_can_edit_a_section_with_replacement_text(self):
        artifact = self._create_progress_draft()
        response = self._section_review(artifact["id"], "outcomeTrends", "edited", "Custom clinician-authored trend summary.")
        self.assertEqual(response.status_code, 200)
        section = next(s for s in response.json()["artifact"]["sections"] if s["key"] == "outcomeTrends")
        self.assertEqual(section["status"], "edited")
        self.assertEqual(section["reviewedText"], "Custom clinician-authored trend summary.")

    def test_editing_a_section_requires_reviewed_text(self):
        artifact = self._create_progress_draft()
        response = self._section_review(artifact["id"], "outcomeTrends", "edited")
        self.assertEqual(response.status_code, 400)

    def test_therapist_can_reject_a_section(self):
        artifact = self._create_progress_draft()
        response = self._section_review(artifact["id"], "priorEvidence", "rejected")
        self.assertEqual(response.status_code, 200)
        section = next(s for s in response.json()["artifact"]["sections"] if s["key"] == "priorEvidence")
        self.assertEqual(section["status"], "rejected")

    def test_section_review_rejects_an_unknown_section_key(self):
        artifact = self._create_progress_draft()
        response = self._section_review(artifact["id"], "not-a-real-section", "accepted")
        self.assertEqual(response.status_code, 400)

    def test_section_review_rejects_an_unknown_status(self):
        artifact = self._create_progress_draft()
        response = self._section_review(artifact["id"], "activeGoals", "signed")
        self.assertEqual(response.status_code, 400)

    def test_org_admin_can_also_review_sections(self):
        """Section review shares the same patient-access rule as whole-draft
        approve/reject — any clinician with chart access, not just the author."""
        artifact = self._create_progress_draft()
        self.client.force_login(self.admin)
        response = self._section_review(artifact["id"], "activeGoals", "accepted")
        self.assertEqual(response.status_code, 200)

    def test_apply_is_blocked_while_any_section_is_still_pending(self):
        artifact = self._create_progress_draft()
        self._section_review(artifact["id"], "priorEvidence", "accepted")
        self._section_review(artifact["id"], "activeGoals", "accepted")
        self._section_review(artifact["id"], "outcomeTrends", "accepted")
        # synthesisGuidance intentionally left pending
        self.client.post(
            reverse("api-draft-review", kwargs={"artifact_id": artifact["id"]}),
            data=json.dumps({"action": "approve"}),
            content_type="application/json",
        )
        response = self.client.post(
            reverse("api-draft-review", kwargs={"artifact_id": artifact["id"]}),
            data=json.dumps({"action": "apply"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(ClinicalNote.objects.filter(status=ClinicalNote.Status.DRAFT, note_type=ClinicalNote.Type.PROGRESS).count(), 0)

    def test_apply_after_full_section_review_excludes_rejected_sections(self):
        artifact = self._create_progress_draft()
        self._section_review(artifact["id"], "priorEvidence", "accepted")
        self._section_review(artifact["id"], "activeGoals", "rejected")
        self._section_review(artifact["id"], "outcomeTrends", "edited", "Trends look stable this period.")
        self._section_review(artifact["id"], "synthesisGuidance", "rejected")
        self.client.post(
            reverse("api-draft-review", kwargs={"artifact_id": artifact["id"]}),
            data=json.dumps({"action": "approve"}),
            content_type="application/json",
        )
        response = self.client.post(
            reverse("api-draft-review", kwargs={"artifact_id": artifact["id"]}),
            data=json.dumps({"action": "apply"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        applied_note = ClinicalNote.objects.get(note_type=ClinicalNote.Type.PROGRESS)
        self.assertIn("Improved gait tolerance", applied_note.assessment)  # from accepted priorEvidence
        self.assertIn("Trends look stable this period.", applied_note.assessment)  # from edited outcomeTrends
        self.assertNotIn("No active goals", applied_note.assessment)  # rejected activeGoals excluded
        self.assertNotIn("This section is guidance only", applied_note.assessment)  # rejected synthesisGuidance excluded

    def test_section_review_records_an_audit_event(self):
        artifact = self._create_progress_draft()
        self._section_review(artifact["id"], "activeGoals", "accepted")
        self.assertTrue(
            AuditEvent.objects.filter(action="ai_draft.section_reviewed", patient=self.patient).exists()
        )

    def test_section_review_blocked_once_draft_is_applied(self):
        artifact = self._create_progress_draft()
        for key in ("priorEvidence", "activeGoals", "outcomeTrends", "synthesisGuidance"):
            self._section_review(artifact["id"], key, "accepted")
        self.client.post(
            reverse("api-draft-review", kwargs={"artifact_id": artifact["id"]}),
            data=json.dumps({"action": "approve"}),
            content_type="application/json",
        )
        self.client.post(
            reverse("api-draft-review", kwargs={"artifact_id": artifact["id"]}),
            data=json.dumps({"action": "apply"}),
            content_type="application/json",
        )
        response = self._section_review(artifact["id"], "priorEvidence", "rejected")
        self.assertEqual(response.status_code, 409)

    def test_legacy_artifact_without_sections_still_applies_using_whole_draft_text(self):
        """Coding-style and other pre-existing artifacts created without a
        section breakdown must keep working exactly as before."""
        source_note = self.patient.notes.get()
        artifact = AIArtifact.objects.create(
            patient=self.patient, requested_by=self.therapist, kind=AIArtifact.Kind.PROGRESS,
            source_note_ids=[str(source_note.pk)], source_fingerprint="legacy-test", draft_text="Legacy whole-draft content.",
            status=AIArtifact.Status.APPROVED,
        )
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-draft-review", kwargs={"artifact_id": artifact.pk}),
            data=json.dumps({"action": "apply"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        applied_note = ClinicalNote.objects.get(note_type=ClinicalNote.Type.PROGRESS)
        self.assertEqual(applied_note.assessment, "Legacy whole-draft content.")


class PayerDirectoryTests(TestCase):
    """Billing/RCM Phase 1: the configurable payer directory. Rules (timely
    filing days, authorization requirement) live as data on the record, not
    hard-coded in the UI — these tests exercise that data round-trips."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Payer Clinic", slug="payer-clinic")
        self.biller = User.objects.create_user(
            username="payer-biller", password="safe-test-password", organization=self.organization, role=User.Role.BILLER,
        )
        self.scheduler = User.objects.create_user(
            username="payer-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER,
        )
        self.therapist = User.objects.create_user(
            username="payer-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        self.other_organization = Organization.objects.create(name="Other Payer Clinic", slug="other-payer-clinic")
        self.other_biller = User.objects.create_user(
            username="other-payer-biller", password="safe-test-password", organization=self.other_organization, role=User.Role.BILLER,
        )

    def test_biller_can_create_a_payer(self):
        self.client.force_login(self.biller)
        response = self.client.post(
            reverse("api-payers"),
            data=json.dumps({"name": "Blue Shield", "electronicPayerId": "BS001", "timelyFilingDays": 120, "authorizationRequired": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        payer = response.json()["payer"]
        self.assertEqual(payer["name"], "Blue Shield")
        self.assertEqual(payer["timelyFilingDays"], 120)
        self.assertTrue(payer["authorizationRequired"])

    def test_payer_name_is_required(self):
        self.client.force_login(self.biller)
        response = self.client.post(reverse("api-payers"), data=json.dumps({}), content_type="application/json")
        self.assertEqual(response.status_code, 422)
        self.assertIn("name", response.json()["errors"])

    def test_scheduler_can_list_payers_but_not_create_one(self):
        Payer.objects.create(organization=self.organization, name="Aetna")
        self.client.force_login(self.scheduler)
        list_response = self.client.get(reverse("api-payers"))
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()["payers"]), 1)
        create_response = self.client.post(
            reverse("api-payers"), data=json.dumps({"name": "Cigna"}), content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 403)

    def test_therapist_cannot_access_payer_directory(self):
        self.client.force_login(self.therapist)
        response = self.client.get(reverse("api-payers"))
        self.assertEqual(response.status_code, 403)

    def test_payer_directory_is_tenant_isolated(self):
        Payer.objects.create(organization=self.organization, name="In-Org Payer")
        Payer.objects.create(organization=self.other_organization, name="Other-Org Payer")
        self.client.force_login(self.biller)
        response = self.client.get(reverse("api-payers"))
        names = {row["name"] for row in response.json()["payers"]}
        self.assertEqual(names, {"In-Org Payer"})

    def test_biller_cannot_update_another_orgs_payer(self):
        other_payer = Payer.objects.create(organization=self.other_organization, name="Not Yours")
        self.client.force_login(self.biller)
        response = self.client.patch(
            reverse("api-payer-detail", kwargs={"payer_id": other_payer.pk}),
            data=json.dumps({"name": "Hijacked"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_payer_can_be_deactivated_and_not_twice(self):
        payer = Payer.objects.create(organization=self.organization, name="Medicare")
        self.client.force_login(self.biller)
        response = self.client.delete(reverse("api-payer-detail", kwargs={"payer_id": payer.pk}))
        self.assertEqual(response.status_code, 200)
        payer.refresh_from_db()
        self.assertFalse(payer.is_active)
        second_response = self.client.delete(reverse("api-payer-detail", kwargs={"payer_id": payer.pk}))
        self.assertEqual(second_response.status_code, 409)

    def test_payer_create_blocked_without_billing_feature(self):
        plan = SubscriptionPlan.objects.create(code="no-billing-plan", name="No Billing Plan", provider_seat_limit=5)
        other_feature = Feature.objects.create(code="crm", name="CRM")
        plan.features.add(other_feature)
        subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=plan, status=OrganizationSubscription.Status.ACTIVE,
        )
        subscription.features.add(other_feature)
        self.client.force_login(self.biller)
        response = self.client.post(reverse("api-payers"), data=json.dumps({"name": "Aetna"}), content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_payer_directory_records_audit_events(self):
        self.client.force_login(self.biller)
        self.client.post(reverse("api-payers"), data=json.dumps({"name": "United"}), content_type="application/json")
        self.assertTrue(AuditEvent.objects.filter(action="payer.created", organization=self.organization).exists())


class PatientInsuranceTests(TestCase):
    """Billing/RCM Phase 1: patient insurance policies — member ID, group
    number, subscriber, coverage percentages, effective/termination dates,
    and card images. Policies are terminated, never hard-deleted."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Insurance Clinic", slug="insurance-clinic")
        self.biller = User.objects.create_user(
            username="insurance-biller", password="safe-test-password", organization=self.organization, role=User.Role.BILLER,
        )
        self.scheduler = User.objects.create_user(
            username="insurance-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER,
        )
        self.therapist = User.objects.create_user(
            username="insurance-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Ida", last_name="Insured", date_of_birth="1990-01-01",
            assigned_therapist=self.therapist,
        )
        self.payer = Payer.objects.create(organization=self.organization, name="Blue Cross")

        self.other_organization = Organization.objects.create(name="Other Insurance Clinic", slug="other-insurance-clinic")
        self.other_biller = User.objects.create_user(
            username="other-insurance-biller", password="safe-test-password", organization=self.other_organization, role=User.Role.BILLER,
        )
        self.other_patient = Patient.objects.create(
            organization=self.other_organization, first_name="Not", last_name="Yours", date_of_birth="1990-01-01",
        )
        self.other_payer = Payer.objects.create(organization=self.other_organization, name="Other Payer")

    def _create_policy(self, **overrides):
        body = {
            "payerId": str(self.payer.pk), "memberId": "MBR12345", "effectiveDate": "2026-01-01",
            "copay": "25.00", "coinsurancePercent": "20", "rank": "primary",
        }
        body.update(overrides)
        self.client.force_login(self.biller)
        return self.client.post(
            reverse("api-patient-insurance", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps(body), content_type="application/json",
        )

    def test_biller_can_create_an_insurance_policy(self):
        response = self._create_policy()
        self.assertEqual(response.status_code, 201)
        policy = response.json()["policy"]
        self.assertEqual(policy["payerName"], "Blue Cross")
        self.assertEqual(policy["memberId"], "MBR12345")
        self.assertEqual(policy["copay"], "25.00")
        self.assertTrue(policy["isActive"])

    def test_missing_required_fields_are_rejected(self):
        response = self._create_policy(payerId="", memberId="", effectiveDate="")
        self.assertEqual(response.status_code, 422)
        errors = response.json()["errors"]
        self.assertIn("payerId", errors)
        self.assertIn("memberId", errors)
        self.assertIn("effectiveDate", errors)

    def test_coinsurance_out_of_range_is_rejected(self):
        response = self._create_policy(coinsurancePercent="150")
        self.assertEqual(response.status_code, 422)

    def test_termination_before_effective_date_is_rejected(self):
        response = self._create_policy(effectiveDate="2026-06-01", terminationDate="2026-01-01")
        self.assertEqual(response.status_code, 422)

    def test_payer_from_another_org_is_rejected(self):
        response = self._create_policy(payerId=str(self.other_payer.pk))
        self.assertEqual(response.status_code, 422)
        self.assertIn("payerId", response.json()["errors"])

    def test_scheduler_can_view_but_not_create_insurance(self):
        self._create_policy()
        self.client.force_login(self.scheduler)
        list_response = self.client.get(reverse("api-patient-insurance", kwargs={"patient_id": self.patient.pk}))
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()["policies"]), 1)
        create_response = self.client.post(
            reverse("api-patient-insurance", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"payerId": str(self.payer.pk), "memberId": "X", "effectiveDate": "2026-01-01"}),
            content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 403)

    def test_therapist_cannot_access_patient_insurance(self):
        self.client.force_login(self.therapist)
        response = self.client.get(reverse("api-patient-insurance", kwargs={"patient_id": self.patient.pk}))
        self.assertEqual(response.status_code, 403)

    def test_biller_cannot_view_another_orgs_patient_insurance(self):
        self.client.force_login(self.other_biller)
        response = self.client.get(reverse("api-patient-insurance", kwargs={"patient_id": self.patient.pk}))
        self.assertEqual(response.status_code, 403)

    def test_deleting_a_policy_terminates_it_instead_of_deleting_the_row(self):
        create_response = self._create_policy()
        policy_id = create_response.json()["policy"]["id"]
        self.client.force_login(self.biller)
        response = self.client.delete(
            reverse("api-patient-insurance-detail", kwargs={"patient_id": self.patient.pk, "policy_id": policy_id})
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(PatientInsurance.objects.filter(pk=policy_id).exists())
        policy = PatientInsurance.objects.get(pk=policy_id)
        self.assertEqual(policy.termination_date, timezone.localdate())
        self.assertFalse(policy.is_active)
        second_response = self.client.delete(
            reverse("api-patient-insurance-detail", kwargs={"patient_id": self.patient.pk, "policy_id": policy_id})
        )
        self.assertEqual(second_response.status_code, 409)

    def test_partial_update_only_touches_provided_fields(self):
        create_response = self._create_policy()
        policy_id = create_response.json()["policy"]["id"]
        self.client.force_login(self.biller)
        response = self.client.patch(
            reverse("api-patient-insurance-detail", kwargs={"patient_id": self.patient.pk, "policy_id": policy_id}),
            data=json.dumps({"groupNumber": "GRP-99"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        updated = response.json()["policy"]
        self.assertEqual(updated["groupNumber"], "GRP-99")
        self.assertEqual(updated["memberId"], "MBR12345")  # untouched

    def test_insurance_create_blocked_without_billing_feature(self):
        plan = SubscriptionPlan.objects.create(code="no-billing-plan-2", name="No Billing Plan", provider_seat_limit=5)
        other_feature = Feature.objects.create(code="crm", name="CRM")
        plan.features.add(other_feature)
        subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=plan, status=OrganizationSubscription.Status.ACTIVE,
        )
        subscription.features.add(other_feature)
        response = self._create_policy()
        self.assertEqual(response.status_code, 403)

    def test_card_upload_and_download_round_trip(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        create_response = self._create_policy()
        policy_id = create_response.json()["policy"]["id"]
        self.client.force_login(self.biller)
        image = SimpleUploadedFile("card.png", b"\x89PNG\r\n\x1a\n" + b"0" * 100, content_type="image/png")
        upload_response = self.client.post(
            reverse("api-patient-insurance-card-upload", kwargs={"patient_id": self.patient.pk, "policy_id": policy_id, "side": "front"}),
            data={"file": image},
        )
        self.assertEqual(upload_response.status_code, 201)
        self.assertTrue(upload_response.json()["policy"]["hasCardFront"])

        download_response = self.client.get(
            reverse("api-patient-insurance-card-download", kwargs={"patient_id": self.patient.pk, "policy_id": policy_id, "side": "front"})
        )
        self.assertEqual(download_response.status_code, 200)

    def test_card_upload_rejects_disallowed_file_type(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        create_response = self._create_policy()
        policy_id = create_response.json()["policy"]["id"]
        self.client.force_login(self.biller)
        bad_file = SimpleUploadedFile("card.exe", b"not-an-image", content_type="application/octet-stream")
        response = self.client.post(
            reverse("api-patient-insurance-card-upload", kwargs={"patient_id": self.patient.pk, "policy_id": policy_id, "side": "front"}),
            data={"file": bad_file},
        )
        self.assertEqual(response.status_code, 422)

    def test_insurance_policy_records_audit_events(self):
        self._create_policy()
        self.assertTrue(
            AuditEvent.objects.filter(action="patient_insurance.created", patient=self.patient).exists()
        )


class DiagnosisCodeLookupTests(TestCase):
    """DiagnosisCode is shared, platform-wide reference data (like Feature) —
    read-only, seeded via seed_diagnosis_codes, open to any org member."""

    def setUp(self):
        self.organization = Organization.objects.create(name="ICD Clinic", slug="icd-clinic")
        self.scheduler = User.objects.create_user(
            username="icd-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER,
        )
        DiagnosisCode.objects.create(code="M54.50", description="Low back pain, unspecified")
        DiagnosisCode.objects.create(code="M25.561", description="Pain in right knee")

    def test_search_matches_code_prefix(self):
        self.client.force_login(self.scheduler)
        response = self.client.get(reverse("api-diagnosis-codes"), {"q": "M54"})
        self.assertEqual(response.status_code, 200)
        codes = {row["code"] for row in response.json()["diagnosisCodes"]}
        self.assertEqual(codes, {"M54.50"})

    def test_search_matches_description(self):
        self.client.force_login(self.scheduler)
        response = self.client.get(reverse("api-diagnosis-codes"), {"q": "knee"})
        codes = {row["code"] for row in response.json()["diagnosisCodes"]}
        self.assertEqual(codes, {"M25.561"})

    def test_unauthenticated_request_is_rejected(self):
        response = self.client.get(reverse("api-diagnosis-codes"))
        self.assertEqual(response.status_code, 401)


class ChargeEntryTests(TestCase):
    """Billing/RCM Phase 2: charge entry with server-computed 8-minute-rule
    recommendations. `recommended_units` is always derived from the linked
    note's documented timed minutes — never client-supplied — and a
    mismatch against entered units requires an explicit override reason."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Charge Clinic", slug="charge-clinic")
        self.biller = User.objects.create_user(
            username="charge-biller", password="safe-test-password", organization=self.organization, role=User.Role.BILLER,
        )
        self.scheduler = User.objects.create_user(
            username="charge-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER,
        )
        self.therapist = User.objects.create_user(
            username="charge-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        self.location = Location.objects.create(organization=self.organization, name="Main Clinic")
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Cara", last_name="Charge", date_of_birth="1990-01-01",
            assigned_therapist=self.therapist,
        )
        self.signed_note = ClinicalNote.objects.create(
            patient=self.patient, therapist=self.therapist, note_type=ClinicalNote.Type.DAILY,
            status=ClinicalNote.Status.SIGNED, assessment="Improved tolerance.",
            signature_name="Therapist", signed_at="2026-01-02T12:00:00Z", finalization_attestation=True,
        )
        NoteIntervention.objects.create(
            note=self.signed_note, description="Therapeutic exercise", minutes=25, is_timed=True,
            category=NoteIntervention.Category.THERAPEUTIC_EXERCISE, order=0,
        )
        self.draft_note = ClinicalNote.objects.create(
            patient=self.patient, therapist=self.therapist, note_type=ClinicalNote.Type.DAILY,
        )
        self.diagnosis = DiagnosisCode.objects.create(code="M54.50", description="Low back pain, unspecified")

        self.other_organization = Organization.objects.create(name="Other Charge Clinic", slug="other-charge-clinic")
        self.other_biller = User.objects.create_user(
            username="other-charge-biller", password="safe-test-password", organization=self.other_organization, role=User.Role.BILLER,
        )

    def _create_charge(self, **overrides):
        body = {
            "serviceDate": "2026-01-02", "providerId": str(self.therapist.pk), "locationId": str(self.location.pk),
            "cptCode": "97110", "units": 1, "chargeAmount": "80.00",
        }
        body.update(overrides)
        self.client.force_login(self.biller)
        return self.client.post(
            reverse("api-patient-charges", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps(body), content_type="application/json",
        )

    def test_biller_can_create_a_manual_charge(self):
        response = self._create_charge(diagnosisCodeIds=[str(self.diagnosis.pk)])
        self.assertEqual(response.status_code, 201)
        charge = response.json()["charge"]
        self.assertEqual(charge["cptCode"], "97110")
        self.assertEqual(charge["status"], "draft")
        self.assertEqual(len(charge["diagnosisCodes"]), 1)
        self.assertIsNone(charge["recommendedUnits"])  # no note linked

    def test_cpt_code_is_uppercased_and_validated(self):
        response = self._create_charge(cptCode="g0283")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["charge"]["cptCode"], "G0283")

    def test_invalid_cpt_code_format_is_rejected(self):
        response = self._create_charge(cptCode="bad")
        self.assertEqual(response.status_code, 422)

    def test_missing_required_fields_are_rejected(self):
        response = self._create_charge(serviceDate="", providerId="", chargeAmount="")
        self.assertEqual(response.status_code, 422)
        errors = response.json()["errors"]
        self.assertIn("serviceDate", errors)
        self.assertIn("providerId", errors)
        self.assertIn("chargeAmount", errors)

    def test_duplicate_charge_is_rejected(self):
        first = self._create_charge()
        self.assertEqual(first.status_code, 201)
        second = self._create_charge()
        self.assertEqual(second.status_code, 409)

    def test_linking_an_unsigned_note_is_rejected(self):
        response = self._create_charge(noteId=str(self.draft_note.pk))
        self.assertEqual(response.status_code, 422)
        self.assertIn("noteId", response.json()["errors"])

    def test_linking_a_signed_note_computes_recommended_units_and_minutes(self):
        response = self._create_charge(noteId=str(self.signed_note.pk), units=2)
        self.assertEqual(response.status_code, 201)
        charge = response.json()["charge"]
        self.assertEqual(charge["recommendedUnits"], 2)  # 25 min -> 2 units (8-minute rule)
        self.assertEqual(charge["minutes"], 25)
        self.assertEqual(charge["unitsDifference"], 0)
        self.assertEqual(charge["noteId"], str(self.signed_note.pk))

    def test_units_mismatch_without_reason_is_rejected_with_recommendation_shown(self):
        response = self._create_charge(noteId=str(self.signed_note.pk), units=5)
        self.assertEqual(response.status_code, 422)
        message = response.json()["errors"]["unitsOverrideReason"]
        self.assertIn("Recommended 2", message)
        self.assertIn("entered 5", message)
        self.assertIn("+3", message)

    def test_units_mismatch_with_reason_is_accepted(self):
        response = self._create_charge(
            noteId=str(self.signed_note.pk), units=5, unitsOverrideReason="Payer requires billing full session length.",
        )
        self.assertEqual(response.status_code, 201)
        charge = response.json()["charge"]
        self.assertEqual(charge["units"], 5)
        self.assertEqual(charge["unitsOverrideReason"], "Payer requires billing full session length.")

    def test_scheduler_can_view_but_not_create_charges(self):
        self._create_charge()
        self.client.force_login(self.scheduler)
        list_response = self.client.get(reverse("api-patient-charges", kwargs={"patient_id": self.patient.pk}))
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()["charges"]), 1)
        create_response = self.client.post(
            reverse("api-patient-charges", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({
                "serviceDate": "2026-01-02", "providerId": str(self.therapist.pk), "cptCode": "97140",
                "units": 1, "chargeAmount": "50.00",
            }),
            content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 403)

    def test_therapist_cannot_create_charges(self):
        response = self._create_charge()
        self.client.force_login(self.therapist)
        create_response = self.client.post(
            reverse("api-patient-charges", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({
                "serviceDate": "2026-01-02", "providerId": str(self.therapist.pk), "cptCode": "97112",
                "units": 1, "chargeAmount": "50.00",
            }),
            content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 403)

    def test_biller_cannot_access_another_orgs_charges(self):
        self._create_charge()
        self.client.force_login(self.other_biller)
        response = self.client.get(reverse("api-patient-charges", kwargs={"patient_id": self.patient.pk}))
        self.assertEqual(response.status_code, 403)

    def test_ready_status_charge_remains_editable(self):
        create_response = self._create_charge()
        charge_id = create_response.json()["charge"]["id"]
        self.client.force_login(self.biller)
        response = self.client.patch(
            reverse("api-patient-charge-detail", kwargs={"patient_id": self.patient.pk, "charge_id": charge_id}),
            data=json.dumps({"status": "ready", "chargeAmount": "95.00"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()["charge"]
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["chargeAmount"], "95.00")

    def test_billed_charge_is_locked_except_for_voiding(self):
        create_response = self._create_charge()
        charge_id = create_response.json()["charge"]["id"]
        charge = Charge.objects.get(pk=charge_id)
        charge.status = Charge.Status.BILLED
        charge.save(update_fields=["status"])

        self.client.force_login(self.biller)
        blocked = self.client.patch(
            reverse("api-patient-charge-detail", kwargs={"patient_id": self.patient.pk, "charge_id": charge_id}),
            data=json.dumps({"chargeAmount": "999.00"}),
            content_type="application/json",
        )
        self.assertEqual(blocked.status_code, 409)

        voided = self.client.patch(
            reverse("api-patient-charge-detail", kwargs={"patient_id": self.patient.pk, "charge_id": charge_id}),
            data=json.dumps({"status": "void"}),
            content_type="application/json",
        )
        self.assertEqual(voided.status_code, 200)
        self.assertEqual(voided.json()["charge"]["status"], "void")

    def test_voided_charge_no_longer_blocks_a_duplicate(self):
        create_response = self._create_charge()
        charge_id = create_response.json()["charge"]["id"]
        self.client.force_login(self.biller)
        self.client.patch(
            reverse("api-patient-charge-detail", kwargs={"patient_id": self.patient.pk, "charge_id": charge_id}),
            data=json.dumps({"status": "void"}),
            content_type="application/json",
        )
        second = self._create_charge()
        self.assertEqual(second.status_code, 201)

    def test_charge_create_blocked_without_billing_feature(self):
        plan = SubscriptionPlan.objects.create(code="no-billing-plan-3", name="No Billing Plan", provider_seat_limit=5)
        other_feature = Feature.objects.create(code="crm", name="CRM")
        plan.features.add(other_feature)
        subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=plan, status=OrganizationSubscription.Status.ACTIVE,
        )
        subscription.features.add(other_feature)
        response = self._create_charge()
        self.assertEqual(response.status_code, 403)

    def test_biller_can_fetch_staff_options_to_attribute_a_charge(self):
        self.client.force_login(self.biller)
        response = self.client.get(reverse("api-staff-options"))
        self.assertEqual(response.status_code, 200)
        names = {row["displayName"] for row in response.json()["staff"]}
        self.assertIn(self.therapist.get_full_name() or self.therapist.username, names)

    def test_biller_can_list_locations_but_not_create_one(self):
        self.client.force_login(self.biller)
        list_response = self.client.get(reverse("api-locations"))
        self.assertEqual(list_response.status_code, 200)
        names = {row["name"] for row in list_response.json()["locations"]}
        self.assertIn("Main Clinic", names)
        create_response = self.client.post(
            reverse("api-locations"), data=json.dumps({"name": "New Location"}), content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 403)

    def test_charge_lifecycle_records_audit_events(self):
        create_response = self._create_charge()
        charge_id = create_response.json()["charge"]["id"]
        self.client.force_login(self.biller)
        self.client.patch(
            reverse("api-patient-charge-detail", kwargs={"patient_id": self.patient.pk, "charge_id": charge_id}),
            data=json.dumps({"status": "void"}),
            content_type="application/json",
        )
        self.assertTrue(AuditEvent.objects.filter(action="charge.created", patient=self.patient).exists())


class ClaimLifecycleTests(TestCase):
    """Billing/RCM Phase 3: claim creation, the full CLAIM VALIDATION
    checklist, submission, post-submission status transitions, and the
    CMS-1500 normalized data builder. `billing_services.validate_claim` is
    exercised both through the API (golden path) and directly against a
    hand-built Charge (for checks Phase 2's own charge-entry guards make
    otherwise unreachable, e.g. unsigned documentation)."""

    def setUp(self):
        from care.billing_services import build_cms1500_data, validate_claim
        self.validate_claim = staticmethod(validate_claim)
        self.build_cms1500_data = staticmethod(build_cms1500_data)

        self.organization = Organization.objects.create(
            name="Claim Clinic", slug="claim-clinic", npi_number="1234567890", tax_id="99-8887777",
            address_line_1="1 Clinic Way", city="Raleigh", state="NC", zip_code="27601",
        )
        self.biller = User.objects.create_user(
            username="claim-biller", password="safe-test-password", organization=self.organization, role=User.Role.BILLER,
        )
        self.scheduler = User.objects.create_user(
            username="claim-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER,
        )
        self.therapist = User.objects.create_user(
            username="claim-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        UserLicense.objects.create(
            user=self.therapist, license_number="PT-500", issuing_state="NC", expires_at=date.today() + timedelta(days=200),
        )
        Provider.objects.create(
            organization=self.organization, user=self.therapist, first_name="Claim", last_name="Therapist",
            npi_number="1122334455",
        )
        self.claims_feature = Feature.objects.create(code="claims", name="Claims")
        self.billing_feature = Feature.objects.create(code="billing", name="Billing")
        plan = SubscriptionPlan.objects.create(code="enterprise-claims", name="Enterprise", provider_seat_limit=50)
        plan.features.add(self.claims_feature, self.billing_feature)
        subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=plan, status=OrganizationSubscription.Status.ACTIVE,
        )
        subscription.features.add(self.claims_feature, self.billing_feature)

        self.payer = Payer.objects.create(organization=self.organization, name="Blue Cross", timely_filing_days=90)
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Cora", last_name="Claimant", date_of_birth="1990-01-01",
            assigned_therapist=self.therapist, address="42 Elm St, Raleigh, NC",
        )
        self.patient.refresh_from_db()  # coerce date_of_birth to a real date object, not the raw string above
        self.policy = PatientInsurance.objects.create(
            organization=self.organization, patient=self.patient, payer=self.payer,
            member_id="MBR555", effective_date=date.today() - timedelta(days=365),
        )
        self.diagnosis = DiagnosisCode.objects.create(code="M54.50", description="Low back pain, unspecified")
        self.note = ClinicalNote.objects.create(
            patient=self.patient, therapist=self.therapist, note_type=ClinicalNote.Type.DAILY,
            status=ClinicalNote.Status.SIGNED, assessment="Tolerated treatment well.",
            signature_name="Therapist", signed_at=timezone.now(), finalization_attestation=True,
        )
        NoteIntervention.objects.create(
            note=self.note, description="Therex", minutes=25, is_timed=True,
            category=NoteIntervention.Category.THERAPEUTIC_EXERCISE, order=0,
        )
        self.charge = Charge.objects.create(
            organization=self.organization, patient=self.patient, provider=self.therapist, clinical_note=self.note,
            service_date=date.today(), cpt_code="97110", units=2, minutes=25, recommended_units=2,
            charge_amount="80.00", created_by=self.biller,
        )
        self.charge.diagnosis_codes.set([self.diagnosis])

        self.other_organization = Organization.objects.create(name="Other Claim Clinic", slug="other-claim-clinic")
        self.other_biller = User.objects.create_user(
            username="other-claim-biller", password="safe-test-password", organization=self.other_organization, role=User.Role.BILLER,
        )

    def _create_claim(self, **overrides):
        body = {"patientInsuranceId": str(self.policy.pk), "chargeIds": [str(self.charge.pk)]}
        body.update(overrides)
        self.client.force_login(self.biller)
        return self.client.post(
            reverse("api-patient-claims", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps(body), content_type="application/json",
        )

    # --- creation ----------------------------------------------------------

    def test_biller_can_create_a_claim_from_charges(self):
        response = self._create_claim()
        self.assertEqual(response.status_code, 201)
        claim = response.json()["claim"]
        self.assertEqual(claim["diagnosisCodeList"], ["M54.50"])
        self.assertEqual(claim["chargeIds"], [str(self.charge.pk)])
        self.assertEqual(claim["status"], "draft")
        self.charge.refresh_from_db()
        self.assertEqual(str(self.charge.claim_id), claim["id"])

    def test_create_claim_requires_a_valid_insurance_policy(self):
        response = self._create_claim(patientInsuranceId="")
        self.assertEqual(response.status_code, 422)
        self.assertIn("patientInsuranceId", response.json()["errors"])

    def test_create_claim_requires_at_least_one_charge(self):
        response = self._create_claim(chargeIds=[])
        self.assertEqual(response.status_code, 422)
        self.assertIn("chargeIds", response.json()["errors"])

    def test_create_claim_rejects_an_already_claimed_charge(self):
        self._create_claim()
        second_charge = Charge.objects.create(
            organization=self.organization, patient=self.patient, provider=self.therapist,
            service_date=date(2026, 1, 3), cpt_code="97140", units=1, charge_amount="50.00",
        )
        response = self._create_claim(chargeIds=[str(self.charge.pk), str(second_charge.pk)])
        self.assertEqual(response.status_code, 409)

    def test_create_claim_rejects_more_than_twelve_diagnosis_codes(self):
        codes = [DiagnosisCode.objects.create(code="M99.0%s" % i, description="Test code %s" % i) for i in range(13)]
        self.charge.diagnosis_codes.set(codes)
        response = self._create_claim()
        self.assertEqual(response.status_code, 422)
        self.assertIn("chargeIds", response.json()["errors"])

    def test_scheduler_can_view_but_not_create_claims(self):
        create_response = self._create_claim()
        claim_id = create_response.json()["claim"]["id"]
        self.client.force_login(self.scheduler)
        list_response = self.client.get(reverse("api-patient-claims", kwargs={"patient_id": self.patient.pk}))
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()["claims"]), 1)
        detail_response = self.client.get(
            reverse("api-patient-claim-detail", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id})
        )
        self.assertEqual(detail_response.status_code, 200)
        blocked = self.client.post(
            reverse("api-claim-validate", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id}),
        )
        self.assertEqual(blocked.status_code, 403)

    def test_biller_cannot_access_another_orgs_claims(self):
        self._create_claim()
        self.client.force_login(self.other_biller)
        response = self.client.get(reverse("api-patient-claims", kwargs={"patient_id": self.patient.pk}))
        self.assertEqual(response.status_code, 403)

    def test_claim_actions_blocked_without_claims_feature(self):
        self.claims_feature.delete()
        response = self._create_claim()
        self.assertEqual(response.status_code, 403)

    # --- validation ----------------------------------------------------

    def test_validate_clean_claim_becomes_ready_with_no_errors(self):
        create_response = self._create_claim()
        claim_id = create_response.json()["claim"]["id"]
        self.client.force_login(self.biller)
        response = self.client.post(
            reverse("api-claim-validate", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id})
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["claim"]["status"], "ready")
        self.assertEqual([f for f in body["findings"] if f["severity"] == "error"], [])

    def test_validate_flags_missing_diagnosis(self):
        self.charge.diagnosis_codes.clear()
        create_response = self._create_claim()
        claim_id = create_response.json()["claim"]["id"]
        self.client.force_login(self.biller)
        response = self.client.post(
            reverse("api-claim-validate", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id})
        )
        codes = {f["code"] for f in response.json()["findings"]}
        self.assertIn("missing_diagnosis", codes)
        self.assertEqual(response.json()["claim"]["status"], "validation_error")

    def test_validate_flags_missing_npi(self):
        Provider.objects.filter(user=self.therapist).delete()
        claim = Claim.objects.create(
            organization=self.organization, patient=self.patient, patient_insurance=self.policy, payer=self.payer,
            diagnosis_code_list=["M54.50"],
        )
        self.charge.claim = claim
        self.charge.save(update_fields=["claim"])
        findings = self.validate_claim(claim)
        self.assertTrue(any(f["code"] == "missing_npi" for f in findings))

    def test_validate_flags_expired_credential(self):
        UserLicense.objects.filter(user=self.therapist).update(expires_at=date.today() - timedelta(days=10))
        claim = Claim.objects.create(
            organization=self.organization, patient=self.patient, patient_insurance=self.policy, payer=self.payer,
            diagnosis_code_list=["M54.50"],
        )
        self.charge.claim = claim
        self.charge.save(update_fields=["claim"])
        findings = self.validate_claim(claim)
        self.assertTrue(any(f["code"] == "credential_issue" for f in findings))

    def test_validate_flags_inactive_payer_and_insurance(self):
        self.payer.is_active = False
        self.payer.save()
        self.policy.termination_date = date.today() - timedelta(days=1)
        self.policy.save()
        claim = Claim.objects.create(
            organization=self.organization, patient=self.patient, patient_insurance=self.policy, payer=self.payer,
            diagnosis_code_list=["M54.50"],
        )
        findings = self.validate_claim(claim)
        codes = {f["code"] for f in findings}
        self.assertIn("inactive_payer", codes)
        self.assertIn("inactive_insurance", codes)

    def test_validate_flags_future_service_date(self):
        self.charge.service_date = date.today() + timedelta(days=5)
        self.charge.save(update_fields=["service_date"])
        claim = Claim.objects.create(
            organization=self.organization, patient=self.patient, patient_insurance=self.policy, payer=self.payer,
            diagnosis_code_list=["M54.50"],
        )
        self.charge.claim = claim
        self.charge.save(update_fields=["claim"])
        findings = self.validate_claim(claim)
        self.assertTrue(any(f["code"] == "future_service_date" for f in findings))

    def test_validate_flags_timely_filing_exceeded(self):
        self.payer.timely_filing_days = 30
        self.payer.save()
        self.charge.service_date = date.today() - timedelta(days=200)
        self.charge.save(update_fields=["service_date"])
        claim = Claim.objects.create(
            organization=self.organization, patient=self.patient, patient_insurance=self.policy, payer=self.payer,
            diagnosis_code_list=["M54.50"],
        )
        self.charge.claim = claim
        self.charge.save(update_fields=["claim"])
        findings = self.validate_claim(claim)
        self.assertTrue(any(f["code"] == "timely_filing" for f in findings))

    def test_validate_flags_unsigned_documentation(self):
        draft_note = ClinicalNote.objects.create(patient=self.patient, therapist=self.therapist, note_type=ClinicalNote.Type.DAILY)
        self.charge.clinical_note = draft_note
        self.charge.save(update_fields=["clinical_note"])
        claim = Claim.objects.create(
            organization=self.organization, patient=self.patient, patient_insurance=self.policy, payer=self.payer,
            diagnosis_code_list=["M54.50"],
        )
        self.charge.claim = claim
        self.charge.save(update_fields=["claim"])
        findings = self.validate_claim(claim)
        self.assertTrue(any(f["code"] == "unsigned_documentation" for f in findings))

    def test_validate_flags_missing_documentation_link_as_warning(self):
        self.charge.clinical_note = None
        self.charge.save(update_fields=["clinical_note"])
        claim = Claim.objects.create(
            organization=self.organization, patient=self.patient, patient_insurance=self.policy, payer=self.payer,
            diagnosis_code_list=["M54.50"],
        )
        self.charge.claim = claim
        self.charge.save(update_fields=["claim"])
        finding = next(f for f in self.validate_claim(claim) if f["code"] == "no_documentation_link")
        self.assertEqual(finding["severity"], "warning")

    def test_validate_flags_missing_and_exhausted_authorization(self):
        self.payer.authorization_required = True
        self.payer.save()
        claim = Claim.objects.create(
            organization=self.organization, patient=self.patient, patient_insurance=self.policy, payer=self.payer,
            diagnosis_code_list=["M54.50"],
        )
        self.charge.claim = claim
        self.charge.save(update_fields=["claim"])
        findings = self.validate_claim(claim)
        self.assertTrue(any(f["code"] == "missing_authorization" for f in findings))

        Authorization.objects.create(
            organization=self.organization, patient=self.patient, status=Authorization.Status.ACTIVE,
            visits_approved=1, visits_used=1, start_date=date.today() - timedelta(days=30), expires_at=date.today() + timedelta(days=30),
        )
        findings = self.validate_claim(claim)
        self.assertTrue(any(f["code"] == "exhausted_authorization" for f in findings))

    def test_validate_flags_duplicate_claim(self):
        first_response = self._create_claim()
        first_claim_id = first_response.json()["claim"]["id"]
        second_charge = Charge.objects.create(
            organization=self.organization, patient=self.patient, provider=self.therapist,
            service_date=date.today(), cpt_code="97140", units=1, charge_amount="50.00",
        )
        second_response = self._create_claim(chargeIds=[str(second_charge.pk)])
        second_claim_id = second_response.json()["claim"]["id"]
        self.client.force_login(self.biller)
        response = self.client.post(
            reverse("api-claim-validate", kwargs={"patient_id": self.patient.pk, "claim_id": second_claim_id})
        )
        codes = {f["code"] for f in response.json()["findings"]}
        self.assertIn("duplicate_claim", codes)

    # --- submission and post-submission lifecycle ---------------------------

    def test_submit_requires_ready_status(self):
        create_response = self._create_claim()
        claim_id = create_response.json()["claim"]["id"]
        self.client.force_login(self.biller)
        response = self.client.post(
            reverse("api-claim-submit", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id})
        )
        self.assertEqual(response.status_code, 409)

    def test_submit_marks_charges_billed_and_records_submitted_at(self):
        create_response = self._create_claim()
        claim_id = create_response.json()["claim"]["id"]
        self.client.force_login(self.biller)
        self.client.post(reverse("api-claim-validate", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id}))
        response = self.client.post(reverse("api-claim-submit", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id}))
        self.assertEqual(response.status_code, 200)
        body = response.json()["claim"]
        self.assertEqual(body["status"], "submitted")
        self.assertIsNotNone(body["submittedAt"])
        self.charge.refresh_from_db()
        self.assertEqual(self.charge.status, Charge.Status.BILLED)

    def test_charge_is_locked_once_its_claim_leaves_draft(self):
        create_response = self._create_claim()
        claim_id = create_response.json()["claim"]["id"]
        self.client.force_login(self.biller)
        self.client.post(reverse("api-claim-validate", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id}))
        response = self.client.patch(
            reverse("api-patient-charge-detail", kwargs={"patient_id": self.patient.pk, "charge_id": self.charge.pk}),
            data=json.dumps({"chargeAmount": "999.00"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)

    def test_status_update_blocked_before_submission(self):
        create_response = self._create_claim()
        claim_id = create_response.json()["claim"]["id"]
        self.client.force_login(self.biller)
        response = self.client.post(
            reverse("api-claim-status-update", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id}),
            data=json.dumps({"status": "paid"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)

    def test_status_update_transitions_after_submission_and_sets_closed_at_for_paid(self):
        create_response = self._create_claim()
        claim_id = create_response.json()["claim"]["id"]
        self.client.force_login(self.biller)
        self.client.post(reverse("api-claim-validate", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id}))
        self.client.post(reverse("api-claim-submit", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id}))
        response = self.client.post(
            reverse("api-claim-status-update", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id}),
            data=json.dumps({"status": "paid"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()["claim"]
        self.assertEqual(body["status"], "paid")
        self.assertIsNotNone(body["closedAt"])

    def test_status_update_rejects_an_invalid_status(self):
        create_response = self._create_claim()
        claim_id = create_response.json()["claim"]["id"]
        self.client.force_login(self.biller)
        self.client.post(reverse("api-claim-validate", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id}))
        self.client.post(reverse("api-claim-submit", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id}))
        response = self.client.post(
            reverse("api-claim-status-update", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id}),
            data=json.dumps({"status": "not-a-real-status"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)

    # --- CMS-1500 normalized data --------------------------------------

    def test_cms1500_data_structure(self):
        claim = Claim.objects.create(
            organization=self.organization, patient=self.patient, patient_insurance=self.policy, payer=self.payer,
            diagnosis_code_list=["M54.50"],
        )
        self.charge.claim = claim
        self.charge.save(update_fields=["claim"])
        data = self.build_cms1500_data(claim)
        self.assertEqual(data["billingProvider"]["npi"], "1234567890")
        self.assertEqual(data["billingProvider"]["taxId"], "99-8887777")
        self.assertEqual(data["subscriber"]["memberId"], "MBR555")
        self.assertEqual(data["diagnoses"], [{"pointer": "A", "code": "M54.50"}])
        self.assertEqual(len(data["serviceLines"]), 1)
        line = data["serviceLines"][0]
        self.assertEqual(line["cptCode"], "97110")
        self.assertEqual(line["renderingProviderNpi"], "1122334455")
        self.assertEqual(line["diagnosisPointers"], ["A"])
        self.assertEqual(data["totalChargeAmount"], "80.00")

    def test_cms1500_endpoint_returns_the_same_structure(self):
        create_response = self._create_claim()
        claim_id = create_response.json()["claim"]["id"]
        self.client.force_login(self.biller)
        response = self.client.get(
            reverse("api-claim-cms1500", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id})
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cms1500"]["diagnoses"], [{"pointer": "A", "code": "M54.50"}])

    # --- audit trail -----------------------------------------------------

    def test_claim_lifecycle_records_audit_events(self):
        create_response = self._create_claim()
        claim_id = create_response.json()["claim"]["id"]
        self.client.force_login(self.biller)
        self.client.post(reverse("api-claim-validate", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id}))
        self.client.post(reverse("api-claim-submit", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id}))
        self.client.post(
            reverse("api-claim-status-update", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id}),
            data=json.dumps({"status": "paid"}), content_type="application/json",
        )
        actions = set(AuditEvent.objects.filter(patient=self.patient).values_list("action", flat=True))
        self.assertIn("claim.created", actions)
        self.assertIn("claim.validated", actions)
        self.assertIn("claim.submitted", actions)
        self.assertIn("claim.status_changed", actions)

    # --- clearinghouse adapter integration (Phase 4) ------------------------

    def test_submit_response_includes_the_clearinghouse_message(self):
        create_response = self._create_claim()
        claim_id = create_response.json()["claim"]["id"]
        self.client.force_login(self.biller)
        self.client.post(reverse("api-claim-validate", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id}))
        response = self.client.post(reverse("api-claim-submit", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id}))
        self.assertEqual(response.status_code, 200)
        self.assertIn("No clearinghouse is connected", response.json()["clearinghouseMessage"])

    def test_check_status_blocked_before_submission(self):
        create_response = self._create_claim()
        claim_id = create_response.json()["claim"]["id"]
        self.client.force_login(self.biller)
        response = self.client.post(
            reverse("api-claim-check-status", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id})
        )
        self.assertEqual(response.status_code, 409)

    def test_check_status_after_submission_echoes_tracked_status(self):
        create_response = self._create_claim()
        claim_id = create_response.json()["claim"]["id"]
        self.client.force_login(self.biller)
        self.client.post(reverse("api-claim-validate", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id}))
        self.client.post(reverse("api-claim-submit", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id}))
        response = self.client.post(
            reverse("api-claim-check-status", kwargs={"patient_id": self.patient.pk, "claim_id": claim_id})
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["clearinghouseStatus"], "submitted")
        self.assertTrue(AuditEvent.objects.filter(action="claim.status_checked", patient=self.patient).exists())

    def test_verify_eligibility_reports_unverified_and_records_audit_event(self):
        self.client.force_login(self.biller)
        response = self.client.post(
            reverse("api-patient-insurance-verify-eligibility", kwargs={"patient_id": self.patient.pk, "policy_id": self.policy.pk})
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["verified"])
        self.assertIn("No clearinghouse is connected", body["message"])
        self.assertTrue(
            AuditEvent.objects.filter(action="patient_insurance.eligibility_checked", patient=self.patient).exists()
        )

    def test_scheduler_cannot_verify_eligibility(self):
        self.client.force_login(self.scheduler)
        response = self.client.post(
            reverse("api-patient-insurance-verify-eligibility", kwargs={"patient_id": self.patient.pk, "policy_id": self.policy.pk})
        )
        self.assertEqual(response.status_code, 403)


class ManualClearinghouseAdapterTests(TestCase):
    """Billing/RCM Phase 4: the manual clearinghouse adapter must never
    fabricate a response from a service nothing is actually connected to."""

    def test_submit_claim_is_accepted_for_internal_tracking_only(self):
        from types import SimpleNamespace
        from care.clearinghouse import ManualClearinghouseAdapter

        result = ManualClearinghouseAdapter().submit_claim(SimpleNamespace(status="ready"))
        self.assertTrue(result.accepted)
        self.assertEqual(result.clearinghouse_claim_id, "")
        self.assertIn("No clearinghouse is connected", result.message)

    def test_check_claim_status_echoes_the_tracked_status(self):
        from types import SimpleNamespace
        from care.clearinghouse import ManualClearinghouseAdapter

        result = ManualClearinghouseAdapter().check_claim_status(SimpleNamespace(status="submitted"))
        self.assertEqual(result.status, "submitted")

    def test_fetch_era_reports_unavailable(self):
        from care.clearinghouse import ManualClearinghouseAdapter

        result = ManualClearinghouseAdapter().fetch_era("some-reference")
        self.assertFalse(result.available)
        self.assertEqual(result.reference, "some-reference")

    def test_verify_eligibility_reports_unverified(self):
        from types import SimpleNamespace
        from care.clearinghouse import ManualClearinghouseAdapter

        result = ManualClearinghouseAdapter().verify_eligibility(SimpleNamespace())
        self.assertFalse(result.verified)

    def test_get_clearinghouse_adapter_returns_the_manual_adapter(self):
        from care.clearinghouse import ManualClearinghouseAdapter, get_clearinghouse_adapter

        self.assertIsInstance(get_clearinghouse_adapter(organization=None), ManualClearinghouseAdapter)


class PaymentPostingAndArAgingTests(TestCase):
    """Billing/RCM Phase 5: payment posting (insurance/patient payment,
    adjustment, write-off, refund, transfer), the manual ERA/EOB workflow
    (unmatched transactions + later matching), and the AR aging dashboard.
    Claim.total_paid/total_adjusted/balance are computed live from
    ClaimTransaction rows — never stored — so these tests exercise the
    computation through real posted transactions, not stubbed totals."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Payment Clinic", slug="payment-clinic")
        self.biller = User.objects.create_user(
            username="payment-biller", password="safe-test-password", organization=self.organization, role=User.Role.BILLER,
        )
        self.scheduler = User.objects.create_user(
            username="payment-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER,
        )
        self.therapist = User.objects.create_user(
            username="payment-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        self.location = Location.objects.create(organization=self.organization, name="Payment Location")

        billing_feature = Feature.objects.create(code="billing", name="Billing")
        claims_feature = Feature.objects.create(code="claims", name="Claims")
        plan = SubscriptionPlan.objects.create(code="payment-enterprise", name="Enterprise", provider_seat_limit=50)
        plan.features.add(billing_feature, claims_feature)
        subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=plan, status=OrganizationSubscription.Status.ACTIVE,
        )
        subscription.features.add(billing_feature, claims_feature)

        self.payer = Payer.objects.create(organization=self.organization, name="Payment Payer", timely_filing_days=365)
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Pat", last_name="Payment", date_of_birth="1990-01-01",
            assigned_therapist=self.therapist, address="1 Payment Way",
        )
        self.policy = PatientInsurance.objects.create(
            organization=self.organization, patient=self.patient, payer=self.payer,
            member_id="MBR-PAY-1", effective_date=date.today() - timedelta(days=365),
        )

        self.other_organization = Organization.objects.create(name="Other Payment Clinic", slug="other-payment-clinic")
        self.other_biller = User.objects.create_user(
            username="other-payment-biller", password="safe-test-password", organization=self.other_organization, role=User.Role.BILLER,
        )

    def _make_submitted_claim(self, *, amount="100.00", service_date=None, status=Claim.Status.SUBMITTED):
        service_date = service_date or date.today()
        charge = Charge.objects.create(
            organization=self.organization, patient=self.patient, provider=self.therapist, location=self.location,
            service_date=service_date, cpt_code="97110", units=1, charge_amount=amount,
        )
        claim = Claim.objects.create(
            organization=self.organization, patient=self.patient, patient_insurance=self.policy, payer=self.payer,
            diagnosis_code_list=[], status=status,
        )
        charge.claim = claim
        charge.save(update_fields=["claim"])
        return claim

    def _post_transaction(self, **overrides):
        body = {"kind": "insurance_payment", "amount": "50.00", "method": "eft"}
        body.update(overrides)
        self.client.force_login(self.biller)
        return self.client.post(
            reverse("api-patient-transactions", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps(body), content_type="application/json",
        )

    # --- payment posting ----------------------------------------------

    def test_biller_can_post_an_insurance_payment(self):
        claim = self._make_submitted_claim()
        response = self._post_transaction(claimId=str(claim.pk), amount="60.00", reference="EFT-123")
        self.assertEqual(response.status_code, 201)
        body = response.json()["transaction"]
        self.assertEqual(body["kind"], "insurance_payment")
        self.assertTrue(body["isMatched"])
        claim.refresh_from_db()
        self.assertEqual(str(claim.total_paid), "60.00")
        self.assertEqual(str(claim.balance), "40.00")

    def test_posting_an_unmatched_transaction_is_allowed(self):
        response = self._post_transaction(amount="25.00")
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.json()["transaction"]["isMatched"])
        self.assertIsNone(response.json()["transaction"]["claimId"])

    def test_matching_an_unmatched_transaction_to_a_claim(self):
        claim = self._make_submitted_claim()
        create_response = self._post_transaction(amount="30.00")
        transaction_id = create_response.json()["transaction"]["id"]
        self.client.force_login(self.biller)
        response = self.client.post(
            reverse("api-transaction-match", kwargs={"patient_id": self.patient.pk, "transaction_id": transaction_id}),
            data=json.dumps({"claimId": str(claim.pk)}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["transaction"]["isMatched"])
        claim.refresh_from_db()
        self.assertEqual(str(claim.total_paid), "30.00")

    def test_write_off_and_adjustment_reduce_balance_without_counting_as_paid(self):
        claim = self._make_submitted_claim(amount="100.00")
        self._post_transaction(claimId=str(claim.pk), kind="adjustment", amount="20.00")
        self._post_transaction(claimId=str(claim.pk), kind="write_off", amount="10.00")
        claim.refresh_from_db()
        self.assertEqual(str(claim.total_paid), "0.00")
        self.assertEqual(str(claim.total_adjusted), "30.00")
        self.assertEqual(str(claim.balance), "70.00")

    def test_refund_reduces_total_paid(self):
        claim = self._make_submitted_claim(amount="100.00")
        self._post_transaction(claimId=str(claim.pk), kind="insurance_payment", amount="80.00")
        self._post_transaction(claimId=str(claim.pk), kind="refund", amount="20.00")
        claim.refresh_from_db()
        self.assertEqual(str(claim.total_paid), "60.00")
        self.assertEqual(str(claim.balance), "40.00")

    def test_transfer_requires_a_destination_claim(self):
        claim = self._make_submitted_claim()
        response = self._post_transaction(claimId=str(claim.pk), kind="transfer", amount="15.00")
        self.assertEqual(response.status_code, 422)
        self.assertIn("transferredToClaimId", response.json()["errors"])

    def test_transfer_to_a_secondary_claim(self):
        primary = self._make_submitted_claim(amount="100.00")
        secondary_policy = PatientInsurance.objects.create(
            organization=self.organization, patient=self.patient, payer=self.payer, rank=PatientInsurance.Rank.SECONDARY,
            member_id="MBR-PAY-2", effective_date=date.today() - timedelta(days=365),
        )
        secondary = Claim.objects.create(
            organization=self.organization, patient=self.patient, patient_insurance=secondary_policy, payer=self.payer,
            diagnosis_code_list=[], status=Claim.Status.SUBMITTED,
        )
        response = self._post_transaction(
            claimId=str(primary.pk), kind="transfer", amount="40.00", transferredToClaimId=str(secondary.pk),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["transaction"]["transferredToClaimId"], str(secondary.pk))

    def test_amount_must_be_positive(self):
        claim = self._make_submitted_claim()
        response = self._post_transaction(claimId=str(claim.pk), amount="0")
        self.assertEqual(response.status_code, 422)

    def test_scheduler_can_view_but_not_post_transactions(self):
        claim = self._make_submitted_claim()
        self._post_transaction(claimId=str(claim.pk), amount="10.00")
        self.client.force_login(self.scheduler)
        list_response = self.client.get(reverse("api-patient-transactions", kwargs={"patient_id": self.patient.pk}))
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()["transactions"]), 1)
        create_response = self.client.post(
            reverse("api-patient-transactions", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"kind": "patient_payment", "amount": "5.00"}), content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 403)

    def test_biller_cannot_post_transactions_for_another_orgs_patient(self):
        self.client.force_login(self.other_biller)
        response = self.client.post(
            reverse("api-patient-transactions", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"kind": "patient_payment", "amount": "5.00"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_transaction_posting_blocked_without_billing_feature(self):
        Feature.objects.filter(code="billing").delete()
        response = self._post_transaction(amount="10.00")
        self.assertEqual(response.status_code, 403)

    def test_transaction_records_audit_events(self):
        claim = self._make_submitted_claim()
        create_response = self._post_transaction(amount="10.00")
        transaction_id = create_response.json()["transaction"]["id"]
        self.client.force_login(self.biller)
        self.client.post(
            reverse("api-transaction-match", kwargs={"patient_id": self.patient.pk, "transaction_id": transaction_id}),
            data=json.dumps({"claimId": str(claim.pk)}), content_type="application/json",
        )
        self.assertTrue(AuditEvent.objects.filter(action="claim_transaction.created", patient=self.patient).exists())
        self.assertTrue(AuditEvent.objects.filter(action="claim_transaction.matched", patient=self.patient).exists())

    # --- AR aging dashboard ----------------------------------------------

    def test_ar_aging_buckets_outstanding_balance_by_service_date_age(self):
        recent = self._make_submitted_claim(amount="100.00", service_date=date.today() - timedelta(days=10))
        old = self._make_submitted_claim(amount="200.00", service_date=date.today() - timedelta(days=150))
        self.client.force_login(self.biller)
        response = self.client.get(reverse("api-ar-aging-report"))
        self.assertEqual(response.status_code, 200)
        buckets = response.json()["buckets"]
        self.assertEqual(buckets["0-30"], "100.00")
        self.assertEqual(buckets["120+"], "200.00")
        self.assertEqual(response.json()["totalOutstanding"], "300.00")
        claim_ids = {row["claimId"] for row in response.json()["claims"]}
        self.assertEqual(claim_ids, {str(recent.pk), str(old.pk)})

    def test_ar_aging_excludes_pre_submission_and_paid_off_claims(self):
        self._make_submitted_claim(amount="100.00", status=Claim.Status.DRAFT)
        fully_paid = self._make_submitted_claim(amount="50.00")
        self._post_transaction(claimId=str(fully_paid.pk), amount="50.00")
        self.client.force_login(self.biller)
        response = self.client.get(reverse("api-ar-aging-report"))
        self.assertEqual(response.json()["claims"], [])
        self.assertEqual(response.json()["totalOutstanding"], "0.00")

    def test_ar_aging_filters_by_payer_and_status(self):
        matching = self._make_submitted_claim(amount="100.00")
        other_payer = Payer.objects.create(organization=self.organization, name="Different Payer")
        other_policy = PatientInsurance.objects.create(
            organization=self.organization, patient=self.patient, payer=other_payer,
            member_id="MBR-OTHER", effective_date=date.today() - timedelta(days=365),
        )
        non_matching_charge = Charge.objects.create(
            organization=self.organization, patient=self.patient, provider=self.therapist,
            service_date=date.today(), cpt_code="97140", units=1, charge_amount="75.00",
        )
        non_matching = Claim.objects.create(
            organization=self.organization, patient=self.patient, patient_insurance=other_policy, payer=other_payer,
            diagnosis_code_list=[], status=Claim.Status.SUBMITTED,
        )
        non_matching_charge.claim = non_matching
        non_matching_charge.save(update_fields=["claim"])

        self.client.force_login(self.biller)
        response = self.client.get(reverse("api-ar-aging-report"), {"payerId": str(self.payer.pk)})
        claim_ids = {row["claimId"] for row in response.json()["claims"]}
        self.assertEqual(claim_ids, {str(matching.pk)})

    def test_scheduler_cannot_access_ar_aging_report(self):
        self.client.force_login(self.scheduler)
        response = self.client.get(reverse("api-ar-aging-report"))
        self.assertEqual(response.status_code, 403)

    def test_ar_aging_is_tenant_isolated(self):
        self._make_submitted_claim(amount="100.00")
        self.client.force_login(self.other_biller)
        response = self.client.get(reverse("api-ar-aging-report"))
        self.assertEqual(response.json()["claims"], [])


class DenialWorkQueueTests(TestCase):
    """Billing/RCM Phase 6: the denial work queue — denial code/reason,
    payer, claim, owner, due date, action notes, appeal status, and
    resolution, plus the org-wide filterable queue billing staff work from."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Denial Clinic", slug="denial-clinic")
        self.biller = User.objects.create_user(
            username="denial-biller", password="safe-test-password", organization=self.organization, role=User.Role.BILLER,
        )
        self.scheduler = User.objects.create_user(
            username="denial-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER,
        )
        self.therapist = User.objects.create_user(
            username="denial-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        billing_feature = Feature.objects.create(code="billing", name="Billing")
        claims_feature = Feature.objects.create(code="claims", name="Claims")
        plan = SubscriptionPlan.objects.create(code="denial-enterprise", name="Enterprise", provider_seat_limit=50)
        plan.features.add(billing_feature, claims_feature)
        subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=plan, status=OrganizationSubscription.Status.ACTIVE,
        )
        subscription.features.add(billing_feature, claims_feature)

        self.payer = Payer.objects.create(organization=self.organization, name="Denial Payer", timely_filing_days=365)
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Dana", last_name="Denial", date_of_birth="1990-01-01",
            assigned_therapist=self.therapist, address="1 Denial Way",
        )
        self.policy = PatientInsurance.objects.create(
            organization=self.organization, patient=self.patient, payer=self.payer,
            member_id="MBR-DEN-1", effective_date=date.today() - timedelta(days=365),
        )
        charge = Charge.objects.create(
            organization=self.organization, patient=self.patient, provider=self.therapist,
            service_date=date.today(), cpt_code="97110", units=1, charge_amount="100.00",
        )
        self.claim = Claim.objects.create(
            organization=self.organization, patient=self.patient, patient_insurance=self.policy, payer=self.payer,
            diagnosis_code_list=[], status=Claim.Status.DENIED,
        )
        charge.claim = self.claim
        charge.save(update_fields=["claim"])

        self.other_organization = Organization.objects.create(name="Other Denial Clinic", slug="other-denial-clinic")
        self.other_biller = User.objects.create_user(
            username="other-denial-biller", password="safe-test-password", organization=self.other_organization, role=User.Role.BILLER,
        )

    def _create_denial(self, **overrides):
        body = {"denialReason": "Missing prior authorization", "denialCode": "CO-197"}
        body.update(overrides)
        self.client.force_login(self.biller)
        return self.client.post(
            reverse("api-claim-denials", kwargs={"patient_id": self.patient.pk, "claim_id": self.claim.pk}),
            data=json.dumps(body), content_type="application/json",
        )

    def test_biller_can_create_a_denial(self):
        response = self._create_denial(dueDate=(date.today() + timedelta(days=14)).isoformat())
        self.assertEqual(response.status_code, 201)
        body = response.json()["denial"]
        self.assertEqual(body["denialReason"], "Missing prior authorization")
        self.assertEqual(body["resolution"], "open")
        self.assertFalse(body["isOverdue"])

    def test_denial_reason_is_required(self):
        response = self._create_denial(denialReason="")
        self.assertEqual(response.status_code, 422)
        self.assertIn("denialReason", response.json()["errors"])

    def test_overdue_computed_from_due_date_and_open_resolution(self):
        create_response = self._create_denial(dueDate=(date.today() - timedelta(days=5)).isoformat())
        self.assertTrue(create_response.json()["denial"]["isOverdue"])

    def test_resolving_a_denial_sets_resolved_at_and_clears_overdue(self):
        create_response = self._create_denial(dueDate=(date.today() - timedelta(days=5)).isoformat())
        denial_id = create_response.json()["denial"]["id"]
        self.client.force_login(self.biller)
        response = self.client.patch(
            reverse("api-denial-detail", kwargs={"patient_id": self.patient.pk, "denial_id": denial_id}),
            data=json.dumps({"resolution": "resolved_paid"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()["denial"]
        self.assertIsNotNone(body["resolvedAt"])
        self.assertFalse(body["isOverdue"])

    def test_assigning_an_owner(self):
        create_response = self._create_denial()
        denial_id = create_response.json()["denial"]["id"]
        self.client.force_login(self.biller)
        response = self.client.patch(
            reverse("api-denial-detail", kwargs={"patient_id": self.patient.pk, "denial_id": denial_id}),
            data=json.dumps({"ownerId": str(self.biller.pk), "appealStatus": "preparing"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()["denial"]
        self.assertEqual(body["ownerId"], str(self.biller.pk))
        self.assertEqual(body["appealStatus"], "preparing")

    def test_scheduler_can_view_but_not_create_denials(self):
        self._create_denial()
        self.client.force_login(self.scheduler)
        list_response = self.client.get(
            reverse("api-claim-denials", kwargs={"patient_id": self.patient.pk, "claim_id": self.claim.pk})
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()["denials"]), 1)
        create_response = self.client.post(
            reverse("api-claim-denials", kwargs={"patient_id": self.patient.pk, "claim_id": self.claim.pk}),
            data=json.dumps({"denialReason": "Blocked"}), content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 403)

    def test_denial_actions_blocked_without_claims_feature(self):
        Feature.objects.filter(code="claims").delete()
        response = self._create_denial()
        self.assertEqual(response.status_code, 403)

    def test_denial_records_audit_events(self):
        create_response = self._create_denial()
        denial_id = create_response.json()["denial"]["id"]
        self.client.force_login(self.biller)
        self.client.patch(
            reverse("api-denial-detail", kwargs={"patient_id": self.patient.pk, "denial_id": denial_id}),
            data=json.dumps({"resolution": "resolved_paid"}), content_type="application/json",
        )
        self.assertTrue(AuditEvent.objects.filter(action="claim_denial.created", patient=self.patient).exists())
        self.assertTrue(AuditEvent.objects.filter(action="claim_denial.updated", patient=self.patient).exists())

    def test_biller_cannot_access_another_orgs_denials(self):
        self._create_denial()
        self.client.force_login(self.other_biller)
        response = self.client.get(
            reverse("api-claim-denials", kwargs={"patient_id": self.patient.pk, "claim_id": self.claim.pk})
        )
        self.assertEqual(response.status_code, 403)

    # --- work queue ------------------------------------------------------

    def test_work_queue_filters_by_owner_and_resolution(self):
        first = self._create_denial(denialReason="First denial")
        first_id = first.json()["denial"]["id"]
        self._create_denial(denialReason="Second denial")
        self.client.force_login(self.biller)
        self.client.patch(
            reverse("api-denial-detail", kwargs={"patient_id": self.patient.pk, "denial_id": first_id}),
            data=json.dumps({"ownerId": str(self.biller.pk)}), content_type="application/json",
        )
        response = self.client.get(reverse("api-denial-work-queue"), {"ownerId": str(self.biller.pk)})
        self.assertEqual(response.status_code, 200)
        reasons = {row["denialReason"] for row in response.json()["denials"]}
        self.assertEqual(reasons, {"First denial"})

    def test_work_queue_overdue_filter(self):
        self._create_denial(denialReason="Overdue", dueDate=(date.today() - timedelta(days=3)).isoformat())
        self._create_denial(denialReason="Not overdue", dueDate=(date.today() + timedelta(days=30)).isoformat())
        self.client.force_login(self.biller)
        response = self.client.get(reverse("api-denial-work-queue"), {"overdue": "1"})
        reasons = {row["denialReason"] for row in response.json()["denials"]}
        self.assertEqual(reasons, {"Overdue"})

    def test_scheduler_cannot_access_the_org_wide_work_queue(self):
        self.client.force_login(self.scheduler)
        response = self.client.get(reverse("api-denial-work-queue"))
        self.assertEqual(response.status_code, 403)

    def test_work_queue_is_tenant_isolated(self):
        self._create_denial()
        self.client.force_login(self.other_biller)
        response = self.client.get(reverse("api-denial-work-queue"))
        self.assertEqual(response.json()["denials"], [])


class PatientStatementTests(TestCase):
    """Billing/RCM Phase 6: patient statements combining insurance-claim
    balance and cash-pay superbill balance, reproducible as of the
    statement's own statement_date."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Statement Clinic", slug="statement-clinic")
        self.biller = User.objects.create_user(
            username="statement-biller", password="safe-test-password", organization=self.organization, role=User.Role.BILLER,
        )
        self.scheduler = User.objects.create_user(
            username="statement-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER,
        )
        self.therapist = User.objects.create_user(
            username="statement-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        billing_feature = Feature.objects.create(code="billing", name="Billing")
        plan = SubscriptionPlan.objects.create(code="statement-plan", name="Statement Plan", provider_seat_limit=50)
        plan.features.add(billing_feature)
        subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=plan, status=OrganizationSubscription.Status.ACTIVE,
        )
        subscription.features.add(billing_feature)

        self.payer = Payer.objects.create(organization=self.organization, name="Statement Payer", timely_filing_days=365)
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Stan", last_name="Statement", date_of_birth="1990-01-01",
            assigned_therapist=self.therapist, address="1 Statement St",
        )
        self.policy = PatientInsurance.objects.create(
            organization=self.organization, patient=self.patient, payer=self.payer,
            member_id="MBR-STMT-1", effective_date=date.today() - timedelta(days=365),
        )
        charge = Charge.objects.create(
            organization=self.organization, patient=self.patient, provider=self.therapist,
            service_date=date.today() - timedelta(days=10), cpt_code="97110", units=1, charge_amount="100.00",
        )
        self.claim = Claim.objects.create(
            organization=self.organization, patient=self.patient, patient_insurance=self.policy, payer=self.payer,
            diagnosis_code_list=[], status=Claim.Status.SUBMITTED,
        )
        charge.claim = self.claim
        charge.save(update_fields=["claim"])
        ClaimTransaction.objects.create(
            organization=self.organization, patient=self.patient, claim=self.claim,
            kind=ClaimTransaction.Kind.INSURANCE_PAYMENT, amount="60.00", payment_date=date.today() - timedelta(days=5),
        )

        self.other_organization = Organization.objects.create(name="Other Statement Clinic", slug="other-statement-clinic")
        self.other_biller = User.objects.create_user(
            username="other-statement-biller", password="safe-test-password", organization=self.other_organization, role=User.Role.BILLER,
        )

    def _generate_statement(self, **overrides):
        body = {"dueDate": (date.today() + timedelta(days=30)).isoformat()}
        body.update(overrides)
        self.client.force_login(self.biller)
        return self.client.post(
            reverse("api-patient-statements", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps(body), content_type="application/json",
        )

    def test_generating_a_statement_computes_insurance_balance(self):
        response = self._generate_statement()
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["statement"]["balanceAtGeneration"], "40.00")
        self.assertEqual(body["data"]["totalBalance"], "40.00")
        self.assertEqual(len(body["data"]["insuranceClaims"]), 1)
        self.assertEqual(body["data"]["insuranceClaims"][0]["balance"], "40.00")

    def test_statement_includes_cash_pay_superbill_balance(self):
        superbill = Superbill.objects.create(
            patient=self.patient, clinician=self.therapist, service_date=date.today() - timedelta(days=2),
            codes=["97140"], amount="50.00",
        )
        PaymentRecord.objects.create(
            patient=self.patient, superbill=superbill, recorded_by=self.biller, amount="20.00",
            status=PaymentRecord.Status.RECEIVED, payment_processor_reference="tok_test",
        )
        response = self._generate_statement()
        body = response.json()["data"]
        self.assertEqual(len(body["cashCharges"]), 1)
        self.assertEqual(body["cashCharges"][0]["balance"], "30.00")
        self.assertEqual(body["totalBalance"], "70.00")  # 40.00 insurance + 30.00 cash

    def test_statement_is_reproducible_as_of_its_statement_date(self):
        early_response = self._generate_statement(statementDate=(date.today() - timedelta(days=8)).isoformat())
        # The $60 payment above was posted 5 days ago — after this earlier statement date — so it must not count yet.
        self.assertEqual(early_response.json()["data"]["totalBalance"], "100.00")

    def test_scheduler_can_view_but_not_generate_statements(self):
        create_response = self._generate_statement()
        statement_id = create_response.json()["statement"]["id"]
        self.client.force_login(self.scheduler)
        list_response = self.client.get(reverse("api-patient-statements", kwargs={"patient_id": self.patient.pk}))
        self.assertEqual(list_response.status_code, 200)
        detail_response = self.client.get(
            reverse("api-statement-detail", kwargs={"patient_id": self.patient.pk, "statement_id": statement_id})
        )
        self.assertEqual(detail_response.status_code, 200)
        blocked = self.client.post(
            reverse("api-patient-statements", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"dueDate": (date.today() + timedelta(days=30)).isoformat()}),
            content_type="application/json",
        )
        self.assertEqual(blocked.status_code, 403)

    def test_biller_cannot_generate_statements_for_another_orgs_patient(self):
        self.client.force_login(self.other_biller)
        response = self.client.post(
            reverse("api-patient-statements", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"dueDate": (date.today() + timedelta(days=30)).isoformat()}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_statement_generation_records_an_audit_event(self):
        self._generate_statement()
        self.assertTrue(AuditEvent.objects.filter(action="patient_statement.generated", patient=self.patient).exists())


class CashPayPricingTests(TestCase):
    """Billing/RCM Phase 6: cash-pay service price list and
    packages/memberships — service price, discount, package, membership."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Cash Pay Clinic", slug="cash-pay-clinic")
        self.biller = User.objects.create_user(
            username="cashpay-biller", password="safe-test-password", organization=self.organization, role=User.Role.BILLER,
        )
        self.scheduler = User.objects.create_user(
            username="cashpay-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER,
        )
        self.therapist = User.objects.create_user(
            username="cashpay-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        billing_feature = Feature.objects.create(code="billing", name="Billing")
        plan = SubscriptionPlan.objects.create(code="cashpay-plan", name="Cash Pay Plan", provider_seat_limit=50)
        plan.features.add(billing_feature)
        subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=plan, status=OrganizationSubscription.Status.ACTIVE,
        )
        subscription.features.add(billing_feature)
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Cash", last_name="Payer", date_of_birth="1990-01-01",
            assigned_therapist=self.therapist,
        )
        self.other_organization = Organization.objects.create(name="Other Cash Pay Clinic", slug="other-cash-pay-clinic")
        self.other_biller = User.objects.create_user(
            username="other-cashpay-biller", password="safe-test-password", organization=self.other_organization, role=User.Role.BILLER,
        )

    # --- service prices --------------------------------------------------

    def test_biller_can_create_a_service_price(self):
        self.client.force_login(self.biller)
        response = self.client.post(
            reverse("api-service-prices"), data=json.dumps({"cptCode": "97110", "label": "Therapeutic Exercise", "price": "90.00"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["servicePrice"]["price"], "90.00")

    def test_scheduler_can_list_but_not_create_service_prices(self):
        ServicePrice.objects.create(organization=self.organization, cpt_code="97110", label="Therex", price="90.00")
        self.client.force_login(self.scheduler)
        list_response = self.client.get(reverse("api-service-prices"))
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()["servicePrices"]), 1)
        create_response = self.client.post(
            reverse("api-service-prices"), data=json.dumps({"cptCode": "97140", "label": "Manual", "price": "80.00"}),
            content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 403)

    def test_service_price_can_be_deactivated(self):
        price = ServicePrice.objects.create(organization=self.organization, cpt_code="97110", label="Therex", price="90.00")
        self.client.force_login(self.biller)
        response = self.client.delete(reverse("api-service-price-detail", kwargs={"price_id": price.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["servicePrice"]["isActive"])

    def test_service_price_is_tenant_isolated(self):
        ServicePrice.objects.create(organization=self.organization, cpt_code="97110", label="Therex", price="90.00")
        ServicePrice.objects.create(organization=self.other_organization, cpt_code="97140", label="Manual", price="80.00")
        self.client.force_login(self.biller)
        response = self.client.get(reverse("api-service-prices"))
        codes = {row["cptCode"] for row in response.json()["servicePrices"]}
        self.assertEqual(codes, {"97110"})

    # --- cash packages / memberships --------------------------------------

    def _create_package(self, **overrides):
        body = {"kind": "package", "name": "10-Visit Package", "price": "800.00", "visitsIncluded": 10}
        body.update(overrides)
        self.client.force_login(self.biller)
        return self.client.post(
            reverse("api-patient-cash-packages", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps(body), content_type="application/json",
        )

    def test_biller_can_sell_a_visit_package(self):
        response = self._create_package()
        self.assertEqual(response.status_code, 201)
        body = response.json()["cashPackage"]
        self.assertEqual(body["visitsRemaining"], 10)
        self.assertTrue(body["isActive"])

    def test_membership_has_unlimited_visits_remaining(self):
        response = self._create_package(kind="membership", name="Monthly Membership", visitsIncluded=None, price="150.00")
        self.assertIsNone(response.json()["cashPackage"]["visitsRemaining"])

    def test_recording_a_visit_decrements_remaining_and_blocks_when_exhausted(self):
        create_response = self._create_package(visitsIncluded=1)
        package_id = create_response.json()["cashPackage"]["id"]
        self.client.force_login(self.biller)
        first = self.client.patch(
            reverse("api-cash-package-detail", kwargs={"patient_id": self.patient.pk, "package_id": package_id}),
            data=json.dumps({"action": "record_visit"}), content_type="application/json",
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["cashPackage"]["visitsRemaining"], 0)
        self.assertFalse(first.json()["cashPackage"]["isActive"])
        second = self.client.patch(
            reverse("api-cash-package-detail", kwargs={"patient_id": self.patient.pk, "package_id": package_id}),
            data=json.dumps({"action": "record_visit"}), content_type="application/json",
        )
        self.assertEqual(second.status_code, 409)

    def test_cancelling_a_package(self):
        create_response = self._create_package()
        package_id = create_response.json()["cashPackage"]["id"]
        self.client.force_login(self.biller)
        response = self.client.patch(
            reverse("api-cash-package-detail", kwargs={"patient_id": self.patient.pk, "package_id": package_id}),
            data=json.dumps({"action": "cancel"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cashPackage"]["status"], "cancelled")
        self.assertFalse(response.json()["cashPackage"]["isActive"])

    def test_discount_percent_out_of_range_is_rejected(self):
        response = self._create_package(discountPercent="150")
        self.assertEqual(response.status_code, 422)

    def test_biller_cannot_sell_a_package_to_another_orgs_patient(self):
        self.client.force_login(self.other_biller)
        response = self.client.post(
            reverse("api-patient-cash-packages", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"kind": "package", "name": "Blocked", "price": "1.00"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_cash_package_records_audit_events(self):
        self._create_package()
        self.assertTrue(AuditEvent.objects.filter(action="cash_package.created", patient=self.patient).exists())


class PatientSuperbillDataTests(TestCase):
    """Billing/RCM Phase 6: patient-facing superbill data — patient,
    provider, date, diagnosis, CPT, units, charges, and practice
    information. Uses linked Charge rows when present; falls back to the
    legacy flat `codes` list for pre-existing superbills."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Superbill Clinic", slug="superbill-clinic", npi_number="1112223334", tax_id="55-6667777",
            address_line_1="1 Superbill Rd", city="Durham", state="NC", zip_code="27701",
        )
        self.biller = User.objects.create_user(
            username="superbill-biller", password="safe-test-password", organization=self.organization, role=User.Role.BILLER,
        )
        self.therapist = User.objects.create_user(
            username="superbill-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Sam", last_name="Superbill", date_of_birth="1990-01-01",
            assigned_therapist=self.therapist, diagnoses="Low back pain",
        )
        self.diagnosis = DiagnosisCode.objects.create(code="M54.50", description="Low back pain, unspecified")

        self.other_organization = Organization.objects.create(name="Other Superbill Clinic", slug="other-superbill-clinic")
        self.other_biller = User.objects.create_user(
            username="other-superbill-biller", password="safe-test-password", organization=self.other_organization, role=User.Role.BILLER,
        )

    def test_legacy_flat_superbill_falls_back_to_codes_and_amount(self):
        superbill = Superbill.objects.create(
            patient=self.patient, clinician=self.therapist, service_date=date.today(), codes=["97110", "97140"], amount="150.00",
        )
        self.client.force_login(self.biller)
        response = self.client.get(
            reverse("api-superbill-data", kwargs={"patient_id": self.patient.pk, "superbill_id": superbill.pk})
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["superbill"]
        self.assertEqual(len(data["lines"]), 2)
        self.assertEqual(data["totalAmount"], "150.00")
        self.assertEqual(data["diagnosisText"], "Low back pain")
        self.assertEqual(data["practice"]["npi"], "1112223334")

    def test_charge_linked_superbill_uses_rich_line_data(self):
        superbill = Superbill.objects.create(
            patient=self.patient, clinician=self.therapist, service_date=date.today(), codes=[], amount="0.00",
        )
        charge = Charge.objects.create(
            organization=self.organization, patient=self.patient, provider=self.therapist,
            service_date=date.today(), cpt_code="97110", units=2, charge_amount="90.00", superbill=superbill,
        )
        charge.diagnosis_codes.set([self.diagnosis])
        self.client.force_login(self.biller)
        response = self.client.get(
            reverse("api-superbill-data", kwargs={"patient_id": self.patient.pk, "superbill_id": superbill.pk})
        )
        data = response.json()["superbill"]
        self.assertEqual(len(data["lines"]), 1)
        line = data["lines"][0]
        self.assertEqual(line["cptCode"], "97110")
        self.assertEqual(line["units"], 2)
        self.assertEqual(line["diagnosisCodes"], ["M54.50"])
        self.assertEqual(data["totalAmount"], "90.00")
        self.assertEqual(data["diagnosisCodes"], ["M54.50"])

    def test_charge_cannot_be_linked_to_both_a_claim_and_a_superbill(self):
        payer = Payer.objects.create(organization=self.organization, name="Superbill Payer")
        policy = PatientInsurance.objects.create(
            organization=self.organization, patient=self.patient, payer=payer, member_id="MBR-SB-1",
            effective_date=date.today() - timedelta(days=100),
        )
        claim = Claim.objects.create(
            organization=self.organization, patient=self.patient, patient_insurance=policy, payer=payer,
            diagnosis_code_list=[],
        )
        superbill = Superbill.objects.create(
            patient=self.patient, clinician=self.therapist, service_date=date.today(), codes=[], amount="0.00",
        )
        charge = Charge(
            organization=self.organization, patient=self.patient, provider=self.therapist,
            service_date=date.today(), cpt_code="97110", units=1, charge_amount="90.00", claim=claim, superbill=superbill,
        )
        with self.assertRaises(ValidationError):
            charge.full_clean()

    def test_superbill_data_is_tenant_isolated(self):
        superbill = Superbill.objects.create(
            patient=self.patient, clinician=self.therapist, service_date=date.today(), codes=["97110"], amount="80.00",
        )
        self.client.force_login(self.other_biller)
        response = self.client.get(
            reverse("api-superbill-data", kwargs={"patient_id": self.patient.pk, "superbill_id": superbill.pk})
        )
        self.assertEqual(response.status_code, 403)


class ProviderLimitedBillingViewTests(TestCase):
    """Billing/RCM Phase 7: 'Provider limited billing view' — a treating
    clinician may view (never edit) charges/claims for visits they
    personally rendered, without full billing-role access. Every other
    billing surface (payer directory, insurance, payments, statements,
    denials) stays full-billing-staff-only."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Provider View Clinic", slug="provider-view-clinic")
        self.rendering_therapist = User.objects.create_user(
            username="pv-rendering-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        self.other_therapist = User.objects.create_user(
            username="pv-other-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        self.biller = User.objects.create_user(
            username="pv-biller", password="safe-test-password", organization=self.organization, role=User.Role.BILLER,
        )
        billing_feature = Feature.objects.create(code="billing", name="Billing")
        claims_feature = Feature.objects.create(code="claims", name="Claims")
        plan = SubscriptionPlan.objects.create(code="pv-enterprise", name="Enterprise", provider_seat_limit=50)
        plan.features.add(billing_feature, claims_feature)
        subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=plan, status=OrganizationSubscription.Status.ACTIVE,
        )
        subscription.features.add(billing_feature, claims_feature)

        self.payer = Payer.objects.create(organization=self.organization, name="Provider View Payer")
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Peter", last_name="View", date_of_birth="1990-01-01",
            assigned_therapist=self.rendering_therapist,
        )
        self.unassigned_patient = Patient.objects.create(
            organization=self.organization, first_name="Unassigned", last_name="Patient", date_of_birth="1990-01-01",
            assigned_therapist=self.other_therapist,
        )
        self.own_charge = Charge.objects.create(
            organization=self.organization, patient=self.patient, provider=self.rendering_therapist,
            service_date=date.today(), cpt_code="97110", units=1, charge_amount="90.00",
        )
        self.other_charge = Charge.objects.create(
            organization=self.organization, patient=self.patient, provider=self.other_therapist,
            service_date=date.today(), cpt_code="97140", units=1, charge_amount="70.00",
        )
        policy = PatientInsurance.objects.create(
            organization=self.organization, patient=self.patient, payer=self.payer, member_id="MBR-PV-1",
            effective_date=date.today() - timedelta(days=100),
        )
        self.own_claim = Claim.objects.create(
            organization=self.organization, patient=self.patient, patient_insurance=policy, payer=self.payer,
            diagnosis_code_list=[],
        )
        self.own_charge.claim = self.own_claim
        self.own_charge.save(update_fields=["claim"])
        self.other_only_claim = Claim.objects.create(
            organization=self.organization, patient=self.patient, patient_insurance=policy, payer=self.payer,
            diagnosis_code_list=[],
        )
        self.other_charge.claim = self.other_only_claim
        self.other_charge.save(update_fields=["claim"])

    def test_therapist_can_view_their_own_rendered_charge(self):
        self.client.force_login(self.rendering_therapist)
        response = self.client.get(
            reverse("api-patient-charge-detail", kwargs={"patient_id": self.patient.pk, "charge_id": self.own_charge.pk})
        )
        self.assertEqual(response.status_code, 200)

    def test_therapist_cannot_view_another_providers_charge(self):
        self.client.force_login(self.rendering_therapist)
        response = self.client.get(
            reverse("api-patient-charge-detail", kwargs={"patient_id": self.patient.pk, "charge_id": self.other_charge.pk})
        )
        self.assertEqual(response.status_code, 403)

    def test_therapist_charge_list_is_scoped_to_their_own_visits(self):
        self.client.force_login(self.rendering_therapist)
        response = self.client.get(reverse("api-patient-charges", kwargs={"patient_id": self.patient.pk}))
        self.assertEqual(response.status_code, 200)
        charge_ids = {row["id"] for row in response.json()["charges"]}
        self.assertEqual(charge_ids, {str(self.own_charge.pk)})

    def test_therapist_cannot_edit_a_charge(self):
        self.client.force_login(self.rendering_therapist)
        response = self.client.patch(
            reverse("api-patient-charge-detail", kwargs={"patient_id": self.patient.pk, "charge_id": self.own_charge.pk}),
            data=json.dumps({"chargeAmount": "999.00"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_therapist_cannot_view_charges_for_an_unassigned_patient(self):
        self.client.force_login(self.rendering_therapist)
        response = self.client.get(reverse("api-patient-charges", kwargs={"patient_id": self.unassigned_patient.pk}))
        self.assertEqual(response.status_code, 403)

    def test_therapist_can_view_a_claim_containing_their_own_charge(self):
        self.client.force_login(self.rendering_therapist)
        response = self.client.get(
            reverse("api-patient-claim-detail", kwargs={"patient_id": self.patient.pk, "claim_id": self.own_claim.pk})
        )
        self.assertEqual(response.status_code, 200)

    def test_therapist_cannot_view_a_claim_with_no_charges_from_them(self):
        self.client.force_login(self.rendering_therapist)
        response = self.client.get(
            reverse("api-patient-claim-detail", kwargs={"patient_id": self.patient.pk, "claim_id": self.other_only_claim.pk})
        )
        self.assertEqual(response.status_code, 403)

    def test_therapist_claim_list_is_scoped_to_claims_with_their_own_charges(self):
        self.client.force_login(self.rendering_therapist)
        response = self.client.get(reverse("api-patient-claims", kwargs={"patient_id": self.patient.pk}))
        claim_ids = {row["id"] for row in response.json()["claims"]}
        self.assertEqual(claim_ids, {str(self.own_claim.pk)})

    def test_therapist_cannot_create_a_claim(self):
        self.client.force_login(self.rendering_therapist)
        response = self.client.post(
            reverse("api-patient-claims", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"patientInsuranceId": "x", "chargeIds": [str(self.own_charge.pk)]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_therapist_cannot_access_the_payer_directory(self):
        self.client.force_login(self.rendering_therapist)
        response = self.client.get(reverse("api-payers"))
        self.assertEqual(response.status_code, 403)

    def test_biller_view_is_unaffected_by_provider_scoping(self):
        """A full billing-role user still sees every charge/claim for the
        patient, not just those tied to one provider."""
        self.client.force_login(self.biller)
        response = self.client.get(reverse("api-patient-charges", kwargs={"patient_id": self.patient.pk}))
        charge_ids = {row["id"] for row in response.json()["charges"]}
        self.assertEqual(charge_ids, {str(self.own_charge.pk), str(self.other_charge.pk)})


class ClaimCorrectionAuditTests(TestCase):
    """Billing/RCM Phase 7: correcting a claim gets its own distinct audit
    action (`claim.corrected`), separate from a generic status change, per
    the module's AUDIT LOG checklist."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Correction Clinic", slug="correction-clinic")
        self.biller = User.objects.create_user(
            username="correction-biller", password="safe-test-password", organization=self.organization, role=User.Role.BILLER,
        )
        self.therapist = User.objects.create_user(
            username="correction-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        billing_feature = Feature.objects.create(code="billing", name="Billing")
        claims_feature = Feature.objects.create(code="claims", name="Claims")
        plan = SubscriptionPlan.objects.create(code="correction-enterprise", name="Enterprise", provider_seat_limit=50)
        plan.features.add(billing_feature, claims_feature)
        subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=plan, status=OrganizationSubscription.Status.ACTIVE,
        )
        subscription.features.add(billing_feature, claims_feature)
        payer = Payer.objects.create(organization=self.organization, name="Correction Payer")
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Cody", last_name="Correction", date_of_birth="1990-01-01",
            assigned_therapist=self.therapist,
        )
        policy = PatientInsurance.objects.create(
            organization=self.organization, patient=self.patient, payer=payer, member_id="MBR-COR-1",
            effective_date=date.today() - timedelta(days=100),
        )
        self.claim = Claim.objects.create(
            organization=self.organization, patient=self.patient, patient_insurance=policy, payer=payer,
            diagnosis_code_list=[], status=Claim.Status.REJECTED,
        )

    def test_correcting_a_claim_records_a_distinct_audit_action(self):
        self.client.force_login(self.biller)
        response = self.client.post(
            reverse("api-claim-status-update", kwargs={"patient_id": self.patient.pk, "claim_id": self.claim.pk}),
            data=json.dumps({"status": "corrected"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(AuditEvent.objects.filter(action="claim.corrected", patient=self.patient).exists())
        self.assertFalse(AuditEvent.objects.filter(action="claim.status_changed", patient=self.patient).exists())

    def test_other_status_transitions_still_use_the_generic_action(self):
        self.client.force_login(self.biller)
        self.client.post(
            reverse("api-claim-status-update", kwargs={"patient_id": self.patient.pk, "claim_id": self.claim.pk}),
            data=json.dumps({"status": "appealed"}), content_type="application/json",
        )
        self.assertTrue(AuditEvent.objects.filter(action="claim.status_changed", patient=self.patient).exists())


class BillingSummaryReportTests(TestCase):
    """Billing/RCM Phase 7: the reports suite — charges, collections,
    payments, claim status breakdown, clean claim rate, revenue by
    provider/location/payer, and patient balances. Every figure is a real
    live aggregate; 'revenue' is billed/production charge amount, reported
    separately from 'collections' (actual cash received) — never conflated."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Summary Clinic", slug="summary-clinic")
        self.biller = User.objects.create_user(
            username="summary-biller", password="safe-test-password", organization=self.organization, role=User.Role.BILLER,
        )
        self.scheduler = User.objects.create_user(
            username="summary-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER,
        )
        self.therapist_a = User.objects.create_user(
            username="summary-therapist-a", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        self.therapist_b = User.objects.create_user(
            username="summary-therapist-b", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        self.location = Location.objects.create(organization=self.organization, name="Summary Location")
        self.payer = Payer.objects.create(organization=self.organization, name="Summary Payer")

        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Sue", last_name="Summary", date_of_birth="1990-01-01",
            assigned_therapist=self.therapist_a,
        )
        self.policy = PatientInsurance.objects.create(
            organization=self.organization, patient=self.patient, payer=self.payer, member_id="MBR-SUM-1",
            effective_date=date.today() - timedelta(days=365),
        )

        # In-window charge from therapist_a at the location, on a clean (never-denied) paid-down claim.
        self.in_window_charge = Charge.objects.create(
            organization=self.organization, patient=self.patient, provider=self.therapist_a, location=self.location,
            service_date=date.today() - timedelta(days=5), cpt_code="97110", units=1, charge_amount="100.00",
        )
        self.clean_claim = Claim.objects.create(
            organization=self.organization, patient=self.patient, patient_insurance=self.policy, payer=self.payer,
            diagnosis_code_list=[], status=Claim.Status.SUBMITTED, submitted_at=timezone.now() - timedelta(days=4),
        )
        self.in_window_charge.claim = self.clean_claim
        self.in_window_charge.save(update_fields=["claim"])
        ClaimTransaction.objects.create(
            organization=self.organization, patient=self.patient, claim=self.clean_claim,
            kind=ClaimTransaction.Kind.INSURANCE_PAYMENT, amount="60.00", payment_date=date.today() - timedelta(days=2),
        )
        ClaimTransaction.objects.create(
            organization=self.organization, patient=self.patient, claim=self.clean_claim,
            kind=ClaimTransaction.Kind.ADJUSTMENT, amount="10.00", payment_date=date.today() - timedelta(days=2),
        )

        # A second, denied claim from therapist_b — pulls the clean claim rate below 100%.
        self.denied_charge = Charge.objects.create(
            organization=self.organization, patient=self.patient, provider=self.therapist_b,
            service_date=date.today() - timedelta(days=3), cpt_code="97140", units=1, charge_amount="70.00",
        )
        self.denied_claim = Claim.objects.create(
            organization=self.organization, patient=self.patient, patient_insurance=self.policy, payer=self.payer,
            diagnosis_code_list=[], status=Claim.Status.DENIED, submitted_at=timezone.now() - timedelta(days=2),
        )
        self.denied_charge.claim = self.denied_claim
        self.denied_charge.save(update_fields=["claim"])
        ClaimDenial.objects.create(
            organization=self.organization, patient=self.patient, claim=self.denied_claim, denial_reason="Missing info",
        )

        # An out-of-window charge that must not affect windowed totals.
        Charge.objects.create(
            organization=self.organization, patient=self.patient, provider=self.therapist_a,
            service_date=date.today() - timedelta(days=200), cpt_code="97530", units=1, charge_amount="500.00",
        )

        self.other_organization = Organization.objects.create(name="Other Summary Clinic", slug="other-summary-clinic")
        self.other_biller = User.objects.create_user(
            username="other-summary-biller", password="safe-test-password", organization=self.other_organization, role=User.Role.BILLER,
        )

    def _get_report(self, **params):
        self.client.force_login(self.biller)
        return self.client.get(reverse("api-billing-summary-report"), params)

    def test_charges_totaled_within_the_default_window(self):
        response = self._get_report()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["charges"]["count"], 2)  # the 200-day-old charge is excluded by the default 90-day window
        self.assertEqual(body["charges"]["totalAmount"], "170.00")

    def test_collections_and_payment_breakdown(self):
        body = self._get_report().json()
        self.assertEqual(body["collections"]["totalAmount"], "60.00")
        self.assertEqual(body["payments"]["insurancePayments"], "60.00")
        self.assertEqual(body["payments"]["adjustments"], "10.00")
        self.assertEqual(body["payments"]["patientPayments"], "0.00")
        self.assertEqual(body["payments"]["refunds"], "0.00")

    def test_claims_by_status_reflects_current_snapshot(self):
        body = self._get_report().json()
        self.assertEqual(body["claimsByStatus"]["submitted"], 1)
        self.assertEqual(body["claimsByStatus"]["denied"], 1)

    def test_clean_claim_rate_excludes_denied_claims(self):
        body = self._get_report().json()
        self.assertEqual(body["claimsSubmittedInWindow"], 2)
        self.assertEqual(body["cleanClaimRate"], "50.0")

    def test_revenue_by_provider_location_and_payer(self):
        body = self._get_report().json()
        provider_totals = {row["name"]: row["amount"] for row in body["revenueByProvider"]}
        self.assertEqual(provider_totals[self.therapist_a.get_full_name() or self.therapist_a.username], "100.00")
        self.assertEqual(provider_totals[self.therapist_b.get_full_name() or self.therapist_b.username], "70.00")
        location_totals = {row["name"]: row["amount"] for row in body["revenueByLocation"]}
        self.assertEqual(location_totals[self.location.name], "100.00")
        payer_totals = {row["name"]: row["amount"] for row in body["revenueByPayer"]}
        self.assertEqual(payer_totals[self.payer.name], "170.00")

    def test_patient_balances_lists_outstanding_amounts(self):
        body = self._get_report().json()
        balances = {row["patientId"]: row["balance"] for row in body["patientBalances"]}
        # clean claim balance: 100 - 60 paid - 10 adjusted = 30; denied claim balance: 70 — combined 100.00
        self.assertEqual(balances[str(self.patient.pk)], "100.00")

    def test_date_window_filters_charges(self):
        body = self._get_report(start=(date.today() - timedelta(days=1)).isoformat(), end=date.today().isoformat()).json()
        self.assertEqual(body["charges"]["count"], 0)

    def test_invalid_date_is_rejected(self):
        response = self._get_report(start="not-a-date")
        self.assertEqual(response.status_code, 400)

    def test_scheduler_cannot_access_the_billing_summary_report(self):
        self.client.force_login(self.scheduler)
        response = self.client.get(reverse("api-billing-summary-report"))
        self.assertEqual(response.status_code, 403)

    def test_billing_summary_is_tenant_isolated(self):
        self.client.force_login(self.other_biller)
        response = self.client.get(reverse("api-billing-summary-report"))
        self.assertEqual(response.json()["charges"]["count"], 0)


class PatientPortalFoundationTests(TestCase):
    """Patient Portal Phase 1: the Patient<->User link, portal permission
    scoping, staff-triggered invitations, and the dashboard. The dashboard
    endpoint takes no patient id at all — every test here confirms that
    "which patient" always resolves from the authenticated session, never
    from anything client-suppliable (the module's core IDOR defense)."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Portal Clinic", slug="portal-clinic")
        self.scheduler = User.objects.create_user(
            username="portal-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER,
        )
        self.therapist = User.objects.create_user(
            username="portal-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        self.biller = User.objects.create_user(
            username="portal-biller", password="safe-test-password", organization=self.organization, role=User.Role.BILLER,
        )
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Portia", last_name="Patient", date_of_birth="1990-01-01",
            email="portia@example.test", assigned_therapist=self.therapist,
        )
        self.other_patient = Patient.objects.create(
            organization=self.organization, first_name="Other", last_name="Person", date_of_birth="1991-02-02",
            email="other@example.test", assigned_therapist=self.therapist,
        )
        self.other_organization = Organization.objects.create(name="Other Portal Clinic", slug="other-portal-clinic")
        self.other_org_scheduler = User.objects.create_user(
            username="other-portal-scheduler", password="safe-test-password", organization=self.other_organization, role=User.Role.SCHEDULER,
        )

    # --- patients_for() / portal ownership scoping (unit-level) -----------

    def test_patients_for_scopes_a_patient_role_user_to_their_own_chart(self):
        from care.access import patients_for

        portal_user = User.objects.create_user(
            username="scoping-check@example.test", password="safe-test-password",
            organization=self.organization, role=User.Role.PATIENT,
        )
        self.patient.portal_user = portal_user
        self.patient.save(update_fields=["portal_user"])
        result = list(patients_for(portal_user, clinical=True))
        self.assertEqual(result, [self.patient])

    def test_patients_for_patient_role_ignores_clinical_false(self):
        """Regression test: clinical=False must NEVER hand a portal account
        the whole-org queryset — this was the exact bug fixed in access.py."""
        from care.access import patients_for

        portal_user = User.objects.create_user(
            username="clinical-false-check@example.test", password="safe-test-password",
            organization=self.organization, role=User.Role.PATIENT,
        )
        self.patient.portal_user = portal_user
        self.patient.save(update_fields=["portal_user"])
        result = list(patients_for(portal_user, clinical=False))
        self.assertEqual(result, [self.patient])

    def test_patients_for_patient_role_with_no_linked_chart_is_empty(self):
        from care.access import patients_for

        unlinked_user = User.objects.create_user(
            username="unlinked@example.test", password="safe-test-password",
            organization=self.organization, role=User.Role.PATIENT,
        )
        self.assertEqual(list(patients_for(unlinked_user, clinical=False)), [])

    # --- staff: invite a patient to the portal ------------------------------

    def _invite(self, **overrides):
        body = {"email": "portia@example.test"}
        body.update(overrides)
        self.client.force_login(self.scheduler)
        return self.client.post(
            reverse("api-patient-portal-invite", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps(body), content_type="application/json",
        )

    def test_scheduler_can_invite_a_patient(self):
        response = self._invite()
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertFalse(body["reissued"])
        self.assertIn("invitationUrl", body)
        self.patient.refresh_from_db()
        self.assertIsNotNone(self.patient.portal_user_id)
        self.assertEqual(self.patient.portal_user.role, User.Role.PATIENT)
        self.assertEqual(self.patient.portal_user.username, "portia@example.test")

    def test_inviting_twice_reuses_the_same_portal_account(self):
        self._invite()
        self.patient.refresh_from_db()
        first_user_id = self.patient.portal_user_id
        response = self._invite()
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["reissued"])
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.portal_user_id, first_user_id)
        self.assertEqual(User.objects.filter(role=User.Role.PATIENT).count(), 1)

    def test_invite_rejects_a_conflicting_username(self):
        User.objects.create_user(username="taken@example.test", password="safe-test-password", organization=self.organization)
        response = self._invite(email="taken@example.test")
        self.assertEqual(response.status_code, 409)

    def test_invite_falls_back_to_the_charts_email_when_none_given(self):
        response = self._invite(email="")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["email"], "portia@example.test")

    def test_biller_cannot_invite_a_patient(self):
        self.client.force_login(self.biller)
        response = self.client.post(
            reverse("api-patient-portal-invite", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"email": "portia@example.test"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_therapist_cannot_invite_an_unassigned_patient(self):
        unassigned = Patient.objects.create(
            organization=self.organization, first_name="Not", last_name="Mine", date_of_birth="1990-01-01",
            email="notmine@example.test",
        )
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-patient-portal-invite", kwargs={"patient_id": unassigned.pk}),
            data=json.dumps({"email": "notmine@example.test"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_invite_across_tenants_is_blocked(self):
        self.client.force_login(self.other_org_scheduler)
        response = self.client.post(
            reverse("api-patient-portal-invite", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"email": "portia@example.test"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_invite_records_an_audit_event(self):
        self._invite()
        self.assertTrue(AuditEvent.objects.filter(action="patient_portal.invited", patient=self.patient).exists())

    # --- full invite -> activate -> login -> dashboard flow ------------------

    def test_full_portal_onboarding_flow(self):
        invite_response = self._invite()
        invitation_url = invite_response.json()["invitationUrl"]
        token = invitation_url.split("token=")[1]

        activate_response = self.client.post(
            reverse("api-activate-invitation"),
            data=json.dumps({"token": token, "password": "a-strong-patient-password-123"}),
            content_type="application/json",
        )
        self.assertEqual(activate_response.status_code, 200)

        me_response = self.client.get(reverse("api-me"))
        self.assertEqual(me_response.status_code, 200)
        self.assertTrue(me_response.json()["user"]["capabilities"]["isPatient"])

        dashboard_response = self.client.get(reverse("api-portal-dashboard"))
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertEqual(dashboard_response.json()["patient"]["fullName"], "Portia Patient")

    # --- dashboard: permissions + IDOR isolation --------------------------

    def _activate_portal_login(self, patient: Patient, password: str):
        self.client.force_login(self.scheduler)
        invite_response = self.client.post(
            reverse("api-patient-portal-invite", kwargs={"patient_id": patient.pk}),
            data=json.dumps({"email": patient.email}), content_type="application/json",
        )
        token = invite_response.json()["invitationUrl"].split("token=")[1]
        self.client.logout()
        self.client.post(
            reverse("api-activate-invitation"),
            data=json.dumps({"token": token, "password": password}), content_type="application/json",
        )

    def test_dashboard_requires_authentication(self):
        response = self.client.get(reverse("api-portal-dashboard"))
        self.assertEqual(response.status_code, 401)

    def test_staff_role_cannot_access_the_patient_dashboard(self):
        self.client.force_login(self.scheduler)
        response = self.client.get(reverse("api-portal-dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_dashboard_reflects_only_the_logged_in_patients_own_data(self):
        Appointment.objects.create(
            patient=self.patient, therapist=self.therapist,
            starts_at=timezone.now() + timedelta(days=3), ends_at=timezone.now() + timedelta(days=3, hours=1),
            status=Appointment.Status.SCHEDULED, created_by=self.scheduler,
        )
        Appointment.objects.create(
            patient=self.other_patient, therapist=self.therapist,
            starts_at=timezone.now() + timedelta(days=2), ends_at=timezone.now() + timedelta(days=2, hours=1),
            status=Appointment.Status.SCHEDULED, created_by=self.scheduler,
        )
        self._activate_portal_login(self.patient, "portia-password-123")
        response = self.client.get(reverse("api-portal-dashboard"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsNotNone(body["nextAppointment"])
        self.assertEqual(body["patient"]["fullName"], "Portia Patient")

    def test_dashboard_has_no_patient_id_parameter_to_spoof(self):
        """The module's core IDOR defense, made explicit: even appending a
        query string naming a different patient id changes nothing — the
        endpoint never reads one."""
        self._activate_portal_login(self.patient, "portia-password-123")
        response = self.client.get(reverse("api-portal-dashboard") + f"?patientId={self.other_patient.pk}&patient_id={self.other_patient.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["patient"]["fullName"], "Portia Patient")

    def test_dashboard_message_count_and_balance_are_real(self):
        self._activate_portal_login(self.patient, "portia-password-123")
        self.patient.refresh_from_db()
        SecureMessage.objects.create(
            patient=self.patient, sender=self.therapist, recipient=self.patient.portal_user,
            subject="Welcome", body="Welcome to the portal.",
        )
        HomeProgram.objects.create(
            patient=self.patient, prescribed_by=self.therapist, title="Home routine",
            patient_instructions="Do these daily.", status=HomeProgram.Status.ACTIVE,
        )
        response = self.client.get(reverse("api-portal-dashboard"))
        body = response.json()
        self.assertEqual(body["newMessageCount"], 1)
        self.assertEqual(body["homeExerciseProgram"]["title"], "Home routine")
        self.assertEqual(body["outstandingBalance"], "0.00")

    def test_dashboard_records_an_audit_event(self):
        self._activate_portal_login(self.patient, "portia-password-123")
        response = self.client.get(reverse("api-portal-dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            AuditEvent.objects.filter(action="patient_portal.dashboard_viewed", patient=self.patient).exists()
        )


class PatientPortalAppointmentsTests(TestCase):
    """Patient Portal Phase 2: appointment self-service (view/book/reschedule/
    cancel/confirm) and the waitlist. Booking/reschedule reuse the same
    care/availability.py + care/booking.py machinery as public booking, so
    these tests focus on the portal-specific wiring: patient-scoped ownership,
    the change-cutoff policy, and IDOR — Patient A must never affect Patient
    B's appointment or waitlist entry even with a known id."""

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Portal Scheduling Clinic", slug="portal-scheduling-clinic"
        )
        self.config = BookingConfiguration.objects.create(
            organization=self.organization,
            online_booking_enabled=True,
            allow_returning_patients=True,
            min_notice_hours=4,
            max_advance_days=90,
            slot_interval_minutes=15,
            patient_change_cutoff_hours=24,
        )
        self.location = Location.objects.create(
            organization=self.organization, name="Main Clinic", timezone="America/Los_Angeles"
        )
        self.therapist_user = User.objects.create_user(
            username="portal-sched-therapist", password="safe-test-password",
            organization=self.organization, role=User.Role.THERAPIST,
        )
        self.provider = Provider.objects.create(
            organization=self.organization, user=self.therapist_user, first_name="Jamie", last_name="Rivera",
            online_booking_enabled=True,
        )
        self.provider.locations.add(self.location)
        self.appointment_type = AppointmentType.objects.create(
            organization=self.organization, name="Follow-up Visit", default_duration_minutes=30,
            online_booking_enabled=True,
        )
        ProviderAppointmentType.objects.create(
            provider=self.provider, appointment_type=self.appointment_type, active=True
        )
        self.new_patient_type = AppointmentType.objects.create(
            organization=self.organization, name="Initial Eval", default_duration_minutes=45,
            online_booking_enabled=True, requires_new_patient=True,
        )
        ProviderAppointmentType.objects.create(
            provider=self.provider, appointment_type=self.new_patient_type, active=True
        )

        self.target_date = timezone.localdate() + timedelta(days=14)
        while self.target_date.weekday() > 4:
            self.target_date += timedelta(days=1)
        ProviderAvailability.objects.create(
            provider=self.provider, location=self.location, day_of_week=self.target_date.weekday(),
            start_time="09:00", end_time="12:00", active=True,
        )

        self.scheduler = User.objects.create_user(
            username="portal-sched-frontdesk", password="safe-test-password",
            organization=self.organization, role=User.Role.SCHEDULER,
        )
        self.biller = User.objects.create_user(
            username="portal-sched-biller", password="safe-test-password",
            organization=self.organization, role=User.Role.BILLER,
        )

        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Portia", last_name="Patient", date_of_birth="1990-01-01",
        )
        self.patient_portal_user = User.objects.create_user(
            username="portia-sched@example.test", password="portia-password-123",
            organization=self.organization, role=User.Role.PATIENT,
        )
        self.patient.portal_user = self.patient_portal_user
        self.patient.save(update_fields=["portal_user"])

        self.other_patient = Patient.objects.create(
            organization=self.organization, first_name="Other", last_name="Patient", date_of_birth="1991-02-02",
        )
        self.other_portal_user = User.objects.create_user(
            username="other-sched@example.test", password="other-password-123",
            organization=self.organization, role=User.Role.PATIENT,
        )
        self.other_patient.portal_user = self.other_portal_user
        self.other_patient.save(update_fields=["portal_user"])

    def _login_patient(self):
        self.client.force_login(self.patient_portal_user)

    def _availability(self, **params):
        query = {
            "location_id": str(self.location.pk),
            "appointment_type_id": str(self.appointment_type.pk),
            "date": self.target_date.isoformat(),
        }
        query.update(params)
        url = reverse("api-portal-booking-availability") + "?" + "&".join(f"{key}={value}" for key, value in query.items())
        return self.client.get(url)

    def _first_slot(self):
        self._login_patient()
        response = self._availability()
        for entry in response.json()["providers"]:
            if entry["provider"]["id"] == str(self.provider.pk):
                return entry["slots"][0]["start"]
        raise AssertionError("No slots were available for test setup.")

    def _book(self, start_iso, **overrides):
        payload = {
            "locationId": str(self.location.pk),
            "appointmentTypeId": str(self.appointment_type.pk),
            "providerId": str(self.provider.pk),
            "startDatetime": start_iso,
            "reasonForVisit": "Knee pain",
        }
        payload.update(overrides)
        return self.client.post(
            reverse("api-portal-booking-create"), data=json.dumps(payload), content_type="application/json"
        )

    def _create_appointment(self, patient, *, starts_at, status=Appointment.Status.SCHEDULED):
        return Appointment.objects.create(
            patient=patient, therapist=self.therapist_user, provider=self.provider, location_detail=self.location,
            appointment_type=self.appointment_type, starts_at=starts_at, ends_at=starts_at + timedelta(minutes=30),
            status=status, created_by=self.scheduler,
        )

    # --- booking preview endpoints ------------------------------------------

    def test_booking_locations_lists_active_location(self):
        self._login_patient()
        response = self.client.get(reverse("api-portal-booking-locations"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([entry["id"] for entry in response.json()["locations"]], [str(self.location.pk)])

    def test_booking_appointment_types_excludes_new_patient_only_type(self):
        self._login_patient()
        response = self.client.get(reverse("api-portal-booking-appointment-types"))
        ids = {entry["id"] for entry in response.json()["appointmentTypes"]}
        self.assertIn(str(self.appointment_type.pk), ids)
        self.assertNotIn(str(self.new_patient_type.pk), ids)

    def test_booking_providers_lists_eligible_provider(self):
        self._login_patient()
        url = (
            reverse("api-portal-booking-providers")
            + f"?location_id={self.location.pk}&appointment_type_id={self.appointment_type.pk}"
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([entry["id"] for entry in response.json()["providers"]], [str(self.provider.pk)])

    def test_booking_availability_returns_slots_within_working_hours(self):
        start_iso = self._first_slot()
        local_start = timezone.localtime(datetime.fromisoformat(start_iso), ZoneInfo("America/Los_Angeles"))
        self.assertEqual((local_start.hour, local_start.minute), (9, 0))

    def test_unauthenticated_request_is_rejected(self):
        response = self.client.get(reverse("api-portal-booking-locations"))
        self.assertEqual(response.status_code, 401)

    def test_staff_cannot_use_portal_booking_endpoints(self):
        self.client.force_login(self.scheduler)
        response = self.client.get(reverse("api-portal-booking-locations"))
        self.assertEqual(response.status_code, 403)

    # --- booking creation -----------------------------------------------------

    def test_create_booking_succeeds(self):
        start_iso = self._first_slot()
        response = self._book(start_iso)
        self.assertEqual(response.status_code, 201)
        appointment = Appointment.objects.get(pk=response.json()["appointment"]["id"])
        self.assertEqual(appointment.patient_id, self.patient.pk)
        self.assertEqual(appointment.booking_source, Appointment.BookingSource.PATIENT_PORTAL)
        self.assertEqual(appointment.created_by_id, self.patient_portal_user.pk)
        self.assertTrue(AuditEvent.objects.filter(action="appointment.created", patient=self.patient).exists())

    def test_create_booking_rejects_double_booked_slot(self):
        start_iso = self._first_slot()
        first = self._book(start_iso)
        self.assertEqual(first.status_code, 201)
        second = self._book(start_iso)
        self.assertEqual(second.status_code, 409)

    def test_create_booking_rejects_new_patient_only_type(self):
        start_iso = self._first_slot()
        response = self._book(start_iso, appointmentTypeId=str(self.new_patient_type.pk))
        self.assertEqual(response.status_code, 422)

    def test_create_booking_rejected_when_online_booking_disabled(self):
        start_iso = self._first_slot()
        self.config.online_booking_enabled = False
        self.config.save(update_fields=["online_booking_enabled"])
        response = self._book(start_iso)
        self.assertEqual(response.status_code, 404)

    # --- appointments list -------------------------------------------------

    def test_appointments_list_splits_upcoming_and_past(self):
        tz = ZoneInfo("America/Los_Angeles")
        future = timezone.make_aware(datetime.combine(self.target_date, time(9, 0)), tz)
        past = timezone.now() - timedelta(days=10)
        self._create_appointment(self.patient, starts_at=future)
        self._create_appointment(self.patient, starts_at=past, status=Appointment.Status.COMPLETED)
        self._login_patient()
        body = self.client.get(reverse("api-portal-appointments")).json()
        self.assertEqual(len(body["upcoming"]), 1)
        self.assertEqual(len(body["past"]), 1)
        self.assertIn("canCancel", body["upcoming"][0])
        self.assertNotIn("canCancel", body["past"][0])

    def test_appointments_list_never_shows_another_patients_appointment(self):
        tz = ZoneInfo("America/Los_Angeles")
        future = timezone.make_aware(datetime.combine(self.target_date, time(9, 0)), tz)
        self._create_appointment(self.other_patient, starts_at=future)
        self._login_patient()
        body = self.client.get(reverse("api-portal-appointments")).json()
        self.assertEqual(body["upcoming"], [])
        self.assertEqual(body["past"], [])

    # --- cancel --------------------------------------------------------------

    def test_cancel_appointment_succeeds_within_window(self):
        tz = ZoneInfo("America/Los_Angeles")
        starts_at = timezone.make_aware(datetime.combine(self.target_date, time(9, 0)), tz)
        appointment = self._create_appointment(self.patient, starts_at=starts_at)
        self._login_patient()
        response = self.client.post(reverse("api-portal-appointment-cancel", kwargs={"appointment_id": appointment.pk}))
        self.assertEqual(response.status_code, 200)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.CANCELLED)
        self.assertTrue(AuditEvent.objects.filter(action="appointment.cancelled", patient=self.patient).exists())

    def test_cancel_appointment_blocked_within_cutoff_window(self):
        appointment = self._create_appointment(self.patient, starts_at=timezone.now() + timedelta(hours=2))
        self._login_patient()
        response = self.client.post(reverse("api-portal-appointment-cancel", kwargs={"appointment_id": appointment.pk}))
        self.assertEqual(response.status_code, 409)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.SCHEDULED)

    def test_cancel_appointment_idor_is_blocked(self):
        tz = ZoneInfo("America/Los_Angeles")
        starts_at = timezone.make_aware(datetime.combine(self.target_date, time(9, 0)), tz)
        appointment = self._create_appointment(self.other_patient, starts_at=starts_at)
        self._login_patient()
        response = self.client.post(reverse("api-portal-appointment-cancel", kwargs={"appointment_id": appointment.pk}))
        self.assertEqual(response.status_code, 404)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.SCHEDULED)

    # --- reschedule ------------------------------------------------------------

    def test_reschedule_appointment_succeeds_to_a_new_slot(self):
        tz = ZoneInfo("America/Los_Angeles")
        starts_at = timezone.make_aware(datetime.combine(self.target_date, time(9, 0)), tz)
        appointment = self._create_appointment(self.patient, starts_at=starts_at)
        new_start = starts_at + timedelta(hours=1)
        self._login_patient()
        response = self.client.post(
            reverse("api-portal-appointment-reschedule", kwargs={"appointment_id": appointment.pk}),
            data=json.dumps({"startDatetime": new_start.isoformat()}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        appointment.refresh_from_db()
        self.assertEqual(appointment.starts_at, new_start)
        self.assertTrue(AuditEvent.objects.filter(action="appointment.rescheduled", patient=self.patient).exists())

    def test_reschedule_resets_confirmation(self):
        tz = ZoneInfo("America/Los_Angeles")
        starts_at = timezone.make_aware(datetime.combine(self.target_date, time(9, 0)), tz)
        appointment = self._create_appointment(self.patient, starts_at=starts_at)
        appointment.confirmed_at = timezone.now()
        appointment.save(update_fields=["confirmed_at"])
        self._login_patient()
        self.client.post(
            reverse("api-portal-appointment-reschedule", kwargs={"appointment_id": appointment.pk}),
            data=json.dumps({"startDatetime": (starts_at + timedelta(hours=1)).isoformat()}), content_type="application/json",
        )
        appointment.refresh_from_db()
        self.assertIsNone(appointment.confirmed_at)

    def test_reschedule_appointment_blocked_within_cutoff_window(self):
        starts_at = timezone.now() + timedelta(hours=2)
        appointment = self._create_appointment(self.patient, starts_at=starts_at)
        self._login_patient()
        response = self.client.post(
            reverse("api-portal-appointment-reschedule", kwargs={"appointment_id": appointment.pk}),
            data=json.dumps({"startDatetime": (starts_at + timedelta(hours=1)).isoformat()}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)

    def test_reschedule_appointment_idor_is_blocked(self):
        tz = ZoneInfo("America/Los_Angeles")
        starts_at = timezone.make_aware(datetime.combine(self.target_date, time(9, 0)), tz)
        appointment = self._create_appointment(self.other_patient, starts_at=starts_at)
        self._login_patient()
        response = self.client.post(
            reverse("api-portal-appointment-reschedule", kwargs={"appointment_id": appointment.pk}),
            data=json.dumps({"startDatetime": (starts_at + timedelta(hours=1)).isoformat()}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    # --- confirm ---------------------------------------------------------------

    def test_confirm_appointment_sets_confirmed_at(self):
        tz = ZoneInfo("America/Los_Angeles")
        starts_at = timezone.make_aware(datetime.combine(self.target_date, time(9, 0)), tz)
        appointment = self._create_appointment(self.patient, starts_at=starts_at)
        self._login_patient()
        response = self.client.post(reverse("api-portal-appointment-confirm", kwargs={"appointment_id": appointment.pk}))
        self.assertEqual(response.status_code, 200)
        appointment.refresh_from_db()
        self.assertIsNotNone(appointment.confirmed_at)
        self.assertTrue(AuditEvent.objects.filter(action="appointment.confirmed", patient=self.patient).exists())

    def test_confirm_appointment_is_idempotent(self):
        tz = ZoneInfo("America/Los_Angeles")
        starts_at = timezone.make_aware(datetime.combine(self.target_date, time(9, 0)), tz)
        appointment = self._create_appointment(self.patient, starts_at=starts_at)
        self._login_patient()
        self.client.post(reverse("api-portal-appointment-confirm", kwargs={"appointment_id": appointment.pk}))
        appointment.refresh_from_db()
        first_confirmed_at = appointment.confirmed_at
        self.client.post(reverse("api-portal-appointment-confirm", kwargs={"appointment_id": appointment.pk}))
        appointment.refresh_from_db()
        self.assertEqual(appointment.confirmed_at, first_confirmed_at)
        self.assertEqual(AuditEvent.objects.filter(action="appointment.confirmed", patient=self.patient).count(), 1)

    def test_confirm_appointment_idor_is_blocked(self):
        tz = ZoneInfo("America/Los_Angeles")
        starts_at = timezone.make_aware(datetime.combine(self.target_date, time(9, 0)), tz)
        appointment = self._create_appointment(self.other_patient, starts_at=starts_at)
        self._login_patient()
        response = self.client.post(reverse("api-portal-appointment-confirm", kwargs={"appointment_id": appointment.pk}))
        self.assertEqual(response.status_code, 404)
        appointment.refresh_from_db()
        self.assertIsNone(appointment.confirmed_at)

    # --- waitlist: patient ------------------------------------------------

    def test_waitlist_join_and_list(self):
        self._login_patient()
        response = self.client.post(
            reverse("api-portal-waitlist"),
            data=json.dumps(
                {"locationId": str(self.location.pk), "earliestDate": self.target_date.isoformat(), "notes": "Mornings preferred"}
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        entries = self.client.get(reverse("api-portal-waitlist")).json()["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["notes"], "Mornings preferred")
        self.assertTrue(AuditEvent.objects.filter(action="waitlist.joined", patient=self.patient).exists())

    def test_waitlist_join_is_idempotent_for_same_preferences(self):
        self._login_patient()
        body = json.dumps({"locationId": str(self.location.pk), "earliestDate": self.target_date.isoformat()})
        first = self.client.post(reverse("api-portal-waitlist"), data=body, content_type="application/json")
        second = self.client.post(reverse("api-portal-waitlist"), data=body, content_type="application/json")
        self.assertEqual(first.json()["entry"]["id"], second.json()["entry"]["id"])
        self.assertEqual(Waitlist.objects.filter(patient=self.patient).count(), 1)

    def test_waitlist_leave(self):
        self._login_patient()
        join = self.client.post(
            reverse("api-portal-waitlist"),
            data=json.dumps({"earliestDate": self.target_date.isoformat()}), content_type="application/json",
        )
        entry_id = join.json()["entry"]["id"]
        response = self.client.post(reverse("api-portal-waitlist-leave", kwargs={"entry_id": entry_id}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Waitlist.objects.get(pk=entry_id).status, Waitlist.Status.CANCELLED)

    def test_waitlist_leave_idor_is_blocked(self):
        entry = Waitlist.objects.create(organization=self.organization, patient=self.other_patient, earliest_date=self.target_date)
        self._login_patient()
        response = self.client.post(reverse("api-portal-waitlist-leave", kwargs={"entry_id": entry.pk}))
        self.assertEqual(response.status_code, 404)
        entry.refresh_from_db()
        self.assertEqual(entry.status, Waitlist.Status.ACTIVE)

    # --- waitlist: staff -----------------------------------------------------

    def test_staff_waitlist_list_shows_active_entries_across_patients(self):
        Waitlist.objects.create(organization=self.organization, patient=self.patient, earliest_date=self.target_date)
        Waitlist.objects.create(
            organization=self.organization, patient=self.other_patient, earliest_date=self.target_date,
            status=Waitlist.Status.CANCELLED,
        )
        self.client.force_login(self.scheduler)
        response = self.client.get(reverse("api-waitlist-staff-list"))
        self.assertEqual(response.status_code, 200)
        entries = response.json()["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["patient"]["id"], str(self.patient.pk))

    def test_staff_waitlist_list_forbidden_for_biller(self):
        self.client.force_login(self.biller)
        response = self.client.get(reverse("api-waitlist-staff-list"))
        self.assertEqual(response.status_code, 403)

    def test_staff_can_mark_waitlist_entry_fulfilled(self):
        entry = Waitlist.objects.create(organization=self.organization, patient=self.patient, earliest_date=self.target_date)
        self.client.force_login(self.scheduler)
        response = self.client.post(
            reverse("api-waitlist-staff-update-status", kwargs={"entry_id": entry.pk}),
            data=json.dumps({"status": "fulfilled"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        entry.refresh_from_db()
        self.assertEqual(entry.status, Waitlist.Status.FULFILLED)

    def test_staff_waitlist_cross_tenant_is_blocked(self):
        other_org = Organization.objects.create(name="Other Sched Org", slug="other-sched-org")
        other_scheduler = User.objects.create_user(
            username="other-sched", password="safe-test-password", organization=other_org, role=User.Role.SCHEDULER,
        )
        entry = Waitlist.objects.create(organization=self.organization, patient=self.patient, earliest_date=self.target_date)
        self.client.force_login(other_scheduler)
        response = self.client.post(
            reverse("api-waitlist-staff-update-status", kwargs={"entry_id": entry.pk}),
            data=json.dumps({"status": "fulfilled"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)


class PatientPortalFormsTests(TestCase):
    """Patient Portal Phase 3: the reusable form engine (digital intake +
    HIPAA/privacy acknowledgment), e-signature, the Consent bridge, and
    self-reported insurance + card upload."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Portal Forms Clinic", slug="portal-forms-clinic")
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Portia", last_name="Forms", date_of_birth="1990-01-01",
        )
        self.portal_user = User.objects.create_user(
            username="portia-forms@example.test", password="portia-password-123",
            organization=self.organization, role=User.Role.PATIENT,
        )
        self.patient.portal_user = self.portal_user
        self.patient.save(update_fields=["portal_user"])

        self.other_patient = Patient.objects.create(
            organization=self.organization, first_name="Other", last_name="Forms", date_of_birth="1991-02-02",
        )
        self.other_portal_user = User.objects.create_user(
            username="other-forms@example.test", password="other-password-123",
            organization=self.organization, role=User.Role.PATIENT,
        )
        self.other_patient.portal_user = self.other_portal_user
        self.other_patient.save(update_fields=["portal_user"])

        self.payer = Payer.objects.create(organization=self.organization, name="Acme Health Plan")

        from care.form_engine import ensure_form_templates
        ensure_form_templates(self.organization)

    def _login(self):
        self.client.force_login(self.portal_user)

    def _save(self, slug, data):
        return self.client.post(
            reverse("api-portal-form-save", kwargs={"template_slug": slug}),
            data=json.dumps({"data": data}), content_type="application/json",
        )

    def _submit(self, slug, data):
        return self.client.post(
            reverse("api-portal-form-submit", kwargs={"template_slug": slug}),
            data=json.dumps({"data": data}), content_type="application/json",
        )

    INTAKE_COMPLETE_DATA = {
        "address": "123 Main St", "phone": "555-0100", "email": "portia@example.test",
        "emergencyName": "Sam Forms", "emergencyRelationship": "Spouse", "emergencyPhone": "555-0101",
        "painLocation": "Right knee", "agreeToTreatment": True, "signatureName": "Portia Forms",
    }

    # --- templates are auto-provisioned, listed, and scoped per patient ----

    def test_forms_list_shows_seeded_templates_not_started(self):
        self._login()
        response = self.client.get(reverse("api-portal-forms-list"))
        self.assertEqual(response.status_code, 200)
        slugs = {form["templateSlug"]: form["status"] for form in response.json()["forms"]}
        self.assertEqual(slugs.get("digital-intake"), "not_started")
        self.assertEqual(slugs.get("hipaa-privacy-acknowledgment"), "not_started")

    def test_unauthenticated_forms_list_is_rejected(self):
        response = self.client.get(reverse("api-portal-forms-list"))
        self.assertEqual(response.status_code, 401)

    def test_form_detail_returns_schema_and_working_submission(self):
        self._login()
        response = self.client.get(reverse("api-portal-form-detail", kwargs={"template_slug": "digital-intake"}))
        self.assertEqual(response.status_code, 200)
        body = response.json()["submission"]
        self.assertEqual(body["status"], "not_started")
        self.assertTrue(body["schema"])
        self.assertEqual(body["data"], {})

    def test_unknown_form_slug_is_404(self):
        self._login()
        response = self.client.get(reverse("api-portal-form-detail", kwargs={"template_slug": "not-a-real-form"}))
        self.assertEqual(response.status_code, 404)

    def test_two_patients_get_independent_submissions_for_the_same_template(self):
        self._login()
        self._save("digital-intake", {"phone": "555-1111"})
        self.client.force_login(self.other_portal_user)
        other_response = self.client.get(reverse("api-portal-form-detail", kwargs={"template_slug": "digital-intake"}))
        self.assertEqual(other_response.json()["submission"]["data"], {})
        self.assertEqual(FormSubmission.objects.filter(patient=self.patient, template__slug="digital-intake").count(), 1)
        self.assertEqual(FormSubmission.objects.filter(patient=self.other_patient, template__slug="digital-intake").count(), 1)

    # --- save progress -------------------------------------------------------

    def test_save_progress_marks_in_progress_and_persists_partial_data(self):
        self._login()
        response = self._save("digital-intake", {"phone": "555-1111", "email": "portia@example.test"})
        self.assertEqual(response.status_code, 200)
        body = response.json()["submission"]
        self.assertEqual(body["status"], "in_progress")
        self.assertEqual(body["data"]["phone"], "555-1111")

        # a second save merges rather than replacing
        self._save("digital-intake", {"address": "123 Main St"})
        submission = FormSubmission.objects.get(patient=self.patient, template__slug="digital-intake")
        self.assertEqual(submission.data["phone"], "555-1111")
        self.assertEqual(submission.data["address"], "123 Main St")

    def test_cannot_save_progress_on_a_completed_submission(self):
        self._login()
        self._submit("digital-intake", self.INTAKE_COMPLETE_DATA)
        response = self._save("digital-intake", {"phone": "555-9999"})
        self.assertEqual(response.status_code, 409)

    # --- submit / validation ---------------------------------------------

    def test_submit_rejects_missing_required_fields(self):
        self._login()
        response = self._submit("digital-intake", {"phone": "555-1111"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("email", response.json()["errors"])
        self.assertIn("signatureName", response.json()["errors"])

    def test_submit_succeeds_and_captures_signature(self):
        self._login()
        response = self._submit("digital-intake", self.INTAKE_COMPLETE_DATA)
        self.assertEqual(response.status_code, 200)
        body = response.json()["submission"]
        self.assertEqual(body["status"], "completed")
        self.assertIsNotNone(body["submittedAt"])
        submission = FormSubmission.objects.get(pk=body["id"])
        self.assertEqual(submission.signature_name, "Portia Forms")
        self.assertIsNotNone(submission.signed_at)
        self.assertIsNotNone(submission.signed_ip)
        self.assertTrue(
            AuditEvent.objects.filter(action="form.submitted", patient=self.patient).exists()
        )

    def test_submit_creates_a_consent_record_for_staff_visibility(self):
        self._login()
        self._submit("digital-intake", self.INTAKE_COMPLETE_DATA)
        consent = Consent.objects.filter(patient=self.patient, kind=Consent.Kind.TREATMENT).first()
        self.assertIsNotNone(consent)
        self.assertEqual(consent.signature_name, "Portia Forms")
        self.assertEqual(consent.recorded_by_id, self.portal_user.pk)
        self.assertEqual(consent.status, Consent.Status.SIGNED)

    def test_completed_intake_is_returned_read_only_on_next_visit(self):
        self._login()
        first = self._submit("digital-intake", self.INTAKE_COMPLETE_DATA)
        first_id = first.json()["submission"]["id"]
        detail = self.client.get(reverse("api-portal-form-detail", kwargs={"template_slug": "digital-intake"}))
        self.assertEqual(detail.json()["submission"]["id"], first_id)
        self.assertEqual(detail.json()["submission"]["status"], "completed")

    # --- expiration / never-overwrite-history ------------------------------

    def test_expired_completed_submission_yields_a_fresh_row_without_mutating_history(self):
        template = FormTemplate.objects.get(organization=self.organization, slug="hipaa-privacy-acknowledgment")
        old_submitted_at = timezone.now() - timedelta(days=400)
        expired = FormSubmission.objects.create(
            patient=self.patient, template=template, status=FormSubmission.Status.COMPLETED,
            data={"acknowledged": True, "signatureName": "Portia Forms"},
            submitted_at=old_submitted_at, signature_name="Portia Forms", signed_at=old_submitted_at,
        )
        self._login()
        detail = self.client.get(reverse("api-portal-form-detail", kwargs={"template_slug": "hipaa-privacy-acknowledgment"}))
        body = detail.json()["submission"]
        self.assertNotEqual(body["id"], str(expired.pk))
        self.assertEqual(body["status"], "not_started")

        expired.refresh_from_db()
        self.assertEqual(expired.status, FormSubmission.Status.COMPLETED)
        self.assertEqual(expired.data, {"acknowledged": True, "signatureName": "Portia Forms"})
        self.assertEqual(expired.submitted_at, old_submitted_at)

    def test_forms_overview_reports_expired_status_before_any_rollover(self):
        template = FormTemplate.objects.get(organization=self.organization, slug="hipaa-privacy-acknowledgment")
        old_submitted_at = timezone.now() - timedelta(days=400)
        FormSubmission.objects.create(
            patient=self.patient, template=template, status=FormSubmission.Status.COMPLETED,
            data={"acknowledged": True, "signatureName": "Portia Forms"}, submitted_at=old_submitted_at,
        )
        self._login()
        response = self.client.get(reverse("api-portal-forms-list"))
        forms_by_slug = {form["templateSlug"]: form for form in response.json()["forms"]}
        self.assertEqual(forms_by_slug["hipaa-privacy-acknowledgment"]["status"], "expired")

    def test_dashboard_forms_due_excludes_completed_and_includes_expired(self):
        self._login()
        self._submit("digital-intake", self.INTAKE_COMPLETE_DATA)  # completed, never expires
        response = self.client.get(reverse("api-portal-dashboard"))
        due_slugs = {form["templateSlug"] for form in response.json()["formsDue"]}
        self.assertNotIn("digital-intake", due_slugs)
        self.assertIn("hipaa-privacy-acknowledgment", due_slugs)

    # --- IDOR: forms are per-patient, never trusting a URL/body id ---------

    def test_staff_role_cannot_access_portal_forms(self):
        scheduler = User.objects.create_user(
            username="forms-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER,
        )
        self.client.force_login(scheduler)
        response = self.client.get(reverse("api-portal-forms-list"))
        self.assertEqual(response.status_code, 403)

    # --- self-reported insurance + card upload -----------------------------

    def _create_policy(self, **overrides):
        payload = {
            "payerId": str(self.payer.pk), "memberId": "MBR-001", "subscriberName": "Portia Forms",
        }
        payload.update(overrides)
        return self.client.post(
            reverse("api-portal-insurance"), data=json.dumps(payload), content_type="application/json",
        )

    def test_insurance_payers_list_is_scoped_to_organization(self):
        other_org = Organization.objects.create(name="Other Forms Org", slug="other-forms-org")
        Payer.objects.create(organization=other_org, name="Other Org Payer")
        self._login()
        response = self.client.get(reverse("api-portal-insurance-payers"))
        names = {payer["name"] for payer in response.json()["payers"]}
        self.assertIn("Acme Health Plan", names)
        self.assertNotIn("Other Org Payer", names)

    def test_patient_can_self_report_insurance(self):
        self._login()
        response = self._create_policy()
        self.assertEqual(response.status_code, 201)
        policy = PatientInsurance.objects.get(patient=self.patient)
        self.assertEqual(policy.member_id, "MBR-001")
        self.assertEqual(policy.rank, PatientInsurance.Rank.PRIMARY)
        self.assertTrue(
            AuditEvent.objects.filter(action="patient_insurance.self_reported", patient=self.patient).exists()
        )

    def test_resubmitting_the_same_rank_updates_in_place(self):
        self._login()
        self._create_policy()
        self._create_policy(memberId="MBR-002")
        self.assertEqual(PatientInsurance.objects.filter(patient=self.patient, rank=PatientInsurance.Rank.PRIMARY).count(), 1)
        self.assertEqual(PatientInsurance.objects.get(patient=self.patient).member_id, "MBR-002")

    def test_insurance_list_only_shows_own_policies(self):
        self._login()
        self._create_policy()
        self.client.force_login(self.other_portal_user)
        response = self.client.get(reverse("api-portal-insurance"))
        self.assertEqual(response.json()["policies"], [])

    def test_card_upload_and_download_round_trip(self):
        self._login()
        create_response = self._create_policy()
        policy_id = create_response.json()["policy"]["id"]
        image = SimpleUploadedFile("card.png", b"\x89PNG\r\n\x1a\n" + b"0" * 100, content_type="image/png")
        upload_response = self.client.post(
            reverse("api-portal-insurance-card-upload", kwargs={"policy_id": policy_id, "side": "front"}),
            data={"file": image},
        )
        self.assertEqual(upload_response.status_code, 201)
        self.assertTrue(upload_response.json()["policy"]["hasCardFront"])

        download_response = self.client.get(
            reverse("api-portal-insurance-card-download", kwargs={"policy_id": policy_id, "side": "front"})
        )
        self.assertEqual(download_response.status_code, 200)

    def test_card_upload_idor_is_blocked(self):
        self._login()
        create_response = self._create_policy()
        policy_id = create_response.json()["policy"]["id"]
        self.client.force_login(self.other_portal_user)
        image = SimpleUploadedFile("card.png", b"\x89PNG\r\n\x1a\n" + b"0" * 100, content_type="image/png")
        response = self.client.post(
            reverse("api-portal-insurance-card-upload", kwargs={"policy_id": policy_id, "side": "front"}),
            data={"file": image},
        )
        self.assertEqual(response.status_code, 404)

    # --- staff visibility into a patient's submitted digital forms ---------

    def test_staff_can_view_a_completed_form_submissions_answers(self):
        self._login()
        submit_response = self._submit("digital-intake", self.INTAKE_COMPLETE_DATA)
        submission_id = submit_response.json()["submission"]["id"]
        scheduler = User.objects.create_user(
            username="forms-viewer-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER,
        )
        self.client.force_login(scheduler)
        response = self.client.get(reverse("api-form-submission-detail", kwargs={"patient_id": self.patient.pk, "submission_id": submission_id}))
        self.assertEqual(response.status_code, 200)
        body = response.json()["submission"]
        self.assertEqual(body["data"]["painLocation"], "Right knee")
        self.assertTrue(body["schema"])
        self.assertTrue(
            AuditEvent.objects.filter(action="form.viewed", patient=self.patient).exists()
        )

    def test_workspace_lists_form_submissions_without_answers(self):
        self._login()
        self._submit("digital-intake", self.INTAKE_COMPLETE_DATA)
        scheduler = User.objects.create_user(
            username="forms-list-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER,
        )
        self.client.force_login(scheduler)
        response = self.client.get(reverse("api-patient-workspace", kwargs={"patient_id": self.patient.pk}))
        submissions = response.json()["operations"]["formSubmissions"]
        self.assertEqual(len(submissions), 1)
        self.assertNotIn("data", submissions[0])

    def test_staff_cannot_view_another_patients_form_submission(self):
        self._login()
        submit_response = self._submit("digital-intake", self.INTAKE_COMPLETE_DATA)
        submission_id = submit_response.json()["submission"]["id"]
        scheduler = User.objects.create_user(
            username="forms-cross-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER,
        )
        self.client.force_login(scheduler)
        response = self.client.get(reverse("api-form-submission-detail", kwargs={"patient_id": self.other_patient.pk, "submission_id": submission_id}))
        self.assertEqual(response.status_code, 404)

    def test_biller_cannot_view_form_submission_detail(self):
        self._login()
        submit_response = self._submit("digital-intake", self.INTAKE_COMPLETE_DATA)
        submission_id = submit_response.json()["submission"]["id"]
        biller = User.objects.create_user(
            username="forms-detail-biller", password="safe-test-password", organization=self.organization, role=User.Role.BILLER,
        )
        self.client.force_login(biller)
        response = self.client.get(reverse("api-form-submission-detail", kwargs={"patient_id": self.patient.pk, "submission_id": submission_id}))
        self.assertEqual(response.status_code, 403)


class PatientPortalDocumentsAndHepTests(TestCase):
    """Patient Portal Phase 4: documents (patient sees only what's explicitly
    shared, plus their own uploads) and the home exercise program (view,
    mark completed with pain/difficulty/comment, adherence tracking)."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Portal Docs HEP Clinic", slug="portal-docs-hep-clinic")
        self.therapist = User.objects.create_user(
            username="docs-hep-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        self.scheduler = User.objects.create_user(
            username="docs-hep-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER,
        )
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Portia", last_name="Docs", date_of_birth="1990-01-01",
            assigned_therapist=self.therapist,
        )
        self.portal_user = User.objects.create_user(
            username="portia-docs@example.test", password="portia-password-123",
            organization=self.organization, role=User.Role.PATIENT,
        )
        self.patient.portal_user = self.portal_user
        self.patient.save(update_fields=["portal_user"])

        self.other_patient = Patient.objects.create(
            organization=self.organization, first_name="Other", last_name="Docs", date_of_birth="1991-02-02",
            assigned_therapist=self.therapist,
        )
        self.other_portal_user = User.objects.create_user(
            username="other-docs@example.test", password="other-password-123",
            organization=self.organization, role=User.Role.PATIENT,
        )
        self.other_patient.portal_user = self.other_portal_user
        self.other_patient.save(update_fields=["portal_user"])

        self.program = HomeProgram.objects.create(
            patient=self.patient, prescribed_by=self.therapist, title="Knee protocol",
            patient_instructions="Do these daily.", status=HomeProgram.Status.ACTIVE,
        )
        self.exercise = HomeExercise.objects.create(
            home_program=self.program, name="Quad sets", instructions="Tighten thigh, hold 5s.", dosage="3x10",
            video_url="https://example.test/videos/quad-sets",
        )

    def _login(self):
        self.client.force_login(self.portal_user)

    # --- staff document upload / visibility -----------------------------

    def _staff_upload(self, **overrides):
        self.client.force_login(self.therapist)
        upload = SimpleUploadedFile("report.pdf", b"%PDF-1.4 fake", content_type="application/pdf")
        data = {"file": upload, "title": "Imaging report"}
        data.update(overrides)
        return self.client.post(reverse("api-patient-documents", kwargs={"patient_id": self.patient.pk}), data=data)

    def test_staff_upload_defaults_hidden_from_portal(self):
        response = self._staff_upload()
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.json()["document"]["visibleToPatient"])
        self._login()
        portal_response = self.client.get(reverse("api-portal-documents"))
        self.assertEqual(portal_response.json()["documents"], [])

    def test_staff_upload_with_visible_to_patient_shows_in_portal(self):
        response = self._staff_upload(visibleToPatient="true")
        self.assertTrue(response.json()["document"]["visibleToPatient"])
        self._login()
        portal_response = self.client.get(reverse("api-portal-documents"))
        documents = portal_response.json()["documents"]
        self.assertEqual(len(documents), 1)
        self.assertFalse(documents[0]["uploadedByPatient"])

    def test_staff_can_toggle_visibility_after_upload(self):
        upload_response = self._staff_upload()
        document_id = upload_response.json()["document"]["id"]
        response = self.client.patch(
            reverse("api-patient-document-visibility", kwargs={"patient_id": self.patient.pk, "document_id": document_id}),
            data=json.dumps({"visibleToPatient": True}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["document"]["visibleToPatient"])
        self._login()
        portal_response = self.client.get(reverse("api-portal-documents"))
        self.assertEqual(len(portal_response.json()["documents"]), 1)

    # --- patient documents -------------------------------------------------

    def test_patient_can_upload_own_document(self):
        self._login()
        upload = SimpleUploadedFile("outside-imaging.pdf", b"%PDF-1.4 fake", content_type="application/pdf")
        response = self.client.post(reverse("api-portal-documents"), data={"file": upload, "title": "MRI from outside clinic"})
        self.assertEqual(response.status_code, 201)
        body = response.json()["document"]
        self.assertTrue(body["uploadedByPatient"])
        list_response = self.client.get(reverse("api-portal-documents"))
        self.assertEqual(len(list_response.json()["documents"]), 1)

    def test_patient_document_list_never_shows_another_patients_document(self):
        PatientDocument.objects.create(
            patient=self.other_patient, uploaded_by=self.therapist, file=SimpleUploadedFile("x.pdf", b"x"),
            original_filename="x.pdf", title="Other patient doc", size_bytes=1, visible_to_patient=True,
        )
        self._login()
        response = self.client.get(reverse("api-portal-documents"))
        self.assertEqual(response.json()["documents"], [])

    def test_patient_document_download_idor_is_blocked(self):
        document = PatientDocument.objects.create(
            patient=self.other_patient, uploaded_by=self.therapist, file=SimpleUploadedFile("x.pdf", b"x"),
            original_filename="x.pdf", title="Other patient doc", size_bytes=1, visible_to_patient=True,
        )
        self._login()
        response = self.client.get(reverse("api-portal-document-download", kwargs={"document_id": document.pk}))
        self.assertEqual(response.status_code, 404)

    def test_patient_cannot_download_a_hidden_staff_document(self):
        upload_response = self._staff_upload()
        document_id = upload_response.json()["document"]["id"]
        self._login()
        response = self.client.get(reverse("api-portal-document-download", kwargs={"document_id": document_id}))
        self.assertEqual(response.status_code, 404)

    def test_dashboard_recent_documents_only_shows_visible(self):
        self._staff_upload()  # hidden
        self._staff_upload(visibleToPatient="true", title="Shared doc")
        self._login()
        response = self.client.get(reverse("api-portal-dashboard"))
        titles = [d["title"] for d in response.json()["recentDocuments"]]
        self.assertEqual(titles, ["Shared doc"])

    # --- staff exercise CRUD ------------------------------------------------

    def test_staff_can_create_exercise_on_active_program(self):
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-home-exercise-create", kwargs={"program_id": self.program.pk}),
            data=json.dumps({"name": "Heel slides", "instructions": "Slide heel toward buttock.", "dosage": "2x15", "videoUrl": "https://example.test/heel-slides"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.program.exercises.count(), 2)

    def test_staff_can_update_exercise(self):
        self.client.force_login(self.therapist)
        response = self.client.patch(
            reverse("api-home-exercise-update", kwargs={"program_id": self.program.pk, "exercise_id": self.exercise.pk}),
            data=json.dumps({"dosage": "4x12"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.exercise.refresh_from_db()
        self.assertEqual(self.exercise.dosage, "4x12")

    def test_scheduler_cannot_create_exercise(self):
        self.client.force_login(self.scheduler)
        response = self.client.post(
            reverse("api-home-exercise-create", kwargs={"program_id": self.program.pk}),
            data=json.dumps({"name": "X", "instructions": "Y", "dosage": "1x1"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    # --- patient HEP view ----------------------------------------------------

    def test_portal_hep_returns_active_program_with_exercises(self):
        self._login()
        response = self.client.get(reverse("api-portal-hep"))
        self.assertEqual(response.status_code, 200)
        program = response.json()["program"]
        self.assertEqual(program["title"], "Knee protocol")
        self.assertEqual(len(program["exercises"]), 1)
        self.assertEqual(program["exercises"][0]["videoUrl"], "https://example.test/videos/quad-sets")
        self.assertIsNone(program["exercises"][0]["lastCompletedAt"])

    def test_portal_hep_returns_none_when_no_active_program(self):
        self.program.status = HomeProgram.Status.DRAFT
        self.program.save(update_fields=["status"])
        self._login()
        response = self.client.get(reverse("api-portal-hep"))
        self.assertIsNone(response.json()["program"])

    def test_portal_hep_blocked_when_feature_disabled(self):
        plan = SubscriptionPlan.objects.create(code="no-hep-plan", name="No HEP Plan", provider_seat_limit=5)
        other_feature = Feature.objects.create(code="billing", name="Billing")
        plan.features.add(other_feature)
        subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=plan, status=OrganizationSubscription.Status.ACTIVE,
        )
        subscription.features.add(other_feature)
        self._login()
        response = self.client.get(reverse("api-portal-hep"))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["program"])

    # --- completing an exercise -----------------------------------------

    def test_complete_exercise_records_log_with_pain_and_difficulty(self):
        self._login()
        response = self.client.post(
            reverse("api-portal-hep-complete", kwargs={"exercise_id": self.exercise.pk}),
            data=json.dumps({"painLevel": 3, "difficultyLevel": 5, "comment": "Felt tight today"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        log = HomeExerciseLog.objects.get(patient=self.patient)
        self.assertEqual(log.pain_level, 3)
        self.assertEqual(log.difficulty_level, 5)
        self.assertEqual(log.comment, "Felt tight today")
        self.assertTrue(
            AuditEvent.objects.filter(action="home_exercise.completed", patient=self.patient).exists()
        )

    def test_complete_exercise_allows_omitted_pain_and_difficulty(self):
        self._login()
        response = self.client.post(
            reverse("api-portal-hep-complete", kwargs={"exercise_id": self.exercise.pk}),
            data=json.dumps({}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)

    def test_complete_exercise_rejects_out_of_range_pain_level(self):
        self._login()
        response = self.client.post(
            reverse("api-portal-hep-complete", kwargs={"exercise_id": self.exercise.pk}),
            data=json.dumps({"painLevel": 15}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)

    def test_complete_exercise_idor_is_blocked(self):
        self.client.force_login(self.other_portal_user)
        response = self.client.post(
            reverse("api-portal-hep-complete", kwargs={"exercise_id": self.exercise.pk}),
            data=json.dumps({}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(HomeExerciseLog.objects.count(), 0)

    def test_last_completed_at_reflects_most_recent_log(self):
        self._login()
        self.client.post(
            reverse("api-portal-hep-complete", kwargs={"exercise_id": self.exercise.pk}),
            data=json.dumps({}), content_type="application/json",
        )
        response = self.client.get(reverse("api-portal-hep"))
        self.assertIsNotNone(response.json()["program"]["exercises"][0]["lastCompletedAt"])

    def test_completions_last_7_days_count_is_accurate(self):
        self._login()
        HomeExerciseLog.objects.create(patient=self.patient, home_exercise=self.exercise, completed_at=timezone.now() - timedelta(days=10))
        self.client.post(
            reverse("api-portal-hep-complete", kwargs={"exercise_id": self.exercise.pk}),
            data=json.dumps({}), content_type="application/json",
        )
        response = self.client.get(reverse("api-portal-hep"))
        self.assertEqual(response.json()["program"]["completionsLast7Days"], 1)

    def test_hep_logs_history_lists_own_completions_only(self):
        HomeExerciseLog.objects.create(patient=self.other_patient, home_exercise=HomeExercise.objects.create(
            home_program=HomeProgram.objects.create(
                patient=self.other_patient, prescribed_by=self.therapist, title="Other program",
                patient_instructions="x", status=HomeProgram.Status.ACTIVE,
            ), name="Other exercise", instructions="x", dosage="1x1",
        ))
        self._login()
        self.client.post(
            reverse("api-portal-hep-complete", kwargs={"exercise_id": self.exercise.pk}),
            data=json.dumps({}), content_type="application/json",
        )
        response = self.client.get(reverse("api-portal-hep-logs"))
        logs = response.json()["logs"]
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["exerciseName"], "Quad sets")


class OutcomeScoringEngineTests(TestCase):
    """Unit tests for care/outcome_scoring.py — pure scoring math, no HTTP."""

    def test_lefs_perfect_and_worst_scores(self):
        from care.outcome_scoring import score_outcome_measure

        best = {f"item_{i}": 4 for i in range(20)}
        worst = {f"item_{i}": 0 for i in range(20)}
        self.assertEqual(score_outcome_measure("lefs", best), (Decimal("80.00"), Decimal("80.00")))
        self.assertEqual(score_outcome_measure("lefs", worst), (Decimal("0.00"), Decimal("80.00")))

    def test_quickdash_scores(self):
        from care.outcome_scoring import score_outcome_measure

        no_difficulty = {f"item_{i}": 1 for i in range(11)}
        unable = {f"item_{i}": 5 for i in range(11)}
        self.assertEqual(score_outcome_measure("quickdash", no_difficulty), (Decimal("0.00"), Decimal("100.00")))
        self.assertEqual(score_outcome_measure("quickdash", unable), (Decimal("100.00"), Decimal("100.00")))

    def test_odi_and_ndi_percentage_scoring(self):
        from care.outcome_scoring import score_outcome_measure, _ODI_SECTIONS, _NDI_SECTIONS

        no_disability = {section["key"]: 0 for section in _ODI_SECTIONS}
        full_disability = {section["key"]: 5 for section in _ODI_SECTIONS}
        self.assertEqual(score_outcome_measure("odi", no_disability), (Decimal("0.00"), Decimal("100.00")))
        self.assertEqual(score_outcome_measure("odi", full_disability), (Decimal("100.00"), Decimal("100.00")))
        half_ndi = {section["key"]: 2 for section in _NDI_SECTIONS}  # not exactly half but a real mid-range check
        score, maximum = score_outcome_measure("ndi", half_ndi)
        self.assertEqual(maximum, Decimal("100.00"))
        self.assertEqual(score, Decimal("40.00"))  # (2*10)/(5*10) * 100

    def test_psfs_averages_patient_defined_activities(self):
        from care.outcome_scoring import score_outcome_measure

        responses = {"activities": [{"name": "Squatting", "rating": 6}, {"name": "Stairs", "rating": 8}]}
        score, maximum = score_outcome_measure("psfs", responses)
        self.assertEqual(score, Decimal("7.00"))
        self.assertEqual(maximum, Decimal("10.00"))

    def test_validate_outcome_responses_rejects_missing_items(self):
        from care.outcome_scoring import validate_outcome_responses

        errors = validate_outcome_responses("lefs", {})
        self.assertEqual(len(errors), 20)

    def test_validate_psfs_rejects_too_many_activities(self):
        from care.outcome_scoring import validate_outcome_responses

        responses = {"activities": [{"name": f"A{i}", "rating": 5} for i in range(6)]}
        errors = validate_outcome_responses("psfs", responses)
        self.assertIn("activities", errors)

    def test_tug_and_berg_are_excluded_from_self_report(self):
        from care.outcome_scoring import PATIENT_SELF_REPORT_MEASURES

        self.assertNotIn(OutcomeScore.Measure.TUG, PATIENT_SELF_REPORT_MEASURES)
        self.assertNotIn(OutcomeScore.Measure.BERG, PATIENT_SELF_REPORT_MEASURES)


class PatientPortalOutcomesAndMessagingTests(TestCase):
    """Patient Portal Phase 5: staff-assigned outcome measures (patient
    self-completes, backend auto-scores) and secure messaging (category
    routing, content-free notifications, mark-as-read)."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Portal Outcomes Msg Clinic", slug="portal-outcomes-msg-clinic")
        self.therapist = User.objects.create_user(
            username="om-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
            first_name="Terry", last_name="Therapist", email="terry@example.test",
        )
        self.scheduler = User.objects.create_user(
            username="om-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER,
            first_name="Sam", last_name="Scheduler", email="sam@example.test",
        )
        self.biller = User.objects.create_user(
            username="om-biller", password="safe-test-password", organization=self.organization, role=User.Role.BILLER,
            first_name="Bella", last_name="Biller", email="bella@example.test",
        )
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Portia", last_name="Outcomes", date_of_birth="1990-01-01",
            assigned_therapist=self.therapist,
        )
        self.portal_user = User.objects.create_user(
            username="portia-outcomes@example.test", password="portia-password-123",
            organization=self.organization, role=User.Role.PATIENT, email="portia-outcomes@example.test",
        )
        self.patient.portal_user = self.portal_user
        self.patient.save(update_fields=["portal_user"])

        self.other_patient = Patient.objects.create(
            organization=self.organization, first_name="Other", last_name="Outcomes", date_of_birth="1991-02-02",
            assigned_therapist=self.therapist,
        )
        self.other_portal_user = User.objects.create_user(
            username="other-outcomes@example.test", password="other-password-123",
            organization=self.organization, role=User.Role.PATIENT, email="other-outcomes@example.test",
        )
        self.other_patient.portal_user = self.other_portal_user
        self.other_patient.save(update_fields=["portal_user"])

    def _login(self):
        self.client.force_login(self.portal_user)

    # --- staff assignment -----------------------------------------------

    def _assign(self, measure="lefs"):
        self.client.force_login(self.therapist)
        return self.client.post(
            reverse("api-outcome-assignment-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"measure": measure}), content_type="application/json",
        )

    def test_staff_can_assign_a_self_report_measure(self):
        response = self._assign("lefs")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["assignment"]["status"], "pending")
        self.assertTrue(
            AuditEvent.objects.filter(action="outcome_assignment.created", patient=self.patient).exists()
        )

    def test_staff_cannot_assign_a_clinician_administered_measure(self):
        response = self._assign("tug")
        self.assertEqual(response.status_code, 400)

    def test_scheduler_cannot_assign_outcome_measures(self):
        self.client.force_login(self.scheduler)
        response = self.client.post(
            reverse("api-outcome-assignment-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"measure": "lefs"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_staff_sees_assignment_in_workspace(self):
        self._assign("lefs")
        self.client.force_login(self.therapist)
        response = self.client.get(reverse("api-patient-workspace", kwargs={"patient_id": self.patient.pk}))
        assignments = response.json()["clinical"]["outcomeAssignments"]
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0]["measureLabel"], "LEFS")

    # --- portal: view + complete -------------------------------------------

    def test_portal_outcomes_list_and_dashboard_show_pending_assignment(self):
        self._assign("lefs")
        self._login()
        response = self.client.get(reverse("api-portal-outcomes-list"))
        self.assertEqual(len(response.json()["assignments"]), 1)
        dashboard = self.client.get(reverse("api-portal-dashboard"))
        self.assertEqual(len(dashboard.json()["outcomeMeasuresDue"]), 1)

    def test_portal_outcome_detail_returns_schema(self):
        assign_response = self._assign("lefs")
        assignment_id = assign_response.json()["assignment"]["id"]
        self._login()
        response = self.client.get(reverse("api-portal-outcome-detail", kwargs={"assignment_id": assignment_id}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["schema"]["items"]), 20)

    def test_submit_lefs_auto_scores_and_completes_assignment(self):
        assign_response = self._assign("lefs")
        assignment_id = assign_response.json()["assignment"]["id"]
        self._login()
        response = self.client.post(
            reverse("api-portal-outcome-submit", kwargs={"assignment_id": assignment_id}),
            data=json.dumps({"itemResponses": {f"item_{i}": 4 for i in range(20)}}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["score"], "80.00")
        self.assertEqual(response.json()["assignment"]["status"], "completed")
        outcome = OutcomeScore.objects.get(patient=self.patient, measure="lefs")
        self.assertEqual(outcome.recorded_by_id, self.portal_user.pk)
        self.assertEqual(outcome.item_responses, {f"item_{i}": 4 for i in range(20)})
        self.assertTrue(
            AuditEvent.objects.filter(action="outcome_assignment.completed", patient=self.patient).exists()
        )

    def test_submit_rejects_incomplete_responses(self):
        assign_response = self._assign("lefs")
        assignment_id = assign_response.json()["assignment"]["id"]
        self._login()
        response = self.client.post(
            reverse("api-portal-outcome-submit", kwargs={"assignment_id": assignment_id}),
            data=json.dumps({"itemResponses": {"item_0": 4}}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(len(response.json()["errors"]), 19)

    def test_cannot_resubmit_a_completed_assignment(self):
        assign_response = self._assign("lefs")
        assignment_id = assign_response.json()["assignment"]["id"]
        self._login()
        self.client.post(
            reverse("api-portal-outcome-submit", kwargs={"assignment_id": assignment_id}),
            data=json.dumps({"itemResponses": {f"item_{i}": 4 for i in range(20)}}), content_type="application/json",
        )
        response = self.client.post(
            reverse("api-portal-outcome-submit", kwargs={"assignment_id": assignment_id}),
            data=json.dumps({"itemResponses": {f"item_{i}": 4 for i in range(20)}}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)

    def test_outcome_assignment_idor_is_blocked(self):
        assign_response = self._assign("lefs")
        assignment_id = assign_response.json()["assignment"]["id"]
        self.client.force_login(self.other_portal_user)
        response = self.client.get(reverse("api-portal-outcome-detail", kwargs={"assignment_id": assignment_id}))
        self.assertEqual(response.status_code, 404)
        response = self.client.post(
            reverse("api-portal-outcome-submit", kwargs={"assignment_id": assignment_id}),
            data=json.dumps({"itemResponses": {}}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_psfs_submission_scores_average_of_activities(self):
        assign_response = self._assign("psfs")
        assignment_id = assign_response.json()["assignment"]["id"]
        self._login()
        response = self.client.post(
            reverse("api-portal-outcome-submit", kwargs={"assignment_id": assignment_id}),
            data=json.dumps({"itemResponses": {"activities": [{"name": "Squat", "rating": 6}, {"name": "Stairs", "rating": 8}]}}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["score"], "7.00")

    # --- secure messaging: staff side --------------------------------------

    def test_staff_message_defaults_to_general_category(self):
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-secure-message-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"recipientId": str(self.portal_user.pk), "subject": "Hi", "body": "How are you feeling?"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["message"]["category"], "general")

    def test_staff_message_to_patient_sends_content_free_notification(self):
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-secure-message-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"recipientId": str(self.portal_user.pk), "category": "clinical", "subject": "Confidential subject", "body": "Confidential body content"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, [self.portal_user.email])
        self.assertNotIn("Confidential subject", sent.body)
        self.assertNotIn("Confidential body content", sent.body)
        self.assertNotIn("Confidential subject", sent.subject)

    def test_operations_workspace_recipients_exclude_other_patients_but_include_this_one(self):
        self.client.force_login(self.therapist)
        response = self.client.get(reverse("api-patient-workspace", kwargs={"patient_id": self.patient.pk}))
        recipient_ids = {r["id"] for r in response.json()["operations"]["recipients"]}
        self.assertIn(str(self.portal_user.pk), recipient_ids)
        self.assertNotIn(str(self.other_portal_user.pk), recipient_ids)

    # --- secure messaging: portal side --------------------------------------

    def test_patient_can_send_clinical_message_routed_to_assigned_therapist(self):
        self._login()
        response = self.client.post(
            reverse("api-portal-messages"),
            data=json.dumps({"category": "clinical", "subject": "Knee pain", "body": "My knee still hurts after the last visit."}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        message = SecureMessage.objects.get(patient=self.patient)
        self.assertEqual(message.recipient_id, self.therapist.pk)
        self.assertEqual(message.sender_id, self.portal_user.pk)

    def test_patient_billing_message_routes_to_biller(self):
        self._login()
        response = self.client.post(
            reverse("api-portal-messages"),
            data=json.dumps({"category": "billing", "subject": "Invoice question", "body": "Can you explain my last invoice?"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        message = SecureMessage.objects.get(patient=self.patient)
        self.assertEqual(message.recipient_id, self.biller.pk)

    def test_patient_message_sends_content_free_notification_to_staff(self):
        self._login()
        self.client.post(
            reverse("api-portal-messages"),
            data=json.dumps({"category": "clinical", "subject": "Private subject", "body": "Private body"}),
            content_type="application/json",
        )
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, [self.therapist.email])
        self.assertNotIn("Private subject", sent.body)
        self.assertNotIn("Private body", sent.body)

    def test_patient_message_list_shows_both_directions(self):
        self._login()
        self.client.post(
            reverse("api-portal-messages"),
            data=json.dumps({"category": "general", "subject": "Question", "body": "When is my next visit?"}),
            content_type="application/json",
        )
        self.client.force_login(self.therapist)
        self.client.post(
            reverse("api-secure-message-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"recipientId": str(self.portal_user.pk), "subject": "Re: Question", "body": "Next Tuesday at 10am."}),
            content_type="application/json",
        )
        self._login()
        response = self.client.get(reverse("api-portal-messages"))
        messages = response.json()["messages"]
        self.assertEqual(len(messages), 2)
        directions = {m["direction"] for m in messages}
        self.assertEqual(directions, {"inbound", "outbound"})

    def test_mark_message_read_updates_dashboard_unread_count(self):
        self.client.force_login(self.therapist)
        send_response = self.client.post(
            reverse("api-secure-message-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"recipientId": str(self.portal_user.pk), "subject": "Hi", "body": "Checking in."}),
            content_type="application/json",
        )
        message_id = send_response.json()["message"]["id"]
        self._login()
        dashboard_before = self.client.get(reverse("api-portal-dashboard"))
        self.assertEqual(dashboard_before.json()["newMessageCount"], 1)
        self.assertEqual(len(dashboard_before.json()["notifications"]), 1)

        response = self.client.post(reverse("api-portal-message-read", kwargs={"message_id": message_id}))
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()["message"]["readAt"])

        dashboard_after = self.client.get(reverse("api-portal-dashboard"))
        self.assertEqual(dashboard_after.json()["newMessageCount"], 0)
        self.assertEqual(len(dashboard_after.json()["notifications"]), 0)

    def test_message_read_idor_is_blocked(self):
        self.client.force_login(self.therapist)
        send_response = self.client.post(
            reverse("api-secure-message-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"recipientId": str(self.portal_user.pk), "subject": "Hi", "body": "Checking in."}),
            content_type="application/json",
        )
        message_id = send_response.json()["message"]["id"]
        self.client.force_login(self.other_portal_user)
        response = self.client.post(reverse("api-portal-message-read", kwargs={"message_id": message_id}))
        self.assertEqual(response.status_code, 404)

    def test_dashboard_notifications_never_include_subject_or_body(self):
        self.client.force_login(self.therapist)
        self.client.post(
            reverse("api-secure-message-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"recipientId": str(self.portal_user.pk), "subject": "Very private subject", "body": "Very private body"}),
            content_type="application/json",
        )
        self._login()
        response = self.client.get(reverse("api-portal-dashboard"))
        payload_text = json.dumps(response.json())
        self.assertNotIn("Very private subject", payload_text)
        self.assertNotIn("Very private body", payload_text)


class PatientPortalPaymentsSuperbillTelehealthTests(TestCase):
    """Patient Portal Phase 6: combined balance/statements/receipts, an
    honest (never-fabricated) online-payment attempt via
    care/payment_processor.py, read-only superbill download, and telehealth
    join eligibility + an honest care/telehealth.py session attempt."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Portal Payments Clinic", slug="portal-payments-clinic")
        self.therapist = User.objects.create_user(
            username="pay-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        self.biller = User.objects.create_user(
            username="pay-biller", password="safe-test-password", organization=self.organization, role=User.Role.BILLER,
        )
        self.location = Location.objects.create(organization=self.organization, name="Payments Location")

        billing_feature = Feature.objects.create(code="billing", name="Billing")
        telehealth_feature = Feature.objects.create(code="telehealth", name="Telehealth")
        plan = SubscriptionPlan.objects.create(code="portal-pay-plan", name="Portal Pay Plan", provider_seat_limit=10)
        plan.features.add(billing_feature, telehealth_feature)
        subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=plan, status=OrganizationSubscription.Status.ACTIVE,
        )
        subscription.features.add(billing_feature, telehealth_feature)

        self.payer = Payer.objects.create(organization=self.organization, name="Portal Payer", timely_filing_days=365)
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Portia", last_name="Payments", date_of_birth="1990-01-01",
            assigned_therapist=self.therapist, address="1 Portal Way",
        )
        self.policy = PatientInsurance.objects.create(
            organization=self.organization, patient=self.patient, payer=self.payer,
            member_id="MBR-PORTAL-1", effective_date=date.today() - timedelta(days=365),
        )
        self.portal_user = User.objects.create_user(
            username="portia-payments@example.test", password="portia-password-123",
            organization=self.organization, role=User.Role.PATIENT,
        )
        self.patient.portal_user = self.portal_user
        self.patient.save(update_fields=["portal_user"])

        self.other_patient = Patient.objects.create(
            organization=self.organization, first_name="Other", last_name="Payments", date_of_birth="1991-02-02",
        )
        self.other_portal_user = User.objects.create_user(
            username="other-payments@example.test", password="other-password-123",
            organization=self.organization, role=User.Role.PATIENT,
        )
        self.other_patient.portal_user = self.other_portal_user
        self.other_patient.save(update_fields=["portal_user"])

    def _login(self):
        self.client.force_login(self.portal_user)

    def _make_submitted_claim(self, *, amount="100.00"):
        charge = Charge.objects.create(
            organization=self.organization, patient=self.patient, provider=self.therapist, location=self.location,
            service_date=date.today(), cpt_code="97110", units=1, charge_amount=amount,
        )
        claim = Claim.objects.create(
            organization=self.organization, patient=self.patient, patient_insurance=self.policy, payer=self.payer,
            diagnosis_code_list=[], status=Claim.Status.SUBMITTED,
        )
        charge.claim = claim
        charge.save(update_fields=["claim"])
        return claim

    def _make_superbill(self, *, amount="75.00", status=Superbill.Status.READY):
        return Superbill.objects.create(
            patient=self.patient, clinician=self.therapist, service_date=date.today(), codes=["97110"],
            amount=amount, status=status,
        )

    # --- balance / statements / receipts ------------------------------------

    def test_combined_balance_sums_insurance_and_cash(self):
        self._make_submitted_claim(amount="100.00")
        self._make_superbill(amount="75.00")
        self._login()
        response = self.client.get(reverse("api-portal-payments"))
        body = response.json()
        self.assertEqual(body["insuranceBalance"], "100.00")
        self.assertEqual(body["cashBalance"], "75.00")
        self.assertEqual(body["totalBalance"], "175.00")

    def test_paid_superbill_excluded_from_cash_balance(self):
        self._make_superbill(amount="75.00", status=Superbill.Status.PAID)
        self._login()
        response = self.client.get(reverse("api-portal-payments"))
        self.assertEqual(response.json()["cashBalance"], "0.00")

    def test_dashboard_outstanding_balance_matches_combined_total(self):
        self._make_submitted_claim(amount="50.00")
        self._make_superbill(amount="25.00")
        self._login()
        response = self.client.get(reverse("api-portal-dashboard"))
        self.assertEqual(response.json()["outstandingBalance"], "75.00")

    def test_statement_detail_is_scoped_to_own_patient(self):
        statement = PatientStatement.objects.create(
            organization=self.organization, patient=self.patient, due_date=date.today() + timedelta(days=30),
            balance_at_generation=Decimal("100.00"), generated_by=self.biller,
        )
        self._login()
        response = self.client.get(reverse("api-portal-statement-detail", kwargs={"statement_id": statement.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["statement"]["statementId"], str(statement.pk))

        self.client.force_login(self.other_portal_user)
        response = self.client.get(reverse("api-portal-statement-detail", kwargs={"statement_id": statement.pk}))
        self.assertEqual(response.status_code, 404)

    def test_receipts_only_show_received_payments(self):
        superbill = self._make_superbill()
        PaymentRecord.objects.create(
            patient=self.patient, superbill=superbill, recorded_by=self.biller, amount=Decimal("50.00"),
            status=PaymentRecord.Status.RECEIVED, payment_processor_reference="REF-1",
        )
        PaymentRecord.objects.create(
            patient=self.patient, superbill=superbill, recorded_by=self.biller, amount=Decimal("25.00"),
            status=PaymentRecord.Status.PENDING, payment_processor_reference="REF-2",
        )
        self._login()
        response = self.client.get(reverse("api-portal-payments"))
        receipts = response.json()["receipts"]
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["amount"], "50.00")

    # --- online payment attempt (always honest, never fabricated) ----------

    def test_online_payment_attempt_is_honestly_recorded_as_failed(self):
        self._login()
        response = self.client.post(
            reverse("api-portal-payment-charge"), data=json.dumps({"amount": "40.00"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["succeeded"])
        self.assertIn("not yet connected", body["message"])
        payment = PatientPayment.objects.get(patient=self.patient)
        self.assertEqual(payment.status, PatientPayment.Status.FAILED)
        self.assertEqual(str(payment.amount), "40.00")
        self.assertTrue(
            AuditEvent.objects.filter(action="patient_payment.attempted", patient=self.patient).exists()
        )

    def test_online_payment_rejects_non_positive_amount(self):
        self._login()
        response = self.client.post(
            reverse("api-portal-payment-charge"), data=json.dumps({"amount": "0"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(PatientPayment.objects.count(), 0)

    def test_online_payment_blocked_when_billing_feature_disabled(self):
        self.organization.subscriptions.update(status=OrganizationSubscription.Status.CANCELLED)
        self._login()
        response = self.client.post(
            reverse("api-portal-payment-charge"), data=json.dumps({"amount": "10.00"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    # --- superbill (read-only) ----------------------------------------------

    def test_superbill_list_and_detail_reuse_staff_data_shape(self):
        superbill = self._make_superbill(amount="120.00")
        self._login()
        list_response = self.client.get(reverse("api-portal-superbills"))
        self.assertEqual(len(list_response.json()["superbills"]), 1)

        detail_response = self.client.get(reverse("api-portal-superbill-detail", kwargs={"superbill_id": superbill.pk}))
        self.assertEqual(detail_response.status_code, 200)
        data = detail_response.json()["superbill"]
        self.assertEqual(data["totalAmount"], "120.00")
        self.assertIn("practice", data)

    def test_superbill_detail_idor_is_blocked(self):
        superbill = Superbill.objects.create(
            patient=self.other_patient, clinician=self.therapist, service_date=date.today(), codes=["97110"], amount="60.00",
        )
        self._login()
        response = self.client.get(reverse("api-portal-superbill-detail", kwargs={"superbill_id": superbill.pk}))
        self.assertEqual(response.status_code, 404)

    # --- telehealth join eligibility + honest session attempt --------------

    def _telehealth_appointment(self, *, minutes_from_now=5, kind=Appointment.Kind.TELEHEALTH, status=Appointment.Status.SCHEDULED):
        starts_at = timezone.now() + timedelta(minutes=minutes_from_now)
        return Appointment.objects.create(
            patient=self.patient, therapist=self.therapist, kind=kind, status=status,
            starts_at=starts_at, ends_at=starts_at + timedelta(minutes=30), created_by=self.therapist,
        )

    def test_can_join_telehealth_true_within_window(self):
        appointment = self._telehealth_appointment(minutes_from_now=10)
        self._login()
        response = self.client.get(reverse("api-portal-appointments"))
        matching = next(a for a in response.json()["upcoming"] if a["id"] == str(appointment.pk))
        self.assertTrue(matching["canJoinTelehealth"])

    def test_can_join_telehealth_false_outside_window(self):
        appointment = self._telehealth_appointment(minutes_from_now=60)
        self._login()
        response = self.client.get(reverse("api-portal-appointments"))
        matching = next(a for a in response.json()["upcoming"] if a["id"] == str(appointment.pk))
        self.assertFalse(matching["canJoinTelehealth"])

    def test_can_join_telehealth_false_for_non_telehealth_kind(self):
        appointment = self._telehealth_appointment(minutes_from_now=5, kind=Appointment.Kind.FOLLOW_UP)
        self._login()
        response = self.client.get(reverse("api-portal-appointments"))
        matching = next(a for a in response.json()["upcoming"] if a["id"] == str(appointment.pk))
        self.assertFalse(matching["canJoinTelehealth"])

    def test_join_telehealth_within_window_returns_honest_not_connected(self):
        appointment = self._telehealth_appointment(minutes_from_now=5)
        self._login()
        response = self.client.post(
            reverse("api-portal-appointment-telehealth-join", kwargs={"appointment_id": appointment.pk})
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["joinable"])
        self.assertIsNone(body["joinUrl"])
        self.assertIn("not yet connected", body["message"])
        self.assertTrue(
            AuditEvent.objects.filter(action="telehealth.join_attempted", patient=self.patient).exists()
        )

    def test_join_telehealth_outside_window_is_rejected(self):
        appointment = self._telehealth_appointment(minutes_from_now=120)
        self._login()
        response = self.client.post(
            reverse("api-portal-appointment-telehealth-join", kwargs={"appointment_id": appointment.pk})
        )
        self.assertEqual(response.status_code, 409)

    def test_join_telehealth_idor_is_blocked(self):
        appointment = self._telehealth_appointment(minutes_from_now=5)
        self.client.force_login(self.other_portal_user)
        response = self.client.post(
            reverse("api-portal-appointment-telehealth-join", kwargs={"appointment_id": appointment.pk})
        )
        self.assertEqual(response.status_code, 404)

    def test_join_telehealth_blocked_when_feature_disabled(self):
        self.organization.subscriptions.update(status=OrganizationSubscription.Status.CANCELLED)
        appointment = self._telehealth_appointment(minutes_from_now=5)
        self._login()
        response = self.client.post(
            reverse("api-portal-appointment-telehealth-join", kwargs={"appointment_id": appointment.pk})
        )
        self.assertEqual(response.status_code, 403)


class PatientPortalProfileTests(TestCase):
    """Patient Portal Phase 7: profile self-service. Low-risk preference
    fields apply immediately; phone/email/address/emergency-contact changes
    go through a staff-reviewed queue and are never written until approved."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Portal Profile Clinic", slug="portal-profile-clinic")
        self.therapist = User.objects.create_user(
            username="profile-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        self.scheduler = User.objects.create_user(
            username="profile-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER,
        )
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Portia", last_name="Profile", date_of_birth="1990-01-01",
            phone="555-0001", email="old@example.test", address="1 Old St", emergency_contact="Old Contact 555-0002",
            assigned_therapist=self.therapist,
        )
        self.portal_user = User.objects.create_user(
            username="portia-profile@example.test", password="portia-password-123",
            organization=self.organization, role=User.Role.PATIENT, email="portia-profile@example.test",
        )
        self.patient.portal_user = self.portal_user
        self.patient.save(update_fields=["portal_user"])

        self.other_patient = Patient.objects.create(
            organization=self.organization, first_name="Other", last_name="Profile", date_of_birth="1991-02-02",
        )
        self.other_portal_user = User.objects.create_user(
            username="other-profile@example.test", password="other-password-123",
            organization=self.organization, role=User.Role.PATIENT,
        )
        self.other_patient.portal_user = self.other_portal_user
        self.other_patient.save(update_fields=["portal_user"])

    def _login(self):
        self.client.force_login(self.portal_user)

    def test_profile_view_returns_current_values(self):
        self._login()
        response = self.client.get(reverse("api-portal-profile"))
        self.assertEqual(response.status_code, 200)
        profile = response.json()["profile"]
        self.assertEqual(profile["phone"], "555-0001")
        self.assertIsNone(profile["pendingChangeRequest"])

    def test_preferences_update_applies_immediately(self):
        self._login()
        response = self.client.patch(
            reverse("api-portal-profile-preferences"),
            data=json.dumps({"pharmacyName": "Main St Pharmacy", "preferredContactMethod": "sms", "emailNotificationsEnabled": False}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.pharmacy_name, "Main St Pharmacy")
        self.assertEqual(self.patient.preferred_contact_method, "sms")
        self.assertFalse(self.patient.email_notifications_enabled)
        self.assertTrue(
            AuditEvent.objects.filter(action="patient_profile.preferences_updated", patient=self.patient).exists()
        )

    def test_preferences_update_rejects_invalid_contact_method(self):
        self._login()
        response = self.client.patch(
            reverse("api-portal-profile-preferences"),
            data=json.dumps({"preferredContactMethod": "carrier_pigeon"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)

    def test_sensitive_change_is_not_applied_until_approved(self):
        self._login()
        response = self.client.post(
            reverse("api-portal-profile-change-request-create"),
            data=json.dumps({"phone": "555-9999", "address": "2 New St"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.phone, "555-0001")  # unchanged
        self.assertEqual(PatientProfileChangeRequest.objects.filter(patient=self.patient, status="pending").count(), 1)

    def test_cannot_submit_a_second_request_while_one_is_pending(self):
        self._login()
        self.client.post(
            reverse("api-portal-profile-change-request-create"),
            data=json.dumps({"phone": "555-9999"}), content_type="application/json",
        )
        response = self.client.post(
            reverse("api-portal-profile-change-request-create"),
            data=json.dumps({"phone": "555-8888"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)

    def test_change_request_rejects_disallowed_field(self):
        self._login()
        response = self.client.post(
            reverse("api-portal-profile-change-request-create"),
            data=json.dumps({"diagnoses": "hacked"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 422)

    def test_staff_can_approve_a_change_request(self):
        self._login()
        create_response = self.client.post(
            reverse("api-portal-profile-change-request-create"),
            data=json.dumps({"phone": "555-9999", "emergencyContact": "New Contact 555-0003"}), content_type="application/json",
        )
        request_id = create_response.json()["changeRequest"]["id"]

        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-profile-change-request-staff-decide", kwargs={"request_id": request_id}),
            data=json.dumps({"decision": "approve", "note": "Verified by phone"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.phone, "555-9999")
        self.assertEqual(self.patient.emergency_contact, "New Contact 555-0003")
        self.assertTrue(
            AuditEvent.objects.filter(action="patient_profile.change_approved", patient=self.patient).exists()
        )

    def test_staff_can_reject_a_change_request_without_applying_it(self):
        self._login()
        create_response = self.client.post(
            reverse("api-portal-profile-change-request-create"),
            data=json.dumps({"phone": "555-9999"}), content_type="application/json",
        )
        request_id = create_response.json()["changeRequest"]["id"]

        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-profile-change-request-staff-decide", kwargs={"request_id": request_id}),
            data=json.dumps({"decision": "reject", "note": "Could not verify identity"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.phone, "555-0001")

    def test_scheduler_cannot_review_change_requests(self):
        self._login()
        create_response = self.client.post(
            reverse("api-portal-profile-change-request-create"),
            data=json.dumps({"phone": "555-9999"}), content_type="application/json",
        )
        request_id = create_response.json()["changeRequest"]["id"]
        self.client.force_login(self.scheduler)
        response = self.client.post(
            reverse("api-profile-change-request-staff-decide", kwargs={"request_id": request_id}),
            data=json.dumps({"decision": "approve"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_staff_queue_and_decision_are_scoped_to_own_organization(self):
        other_org = Organization.objects.create(name="Other Profile Org", slug="other-profile-org")
        other_therapist = User.objects.create_user(
            username="other-profile-therapist", password="safe-test-password", organization=other_org, role=User.Role.THERAPIST,
        )
        self._login()
        create_response = self.client.post(
            reverse("api-portal-profile-change-request-create"),
            data=json.dumps({"phone": "555-9999"}), content_type="application/json",
        )
        request_id = create_response.json()["changeRequest"]["id"]

        self.client.force_login(other_therapist)
        list_response = self.client.get(reverse("api-profile-change-requests-staff-list"))
        self.assertEqual(list_response.json()["requests"], [])
        decide_response = self.client.post(
            reverse("api-profile-change-request-staff-decide", kwargs={"request_id": request_id}),
            data=json.dumps({"decision": "approve"}), content_type="application/json",
        )
        self.assertEqual(decide_response.status_code, 404)

    def test_notification_email_is_skipped_when_patient_opts_out(self):
        self._login()
        self.client.patch(
            reverse("api-portal-profile-preferences"),
            data=json.dumps({"emailNotificationsEnabled": False}), content_type="application/json",
        )
        mail.outbox = []
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-secure-message-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"recipientId": str(self.portal_user.pk), "subject": "Hi", "body": "Checking in."}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(mail.outbox), 0)

    def test_notification_email_still_sent_when_opted_in(self):
        mail.outbox = []
        self.client.force_login(self.therapist)
        response = self.client.post(
            reverse("api-secure-message-create", kwargs={"patient_id": self.patient.pk}),
            data=json.dumps({"recipientId": str(self.portal_user.pk), "subject": "Hi", "body": "Checking in."}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(mail.outbox), 1)


class PatientPortalLoginAuditTests(TestCase):
    """Phase 7: a successful login now records an audit event (previously
    only failed logins did), patient-linked when the account is a portal
    account, so 'patient login' shows up in that patient's audit trail."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Login Audit Clinic", slug="login-audit-clinic")
        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Portia", last_name="Login", date_of_birth="1990-01-01",
        )
        self.portal_user = User.objects.create_user(
            username="portia-login@example.test", password="portia-password-123",
            organization=self.organization, role=User.Role.PATIENT,
        )
        self.patient.portal_user = self.portal_user
        self.patient.save(update_fields=["portal_user"])
        self.scheduler = User.objects.create_user(
            username="login-audit-scheduler", password="safe-test-password", organization=self.organization, role=User.Role.SCHEDULER,
        )

    def test_successful_patient_login_is_audited_and_patient_linked(self):
        response = self.client.post(
            reverse("api-login"), data=json.dumps({"username": "portia-login@example.test", "password": "portia-password-123"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        event = AuditEvent.objects.filter(action="user.login_succeeded", patient=self.patient).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.actor_id, self.portal_user.pk)

    def test_successful_staff_login_is_audited_without_patient_link(self):
        response = self.client.post(
            reverse("api-login"), data=json.dumps({"username": "login-audit-scheduler", "password": "safe-test-password"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        event = AuditEvent.objects.filter(action="user.login_succeeded", actor=self.scheduler).first()
        self.assertIsNotNone(event)
        self.assertIsNone(event.patient)

    def test_failed_login_still_audited_as_before(self):
        response = self.client.post(
            reverse("api-login"), data=json.dumps({"username": "portia-login@example.test", "password": "wrong-password"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertTrue(AuditEvent.objects.filter(action="LOGIN_FAILED", patient__isnull=True).exists())
        self.assertFalse(AuditEvent.objects.filter(action="user.login_succeeded").exists())


class PatientPortalDedicatedIdorAuditTests(TestCase):
    """Phase 7: a dedicated, systematic IDOR pass over list/detail portal
    endpoints not already covered by earlier phases' own tests (per-phase
    tests covered the mutating actions; this closes out the read paths)."""

    def setUp(self):
        self.organization = Organization.objects.create(name="IDOR Audit Clinic", slug="idor-audit-clinic")
        self.therapist = User.objects.create_user(
            username="idor-therapist", password="safe-test-password", organization=self.organization, role=User.Role.THERAPIST,
        )
        self.payer = Payer.objects.create(organization=self.organization, name="IDOR Payer", timely_filing_days=365)

        self.patient = Patient.objects.create(
            organization=self.organization, first_name="Portia", last_name="Idor", date_of_birth="1990-01-01",
            assigned_therapist=self.therapist,
        )
        self.portal_user = User.objects.create_user(
            username="portia-idor@example.test", password="portia-password-123",
            organization=self.organization, role=User.Role.PATIENT,
        )
        self.patient.portal_user = self.portal_user
        self.patient.save(update_fields=["portal_user"])

        self.other_patient = Patient.objects.create(
            organization=self.organization, first_name="Other", last_name="Idor", date_of_birth="1991-02-02",
        )
        self.other_portal_user = User.objects.create_user(
            username="other-idor@example.test", password="other-password-123",
            organization=self.organization, role=User.Role.PATIENT,
        )
        self.other_patient.portal_user = self.other_portal_user
        self.other_patient.save(update_fields=["portal_user"])

        from care.form_engine import ensure_form_templates
        ensure_form_templates(self.organization)

    def _login_as(self, portal_user):
        self.client.force_login(portal_user)

    def test_payments_list_never_shows_another_patients_data(self):
        PatientStatement.objects.create(
            organization=self.organization, patient=self.other_patient, due_date=date.today() + timedelta(days=30),
            balance_at_generation=Decimal("50.00"), generated_by=self.therapist,
        )
        self._login_as(self.portal_user)
        response = self.client.get(reverse("api-portal-payments"))
        self.assertEqual(response.json()["statements"], [])

    def test_insurance_card_download_idor_is_blocked(self):
        policy = PatientInsurance.objects.create(
            organization=self.organization, patient=self.other_patient, payer=self.payer,
            member_id="MBR-IDOR-1", effective_date=date.today(),
            card_front=SimpleUploadedFile("card.png", b"\x89PNG\r\n\x1a\n" + b"0" * 100, content_type="image/png"),
        )
        self._login_as(self.portal_user)
        response = self.client.get(
            reverse("api-portal-insurance-card-download", kwargs={"policy_id": policy.pk, "side": "front"})
        )
        self.assertEqual(response.status_code, 404)

    def test_forms_list_and_detail_are_per_patient_not_shared(self):
        self._login_as(self.portal_user)
        self.client.post(
            reverse("api-portal-form-save", kwargs={"template_slug": "digital-intake"}),
            data=json.dumps({"data": {"phone": "555-1111"}}), content_type="application/json",
        )
        self._login_as(self.other_portal_user)
        response = self.client.get(reverse("api-portal-form-detail", kwargs={"template_slug": "digital-intake"}))
        self.assertEqual(response.json()["submission"]["data"], {})

    def test_outcomes_list_never_shows_another_patients_assignment(self):
        OutcomeAssignment.objects.create(patient=self.other_patient, measure="lefs", assigned_by=self.therapist)
        self._login_as(self.portal_user)
        response = self.client.get(reverse("api-portal-outcomes-list"))
        self.assertEqual(response.json()["assignments"], [])

    def test_messages_list_never_shows_another_patients_thread(self):
        SecureMessage.objects.create(
            patient=self.other_patient, sender=self.therapist, recipient=self.other_portal_user,
            subject="Not yours", body="Not yours",
        )
        self._login_as(self.portal_user)
        response = self.client.get(reverse("api-portal-messages"))
        self.assertEqual(response.json()["messages"], [])

    def test_profile_change_request_idor_is_blocked(self):
        self._login_as(self.other_portal_user)
        self.client.post(
            reverse("api-portal-profile-change-request-create"),
            data=json.dumps({"phone": "555-0000"}), content_type="application/json",
        )
        self._login_as(self.portal_user)
        response = self.client.get(reverse("api-portal-profile"))
        self.assertIsNone(response.json()["profile"]["pendingChangeRequest"])

    def test_documents_and_hep_and_appointments_lists_are_isolated_per_patient(self):
        # A single consolidated smoke check across the remaining list endpoints
        # already unit-tested individually in earlier phases — confirms the
        # isolation holds simultaneously, not just one endpoint at a time.
        self._login_as(self.other_portal_user)
        self.client.post(
            reverse("api-portal-documents"),
            data={"file": SimpleUploadedFile("x.pdf", b"%PDF-1.4 x", content_type="application/pdf"), "title": "Other doc"},
        )
        self._login_as(self.portal_user)
        documents_response = self.client.get(reverse("api-portal-documents"))
        appointments_response = self.client.get(reverse("api-portal-appointments"))
        hep_response = self.client.get(reverse("api-portal-hep"))
        self.assertEqual(documents_response.json()["documents"], [])
        self.assertEqual(appointments_response.json()["upcoming"], [])
        self.assertIsNone(hep_response.json()["program"])
