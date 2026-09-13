"""Create a dedicated User Acceptance Testing (UAT) tenant with one clearly
labeled TEST ACCOUNT per role, plus enough supporting data (a location,
appointment type, licensed provider profiles, a Mobile Care service area
and availability, an enabled Mobile Care configuration, a test patient
with a portal login, and a couple of appointments/requests) that every
screen in the UAT testing guide has something real to show instead of an
empty state.

FOR LOCAL / STAGING TESTING ONLY. Every account uses a "*.uat@uat.test"
username/email and the single fixed test password below — never reuse
this password for a real account, and never point this command at a
database containing real patient data.

Idempotent and safe to re-run: an existing UAT organization/user/record is
reused and updated in place (including resetting the password to the
known test value below) rather than duplicated.
"""
from datetime import date, datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from care.client_management import next_client_number, unique_slug
from care.models import (
    Appointment,
    AppointmentType,
    HomeVisitAvailability,
    Location,
    MobileCareConfiguration,
    MobileCareRequest,
    Organization,
    Patient,
    Provider,
    ServiceArea,
    ServiceAreaZipCode,
    ServicePrice,
    User,
    UserLicense,
)

# Clearly a test credential, never a real one — printed in the UAT guide
# labeled "TEST ACCOUNT ONLY" throughout.
UAT_PASSWORD = "Uat-Test-Pw-88214!"
UAT_ORG_NAME = "UAT Test Clinic"
UAT_ORG_SLUG = "uat-test-clinic"

TEST_USERS = [
    # (username/email local part, first, last, role)
    ("superadmin.uat", "Uat", "Superadmin", User.Role.SUPER_ADMIN),
    ("admin.uat", "Uat", "Admin", User.Role.ADMIN),
    ("pt.uat", "Uat", "Therapist", User.Role.THERAPIST),
    ("pta.uat", "Uat", "Assistant", User.Role.ASSISTANT),
    ("frontdesk.uat", "Uat", "Frontdesk", User.Role.SCHEDULER),
    ("billing.uat", "Uat", "Biller", User.Role.BILLER),
    ("patient.uat", "Uat", "Testpatient", User.Role.PATIENT),
]


