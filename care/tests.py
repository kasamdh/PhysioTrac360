import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

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
    BookingConfiguration,
    ClinicalNote,
    Consent,
    Feature,
    FunctionalGoal,
    IntakeSubmission,
    Location,
    LocationClosure,
    NoteAddendum,
    Organization,
    OrganizationSubscription,
    OutcomeScore,
    Patient,
    PatientDocument,
    PaymentRecord,
    PrivilegedAccessGrant,
    Provider,
    ProviderAppointmentType,
    ProviderAvailability,
    ProviderTimeOff,
    Referral,
    SubscriptionPlan,
    Superbill,
    User,
)
from .services import compose_draft, goal_suggestions, note_compliance_findings, record_audit_event


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