class Command(BaseCommand):
    help = "Create/reset a dedicated UAT tenant with one test account per role. Local/staging only."

    def handle(self, *args, **options):
        with transaction.atomic():
            self._run()

    def _run(self):
        org = self._get_or_create_org()
        users = {}
        for local_part, first, last, role in TEST_USERS:
            users[role] = self._get_or_create_user(local_part, first, last, role, org)

        pt_user = users[User.Role.THERAPIST]
        pta_user = users[User.Role.ASSISTANT]
        admin_user = users[User.Role.ADMIN]
        scheduler_user = users[User.Role.SCHEDULER]
        patient_user = users[User.Role.PATIENT]

        pt_provider = self._get_or_create_provider(org, pt_user, "PT-UAT-0001")
        self._get_or_create_provider(org, pta_user, "PTA-UAT-0001")

        location = self._get_or_create_location(org)
        appt_type = self._get_or_create_appointment_type(org)
        self._get_or_create_service_area(org, pt_provider)
        self._get_or_create_availability(org, pt_provider)
        self._get_or_create_mobile_care_config(org)
        self._get_or_create_service_prices(org)
        patient = self._get_or_create_patient(org, pt_user, patient_user)
        self._get_or_create_appointment(patient, pt_user, pt_provider, location, appt_type, scheduler_user)
        self._get_or_create_mobile_care_request(org, patient, admin_user)

        self.stdout.write(self.style.SUCCESS(f"UAT tenant ready: {org.name} (client #{org.client_number})"))
        self.stdout.write(self.style.SUCCESS(f"Test password for every account above: {UAT_PASSWORD}"))
        self.stdout.write(self.style.WARNING("TEST ACCOUNTS ONLY — do not reuse this password for a real account."))

    # --- organization ------------------------------------------------------

    def _get_or_create_org(self) -> Organization:
        org = Organization.objects.filter(slug=UAT_ORG_SLUG).first()
        if org:
            return org
        org = Organization.objects.create(
            client_number=next_client_number(),
            name=UAT_ORG_NAME,
            slug=UAT_ORG_SLUG,
            support_email="admin.uat@uat.test",
            address_line_1="1 UAT Test Way",
            city="Cary",
            state="NC",
            zip_code="27526",
            country="United States",
            subscription_tier=Organization.SubscriptionTier.ENTERPRISE,
            timezone="America/New_York",
            status=Organization.Status.ACTIVE,
            comments="Dedicated User Acceptance Testing tenant. Synthetic data only — never real patients.",
        )
        self.stdout.write(self.style.SUCCESS(f"Created UAT organization #{org.client_number} {org.name}"))
        return org

    # --- users ---------------------------------------------------------------

    def _get_or_create_user(self, local_part, first, last, role, org: Organization) -> User:
        username = f"{local_part}@uat.test"
        user = User.objects.filter(username=username).first()
        is_super_admin = role == User.Role.SUPER_ADMIN
        if user is None:
            user = User(
                username=username,
                email=username,
                first_name=first,
                last_name=last,
                role=role,
                organization=None if is_super_admin else org,
                is_active=True,
                is_superuser=is_super_admin,
                must_change_password=False,
            )
        else:
            user.role = role
            user.organization = None if is_super_admin else org
            user.is_active = True
            user.is_superuser = is_super_admin
            user.status = User.Status.ACTIVE
            user.failed_login_attempts = 0
            user.locked_until = None
        user.set_password(UAT_PASSWORD)
        user.full_clean()
        user.save()
        return user

    # --- provider / license --------------------------------------------------

    def _get_or_create_provider(self, org: Organization, user: User, license_number: str) -> Provider:
        provider = Provider.objects.filter(organization=org, user=user).first()
        if provider is None:
            provider = Provider.objects.create(
                organization=org, user=user, first_name=user.first_name, last_name=user.last_name,
                specialty="General Orthopedic", credentials="PT, DPT" if user.role == User.Role.THERAPIST else "PTA",
                is_active=True,
            )
        UserLicense.objects.update_or_create(
            user=user, license_number=license_number,
            defaults={
                "issuing_state": "NC",
                "expires_at": date.today() + timedelta(days=730),
                "verification_status": UserLicense.VerificationStatus.VERIFIED,
            },
        )
        return provider

    # --- supporting records --------------------------------------------------

    def _get_or_create_location(self, org: Organization) -> Location:
        location, _ = Location.objects.get_or_create(
            organization=org, name="UAT Test Location",
            defaults={"address_line_1": "1 UAT Test Way", "city": "Cary", "state": "NC", "zip_code": "27526", "timezone": "America/New_York"},
        )
        return location

    def _get_or_create_appointment_type(self, org: Organization) -> AppointmentType:
        appt_type, _ = AppointmentType.objects.get_or_create(
            organization=org, name="UAT Follow-Up Visit", defaults={"default_duration_minutes": 30},
        )
        return appt_type

    def _get_or_create_service_area(self, org: Organization, provider: Provider) -> ServiceArea:
        area, _ = ServiceArea.objects.get_or_create(
            organization=org, provider=provider, name="UAT Primary Area",
            defaults={"is_active": True, "primary_zip_code": "27526", "city": "Cary", "state": "NC"},
        )
        ServiceAreaZipCode.objects.get_or_create(service_area=area, zip_code="27526")
        return area

    def _get_or_create_availability(self, org: Organization, provider: Provider) -> None:
        HomeVisitAvailability.objects.get_or_create(
            organization=org, provider=provider, day_of_week=0, start_time=time(8, 0), end_time=time(17, 0),
            defaults={
                "availability_type": HomeVisitAvailability.AvailabilityType.AVAILABLE,
                "is_recurring": True, "is_active": True,
            },
        )

    def _get_or_create_mobile_care_config(self, org: Organization) -> None:
        MobileCareConfiguration.objects.get_or_create(organization=org, defaults={"mobile_care_enabled": True})

    def _get_or_create_service_prices(self, org: Organization) -> None:
        ServicePrice.objects.get_or_create(
            organization=org, cpt_code="97161",
            defaults={"label": "Home PT Initial Evaluation", "price": "175.00", "home_visit_kind": Appointment.Kind.EVALUATION},
        )
        ServicePrice.objects.get_or_create(
            organization=org, cpt_code="97110",
            defaults={"label": "Home PT Follow-Up", "price": "135.00", "home_visit_kind": Appointment.Kind.FOLLOW_UP},
        )
        ServicePrice.objects.get_or_create(
            organization=org, cpt_code="99082",
            defaults={"label": "Optional Travel Fee", "price": "20.00", "is_home_visit_travel_fee": True},
        )

    def _get_or_create_patient(self, org: Organization, pt_user: User, patient_user: User) -> Patient:
        patient = Patient.objects.filter(organization=org, first_name="Uat", last_name="Testpatient").first()
        if patient is None:
            patient = Patient(
                organization=org, first_name="Uat", last_name="Testpatient", date_of_birth=date(1990, 1, 1),
                phone="919-555-0100", email="patient.uat@uat.test", address="1 UAT Test Way, Cary, NC 27526",
                assigned_therapist=pt_user, diagnoses="Synthetic test diagnosis — low back pain",
            )
            patient.full_clean()
            patient.save()
        if patient.portal_user_id != patient_user.id:
            patient.portal_user = patient_user
            patient.save(update_fields=["portal_user"])
        return patient

    def _get_or_create_appointment(self, patient, pt_user, provider, location, appt_type, scheduler_user) -> None:
        if Appointment.objects.filter(patient=patient, therapist=pt_user, status=Appointment.Status.SCHEDULED).exists():
            return
        tomorrow_9am = timezone.make_aware(datetime.combine(date.today() + timedelta(days=1), time(9, 0)))
        Appointment.objects.create(
            patient=patient, therapist=pt_user, provider=provider, location_detail=location, location=location.name,
            appointment_type=appt_type, kind=Appointment.Kind.FOLLOW_UP, status=Appointment.Status.SCHEDULED,
            starts_at=tomorrow_9am, ends_at=tomorrow_9am + timedelta(minutes=30), created_by=scheduler_user,
        )

    def _get_or_create_mobile_care_request(self, org: Organization, patient, admin_user) -> None:
        if MobileCareRequest.objects.filter(organization=org, patient=patient).exists():
            return
        MobileCareRequest.objects.create(
            organization=org, patient=patient,
            address_line_1="1 UAT Test Way", city="Cary", state="NC", zip_code="27526",
            earliest_date=date.today() + timedelta(days=5),
            requested_service=MobileCareRequest.RequestedService.FOLLOW_UP,
            reason_for_visit="Synthetic UAT test request", created_by=admin_user,
        )
