"""Seed demo clients (tenants) and staff for local Client Management testing.

Run `bootstrap_demo` first to create the platform super administrator that
provisions these clients. This command is for local development only; it is
idempotent and safe to re-run — an existing client (matched by name) is
skipped entirely, so the richer clinical-workspace data below only ever runs
once per organization, the first time it is created.

Source Motion PT and Total Motion PT (the two clients with staff) also get a
full realistic dataset across every module built so far — locations,
providers, appointment types, weekly availability, online-booking
configuration, a patient roster, appointments in every status, clinical
notes (signed and draft), a functional goal, an outcome-measure trend,
referrals, intake + consent, and billing — so every workspace page and the
public booking flow have real data to exercise instead of an empty state.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from care.client_management import provision_client, suspend_client
from care.models import (
    Appointment,
    AppointmentType,
    BookingConfiguration,
    ClinicalNote,
    Consent,
    FunctionalGoal,
    IntakeSubmission,
    Location,
    Organization,
    OutcomeScore,
    Patient,
    PaymentRecord,
    Provider,
    ProviderAppointmentType,
    ProviderAvailability,
    Referral,
    Superbill,
    User,
)


DEMO_CLIENTS = [
    {
        "clientName": "Source Motion PT",
        "clientEmail": "admin@sourcemotionpt.test",
        "addressLine1": "123 Main Street",
        "city": "Fuquay-Varina",
        "state": "NC",
        "zipCode": "27526",
        "subscriptionTier": Organization.SubscriptionTier.PROFESSIONAL,
        "timezone": "America/New_York",
        "comments": "Mobile and home-based physical therapy practice.",
        "adminFirstName": "Monika",
        "adminLastName": "Pokhrel",
        "adminEmail": "monika@sourcemotionpt.test",
        "suspend": False,
        "staff": [
            ("Amanda", "Smith", "amanda@sourcemotionpt.test", User.Role.THERAPIST),
            ("Jennifer", "Brown", "jennifer@sourcemotionpt.test", User.Role.SCHEDULER),
        ],
    },
    {
        "clientName": "Total Motion PT",
        "clientEmail": "admin@totalmotionpt.test",
        "addressLine1": "455 Sunset Boulevard",
        "city": "Los Angeles",
        "state": "CA",
        "zipCode": "90028",
        "subscriptionTier": Organization.SubscriptionTier.PREMIUM,
        "timezone": "America/Los_Angeles",
        "comments": "Outpatient orthopedic physical therapy clinic.",
        "adminFirstName": "David",
        "adminLastName": "Miller",
        "adminEmail": "david@totalmotionpt.test",
        "suspend": False,
        "staff": [
            ("Mark", "Wilson", "mark@totalmotionpt.test", User.Role.THERAPIST),
            ("Lisa", "Anderson", "lisa@totalmotionpt.test", User.Role.SCHEDULER),
        ],
    },
    {
        "clientName": "Triangle Rehab Center",
        "clientEmail": "admin@trianglerehab.test",
        "addressLine1": "8200 Capital Boulevard",
        "city": "Raleigh",
        "state": "NC",
        "zipCode": "27616",
        "subscriptionTier": Organization.SubscriptionTier.STARTER,
        "timezone": "America/New_York",
        "comments": "Demo suspended account.",
        "adminFirstName": "Sarah",
        "adminLastName": "Johnson",
        "adminEmail": "sarah@trianglerehab.test",
        "suspend": True,
        "staff": [
            ("Michael", "Reed", "michael@trianglerehab.test", User.Role.THERAPIST),
            ("Ashley", "Cole", "ashley@trianglerehab.test", User.Role.SCHEDULER),
        ],
    },
    {
        "clientName": "Mountain Motion Therapy",
        "clientEmail": "admin@mountainmotion.test",
        "addressLine1": "1500 Blake Street",
        "city": "Denver",
        "state": "CO",
        "zipCode": "80202",
        "subscriptionTier": Organization.SubscriptionTier.PROFESSIONAL,
        "timezone": "America/Denver",
        "comments": "",
        "adminFirstName": "Robert",
        "adminLastName": "Taylor",
        "adminEmail": "robert@mountainmotion.test",
        "suspend": False,
        "staff": [
            ("Emily", "Park", "emily@mountainmotion.test", User.Role.THERAPIST),
            ("Brian", "Hayes", "brian@mountainmotion.test", User.Role.SCHEDULER),
        ],
    },
    {
        "clientName": "Desert Performance PT",
        "clientEmail": "admin@desertperformance.test",
        "addressLine1": "710 East Camelback Road",
        "city": "Phoenix",
        "state": "AZ",
        "zipCode": "85014",
        "subscriptionTier": Organization.SubscriptionTier.PREMIUM,
        "timezone": "America/Phoenix",
        "comments": "",
        "adminFirstName": "Emily",
        "adminLastName": "Davis",
        "adminEmail": "emily@desertperformance.test",
        "suspend": False,
        "staff": [
            ("Carlos", "Rivera", "carlos@desertperformance.test", User.Role.THERAPIST),
            ("Natalie", "Brooks", "natalie@desertperformance.test", User.Role.SCHEDULER),
        ],
    },
]


APPOINTMENT_TYPE_SPECS = [
    # name, duration minutes, price, requires new patient, buffer before, buffer after
    ("Initial Evaluation", 60, Decimal("175.00"), True, 15, 0),
    ("Follow-Up Visit", 30, Decimal("95.00"), False, 0, 0),
    ("Manual Therapy & Dry Needling", 45, Decimal("135.00"), False, 0, 15),
]

PATIENT_ROSTERS = {
    "Source Motion PT": [
        {
            "first": "Robert", "last": "Chen", "dob": date(1978, 3, 22),
            "phone": "919-555-0142", "email": "robert.chen@example.com",
            "address": "212 Holly Springs Rd, Fuquay-Varina, NC 27526",
            "emergency_contact": "Grace Chen (spouse) — 919-555-0143",
            "diagnoses": "Lumbar strain, post motor-vehicle accident",
            "precautions": "No lifting over 10 lbs; avoid prolonged sitting.",
        },
        {
            "first": "Linda", "last": "Torres", "dob": date(1965, 11, 9),
            "phone": "919-555-0198", "email": "linda.torres@example.com",
            "address": "88 Lakeview Ct, Fuquay-Varina, NC 27526",
            "emergency_contact": "Marco Torres (son) — 919-555-0199",
            "diagnoses": "Total knee replacement, right, post-op week 3",
            "precautions": "Weight-bearing as tolerated with front-wheel walker.",
        },
        {
            "first": "Kevin", "last": "Walsh", "dob": date(1990, 7, 14),
            "phone": "919-555-0221", "email": "kevin.walsh@example.com",
            "address": "45 Old Stage Rd, Fuquay-Varina, NC 27526",
            "emergency_contact": "Amy Walsh (spouse) — 919-555-0222",
            "diagnoses": "Rotator cuff repair, left shoulder, post-op week 6",
            "precautions": "No overhead lifting; passive ROM only above 90 degrees.",
        },
        {
            "first": "Sophia", "last": "Martin", "dob": date(1996, 2, 3),
            "phone": "919-555-0264", "email": "sophia.martin@example.com",
            "address": "301 Judd Pkwy, Fuquay-Varina, NC 27526",
            "emergency_contact": "Elena Martin (mother) — 919-555-0265",
            "diagnoses": "Chronic ankle instability, right, recurrent sprains",
            "precautions": "Brace required for weight-bearing activity.",
        },
    ],
    "Total Motion PT": [
        {
            "first": "Daniel", "last": "Foster", "dob": date(1982, 5, 2),
            "phone": "310-555-0110", "email": "daniel.foster@example.com",
            "address": "1900 Vine St, Los Angeles, CA 90028",
            "emergency_contact": "Rachel Foster (spouse) — 310-555-0111",
            "diagnoses": "ACL reconstruction, right knee, post-op month 2",
            "precautions": "No pivoting sports; brace locked for ambulation.",
        },
        {
            "first": "Grace", "last": "Kim", "dob": date(1998, 1, 30),
            "phone": "310-555-0152", "email": "grace.kim@example.com",
            "address": "6250 Hollywood Blvd, Los Angeles, CA 90028",
            "emergency_contact": "Jin Kim (father) — 310-555-0153",
            "diagnoses": "Ankle sprain, left, grade II",
            "precautions": "Boot for community ambulation.",
        },
        {
            "first": "William", "last": "Turner", "dob": date(1955, 9, 18),
            "phone": "310-555-0187", "email": "william.turner@example.com",
            "address": "7080 Hollywood Blvd, Los Angeles, CA 90028",
            "emergency_contact": "Nancy Turner (spouse) — 310-555-0188",
            "diagnoses": "Chronic low back pain with left-sided radiculopathy",
            "precautions": "Avoid end-range lumbar flexion under load.",
        },
        {
            "first": "Olivia", "last": "Bennett", "dob": date(1972, 12, 5),
            "phone": "310-555-0219", "email": "olivia.bennett@example.com",
            "address": "1500 N Highland Ave, Los Angeles, CA 90028",
            "emergency_contact": "Chris Bennett (spouse) — 310-555-0220",
            "diagnoses": "Cervical strain with associated headaches",
            "precautions": "Avoid sustained neck extension.",
        },
    ],
    "Triangle Rehab Center": [
        {
            "first": "Patricia", "last": "Nguyen", "dob": date(1975, 4, 11),
            "phone": "919-555-0311", "email": "patricia.nguyen@example.com",
            "address": "4200 Capital Blvd, Raleigh, NC 27616",
            "emergency_contact": "Hoa Nguyen (spouse) — 919-555-0312",
            "diagnoses": "Adhesive capsulitis (frozen shoulder), right",
            "precautions": "Gentle passive ROM only; avoid forceful stretching.",
        },
        {
            "first": "Steven", "last": "Malone", "dob": date(1988, 9, 2),
            "phone": "919-555-0344", "email": "steven.malone@example.com",
            "address": "900 Capital Blvd, Raleigh, NC 27616",
            "emergency_contact": "Rita Malone (mother) — 919-555-0345",
            "diagnoses": "Achilles tendinopathy, left",
            "precautions": "No plyometrics; limit resisted plantarflexion.",
        },
        {
            "first": "Diane", "last": "Ortiz", "dob": date(1960, 1, 19),
            "phone": "919-555-0377", "email": "diane.ortiz@example.com",
            "address": "6100 Capital Blvd, Raleigh, NC 27616",
            "emergency_contact": "Luis Ortiz (son) — 919-555-0378",
            "diagnoses": "Total hip replacement, left, post-op week 4",
            "precautions": "Hip precautions: no flexion past 90°, no adduction past midline.",
        },
        {
            "first": "Marcus", "last": "Webb", "dob": date(1993, 6, 25),
            "phone": "919-555-0402", "email": "marcus.webb@example.com",
            "address": "3500 Capital Blvd, Raleigh, NC 27616",
            "emergency_contact": "Tasha Webb (spouse) — 919-555-0403",
            "diagnoses": "Lumbar disc herniation L4-L5 with left-sided sciatica",
            "precautions": "Avoid loaded lumbar flexion and prolonged sitting.",
        },
    ],
    "Mountain Motion Therapy": [
        {
            "first": "Hannah", "last": "Roberts", "dob": date(1985, 10, 8),
            "phone": "720-555-0118", "email": "hannah.roberts@example.com",
            "address": "1600 Blake St, Denver, CO 80202",
            "emergency_contact": "Josh Roberts (spouse) — 720-555-0119",
            "diagnoses": "Patellofemoral pain syndrome, bilateral",
            "precautions": "Avoid deep squatting and prolonged stair descent.",
        },
        {
            "first": "Tyler", "last": "Simmons", "dob": date(1979, 2, 14),
            "phone": "720-555-0152", "email": "tyler.simmons@example.com",
            "address": "1700 Wynkoop St, Denver, CO 80202",
            "emergency_contact": "Kara Simmons (spouse) — 720-555-0153",
            "diagnoses": "Rotator cuff tendinopathy, right shoulder",
            "precautions": "No overhead lifting over 15 lbs.",
        },
        {
            "first": "Megan", "last": "Cross", "dob": date(2001, 5, 30),
            "phone": "720-555-0187", "email": "megan.cross@example.com",
            "address": "1400 Larimer St, Denver, CO 80202",
            "emergency_contact": "Diane Cross (mother) — 720-555-0188",
            "diagnoses": "ACL sprain, grade I, right knee, managed non-operatively",
            "precautions": "No pivoting or cutting sports; brace for activity.",
        },
        {
            "first": "Gregory", "last": "Hale", "dob": date(1968, 8, 17),
            "phone": "720-555-0221", "email": "gregory.hale@example.com",
            "address": "1801 California St, Denver, CO 80202",
            "emergency_contact": "Susan Hale (spouse) — 720-555-0222",
            "diagnoses": "Cervical radiculopathy, C6 distribution",
            "precautions": "Avoid sustained cervical extension and heavy overhead work.",
        },
    ],
    "Desert Performance PT": [
        {
            "first": "Isabella", "last": "Ramirez", "dob": date(1992, 3, 5),
            "phone": "602-555-0133", "email": "isabella.ramirez@example.com",
            "address": "4747 N 7th St, Phoenix, AZ 85014",
            "emergency_contact": "Carlos Ramirez (father) — 602-555-0134",
            "diagnoses": "Hamstring strain, grade II, right",
            "precautions": "No sprinting or ballistic stretching.",
        },
        {
            "first": "Noah", "last": "Coleman", "dob": date(1980, 12, 21),
            "phone": "602-555-0166", "email": "noah.coleman@example.com",
            "address": "711 E Camelback Rd, Phoenix, AZ 85014",
            "emergency_contact": "Erin Coleman (spouse) — 602-555-0167",
            "diagnoses": "Plantar fasciitis, bilateral",
            "precautions": "Limit prolonged standing on hard surfaces.",
        },
        {
            "first": "Ava", "last": "Mitchell", "dob": date(1970, 7, 9),
            "phone": "602-555-0199", "email": "ava.mitchell@example.com",
            "address": "5010 N Central Ave, Phoenix, AZ 85014",
            "emergency_contact": "Paul Mitchell (spouse) — 602-555-0200",
            "diagnoses": "Chronic low back pain with SI joint dysfunction",
            "precautions": "Avoid asymmetric loading and high-impact activity.",
        },
        {
            "first": "Ethan", "last": "Price", "dob": date(1996, 11, 2),
            "phone": "602-555-0233", "email": "ethan.price@example.com",
            "address": "3033 N Central Ave, Phoenix, AZ 85014",
            "emergency_contact": "Melissa Price (mother) — 602-555-0234",
            "diagnoses": "Bilateral shin splints, running-related",
            "precautions": "Reduce running mileage; avoid hard surfaces.",
        },
    ],
}


def _seed_clinical_workspace(client: Organization, therapist: User, scheduler: User) -> None:
    """Build a full realistic workspace (locations/booking/patients/chart data
    across every module) for one freshly provisioned client. Only ever called
    once, immediately after `provision_client`, so nothing here needs to be
    idempotent — a rerun of this command skips the whole client by name."""
    tz = ZoneInfo(client.timezone)
    today = timezone.localdate()

    def local_dt(days_offset: int, hour: int, minute: int = 0):
        naive = datetime.combine(today + timedelta(days=days_offset), time(hour, minute))
        return timezone.make_aware(naive, tz)

    location = Location.objects.create(
        organization=client,
        name=f"{client.name} - Main Clinic",
        address_line_1=client.address_line_1,
        city=client.city,
        state=client.state,
        zip_code=client.zip_code,
        timezone=client.timezone,
    )

    provider = Provider.objects.create(
        organization=client,
        user=therapist,
        first_name=therapist.first_name,
        last_name=therapist.last_name,
        specialty="Orthopedic & Sports Physical Therapy",
        credentials="PT, DPT",
        license_number=f"PT-{client.client_number}01",
        online_booking_enabled=True,
        bio=f"{therapist.first_name} {therapist.last_name} is a licensed physical therapist at {client.name}.",
    )
    provider.locations.add(location)

    appointment_types = {}
    for name, duration, price, requires_new, buffer_before, buffer_after in APPOINTMENT_TYPE_SPECS:
        appointment_type = AppointmentType.objects.create(
            organization=client,
            name=name,
            description=f"{name} at {client.name}.",
            default_duration_minutes=duration,
            price=price,
            online_booking_enabled=True,
            requires_new_patient=requires_new,
            buffer_before_minutes=buffer_before,
            buffer_after_minutes=buffer_after,
        )
        ProviderAppointmentType.objects.create(provider=provider, appointment_type=appointment_type)
        appointment_types[name] = appointment_type

    for weekday in range(5):  # Monday-Friday
        ProviderAvailability.objects.create(
            provider=provider, location=location, day_of_week=weekday, start_time=time(8, 0), end_time=time(12, 0)
        )
        ProviderAvailability.objects.create(
            provider=provider, location=location, day_of_week=weekday, start_time=time(13, 0), end_time=time(17, 0)
        )

    BookingConfiguration.objects.create(
        organization=client,
        online_booking_enabled=True,
        min_notice_hours=4,
        max_advance_days=60,
        slot_interval_minutes=15,
    )

    patients = []
    for entry in PATIENT_ROSTERS[client.name]:
        patient = Patient(
            organization=client,
            first_name=entry["first"],
            last_name=entry["last"],
            date_of_birth=entry["dob"],
            phone=entry["phone"],
            email=entry["email"],
            address=entry["address"],
            emergency_contact=entry["emergency_contact"],
            diagnoses=entry["diagnoses"],
            precautions=entry["precautions"],
            assigned_therapist=therapist,
        )
        patient.full_clean()
        patient.save()
        patients.append(patient)

    # Patient 0: established case — signed evaluation note, active goal, an
    # outcome-measure trend, a completed and an upcoming visit, billing, and
    # an incoming referral that led to the initial evaluation.
    p0 = patients[0]
    eval_start = local_dt(-21, 9, 0)
    eval_appointment = Appointment.objects.create(
        patient=p0, therapist=therapist, provider=provider, location_detail=location, location=location.name,
        appointment_type=appointment_types["Initial Evaluation"], kind=Appointment.Kind.EVALUATION,
        status=Appointment.Status.COMPLETED, starts_at=eval_start, ends_at=eval_start + timedelta(minutes=60),
        reason_for_visit=p0.diagnoses, created_by=scheduler,
    )
    eval_note = ClinicalNote(
        patient=p0, therapist=therapist, appointment=eval_appointment, note_type=ClinicalNote.Type.EVALUATION,
        status=ClinicalNote.Status.SIGNED, service_date=eval_start.date(),
        diagnosis_snapshot=p0.diagnoses, precautions_snapshot=p0.precautions,
        subjective=f"{p0.first_name} reports 6/10 low back pain radiating into the right hip since the accident, worse with sitting over 20 minutes.",
        objective="Lumbar AROM: flexion 40°, extension 10°, limited by pain. SLR 45° bilateral, negative for radicular signs. 4/5 strength hip flexors bilaterally.",
        interventions="Patient education, postural retraining, initiated core stabilization program.",
        assessment="Findings consistent with lumbar strain; good rehab potential given absence of neuro signs.",
        plan="Skilled PT 2x/week for 8 weeks: manual therapy, therapeutic exercise, progressive core stabilization.",
        plan_of_care_start=eval_start.date(), plan_of_care_end=eval_start.date() + timedelta(weeks=8),
        frequency_per_week=2, duration_weeks=8, reassessment_due=eval_start.date() + timedelta(weeks=4),
        signature_name=f"{therapist.first_name} {therapist.last_name}, PT, DPT", signed_at=eval_start + timedelta(hours=1),
        finalization_attestation=True,
    )
    eval_note.full_clean()
    eval_note.save()

    goal = FunctionalGoal(
        patient=p0, author=therapist,
        functional_limitation="Unable to sit through a full work day without significant low back pain.",
        functional_task="Sit at a desk for 60 continuous minutes without exceeding 3/10 pain",
        baseline_value=Decimal("20"), target_value=Decimal("60"), current_value=Decimal("40"), unit="minutes",
        measurement_method="Patient-reported sitting tolerance, verified at each visit",
        target_date=eval_start.date() + timedelta(weeks=8),
        suggested_wording=f"{p0.first_name} will sit for 60 continuous minutes with pain at or below 3/10 in 8 weeks.",
        status=FunctionalGoal.Status.ACTIVE, approved_by=therapist, approved_at=eval_start + timedelta(hours=1),
    )
    goal.full_clean()
    goal.save()

    OutcomeScore.objects.create(
        patient=p0, note=eval_note, recorded_by=therapist, measure=OutcomeScore.Measure.ODI,
        measured_on=eval_start.date(), score=Decimal("38"), maximum_score=Decimal("100"),
        notes="Baseline at initial evaluation.",
    )
    OutcomeScore.objects.create(
        patient=p0, recorded_by=therapist, measure=OutcomeScore.Measure.ODI,
        measured_on=today - timedelta(days=3), score=Decimal("22"), maximum_score=Decimal("100"),
        notes="Steady improvement with continued PT.",
    )

    superbill = Superbill.objects.create(
        patient=p0, clinician=therapist, service_date=eval_start.date(), codes=["97161", "97110", "97140"],
        amount=Decimal("175.00"), status=Superbill.Status.SUBMITTED, payment_processor_reference="sb-demo-0001",
    )
    PaymentRecord.objects.create(
        patient=p0, superbill=superbill, recorded_by=scheduler, amount=Decimal("175.00"),
        received_on=eval_start.date(), status=PaymentRecord.Status.RECEIVED, payment_processor_reference="pay-demo-0001",
    )

    followup_start = local_dt(-3, 10, 0)
    Appointment.objects.create(
        patient=p0, therapist=therapist, provider=provider, location_detail=location, location=location.name,
        appointment_type=appointment_types["Follow-Up Visit"], kind=Appointment.Kind.FOLLOW_UP,
        status=Appointment.Status.COMPLETED, starts_at=followup_start, ends_at=followup_start + timedelta(minutes=30),
        created_by=scheduler,
    )
    upcoming_start = local_dt(2, 9, 30)
    Appointment.objects.create(
        patient=p0, therapist=therapist, provider=provider, location_detail=location, location=location.name,
        appointment_type=appointment_types["Follow-Up Visit"], kind=Appointment.Kind.PROGRESS,
        status=Appointment.Status.SCHEDULED, starts_at=upcoming_start, ends_at=upcoming_start + timedelta(minutes=30),
        created_by=scheduler,
    )
    Referral.objects.create(
        patient=p0, direction=Referral.Direction.INCOMING, provider_name="Dr. Susan Patel, MD — Orthopedic Surgery",
        provider_contact="555-0110", status=Referral.Status.SCHEDULED, created_by=scheduler,
        reason="Post-MVA lumbar strain, referred for conservative PT prior to considering imaging.",
    )

    # Patient 1: mid-episode — a draft (unsigned) daily note and an upcoming visit.
    p1 = patients[1]
    daily_start = local_dt(-2, 11, 0)
    daily_appointment = Appointment.objects.create(
        patient=p1, therapist=therapist, provider=provider, location_detail=location, location=location.name,
        appointment_type=appointment_types["Follow-Up Visit"], kind=Appointment.Kind.FOLLOW_UP,
        status=Appointment.Status.COMPLETED, starts_at=daily_start, ends_at=daily_start + timedelta(minutes=30),
        created_by=scheduler,
    )
    draft_note = ClinicalNote(
        patient=p1, therapist=therapist, appointment=daily_appointment, note_type=ClinicalNote.Type.DAILY,
        status=ClinicalNote.Status.DRAFT, service_date=daily_start.date(),
        diagnosis_snapshot=p1.diagnoses, precautions_snapshot=p1.precautions,
        subjective=f"{p1.first_name} reports decreased swelling, walker tolerance improving.",
        objective="Knee flexion AROM 0-95°, gait with walker steady, quad set 4/5.",
        interventions="Gait training, quad sets, patellar mobilization, stationary bike 10 min.",
        assessment="Progressing as expected for post-op week 3.",
        plan="Continue POC; advance to single-point cane as tolerated next visit.",
    )
    draft_note.full_clean()
    draft_note.save()
    next_visit = local_dt(4, 14, 0)
    Appointment.objects.create(
        patient=p1, therapist=therapist, provider=provider, location_detail=location, location=location.name,
        appointment_type=appointment_types["Manual Therapy & Dry Needling"], kind=Appointment.Kind.FOLLOW_UP,
        status=Appointment.Status.SCHEDULED, starts_at=next_visit, ends_at=next_visit + timedelta(minutes=45),
        created_by=scheduler,
    )

    # Patient 2: a cancelled visit and an outgoing referral for a second opinion.
    p2 = patients[2]
    cancelled_start = local_dt(-5, 15, 0)
    Appointment.objects.create(
        patient=p2, therapist=therapist, provider=provider, location_detail=location, location=location.name,
        appointment_type=appointment_types["Follow-Up Visit"], kind=Appointment.Kind.FOLLOW_UP,
        status=Appointment.Status.CANCELLED, starts_at=cancelled_start, ends_at=cancelled_start + timedelta(minutes=30),
        created_by=scheduler,
    )
    Referral.objects.create(
        patient=p2, direction=Referral.Direction.OUTGOING, provider_name="Dr. Alan Ng, MD — Sports Medicine",
        provider_contact="555-0166", status=Referral.Status.PENDING, created_by=scheduler,
        reason="Recurrent ankle instability despite PT; referred to evaluate for surgical stabilization.",
    )

    # Patient 3: brand-new patient — submitted intake, signed consents, a
    # missed first visit, and a rebooked telehealth evaluation.
    p3 = patients[3]
    IntakeSubmission.objects.create(
        patient=p3, form_version="v1",
        answers={"chiefComplaint": p3.diagnoses, "painLevel": 6, "goals": "Return to running without instability"},
        status=IntakeSubmission.Status.SUBMITTED, submitted_at=local_dt(-1, 8, 0), reviewed_by=therapist,
    )
    Consent.objects.create(
        patient=p3, kind=Consent.Kind.TREATMENT, document_version="v2026.1", status=Consent.Status.SIGNED,
        signature_name=f"{p3.first_name} {p3.last_name}", signed_at=local_dt(-1, 8, 5), recorded_by=scheduler,
    )
    Consent.objects.create(
        patient=p3, kind=Consent.Kind.PRIVACY, document_version="v2026.1", status=Consent.Status.SIGNED,
        signature_name=f"{p3.first_name} {p3.last_name}", signed_at=local_dt(-1, 8, 6), recorded_by=scheduler,
    )
    no_show_start = local_dt(-6, 13, 0)
    Appointment.objects.create(
        patient=p3, therapist=therapist, provider=provider, location_detail=location, location=location.name,
        appointment_type=appointment_types["Initial Evaluation"], kind=Appointment.Kind.EVALUATION,
        status=Appointment.Status.NO_SHOW, starts_at=no_show_start, ends_at=no_show_start + timedelta(minutes=60),
        created_by=scheduler,
    )
    rebooked_start = local_dt(1, 8, 0)
    Appointment.objects.create(
        patient=p3, therapist=therapist, provider=provider, location_detail=location, location=location.name,
        appointment_type=appointment_types["Initial Evaluation"], kind=Appointment.Kind.TELEHEALTH,
        status=Appointment.Status.SCHEDULED, starts_at=rebooked_start, ends_at=rebooked_start + timedelta(minutes=60),
        booking_source=Appointment.BookingSource.PATIENT_PORTAL, created_by=scheduler,
    )


class Command(BaseCommand):
    help = "Seed the 5 demo clients (tenants) with admins, staff, and a realistic clinical workspace."

    def add_arguments(self, parser):
        parser.add_argument(
            "--staff-password",
            required=True,
            help="Password assigned to seeded non-admin staff accounts (local demo only).",
        )

    def handle(self, *args, **options):
        actor = User.objects.filter(
            role=User.Role.SUPER_ADMIN, is_superuser=True, organization__isnull=True
        ).first()
        if actor is None:
            raise CommandError(
                "No platform super administrator was found. Run `manage.py bootstrap_demo "
                "--password <password>` first."
            )
        staff_password = options["staff_password"]

        for entry in DEMO_CLIENTS:
            if Organization.objects.filter(name=entry["clientName"]).exists():
                self.stdout.write(self.style.WARNING("Skipped existing client %s" % entry["clientName"]))
                continue
            provisioned = provision_client(
                {
                    "clientName": entry["clientName"],
                    "clientEmail": entry["clientEmail"],
                    "addressLine1": entry["addressLine1"],
                    "city": entry["city"],
                    "state": entry["state"],
                    "zipCode": entry["zipCode"],
                    "subscriptionTier": entry["subscriptionTier"],
                    "timezone": entry["timezone"],
                    "comments": entry["comments"],
                    "adminFirstName": entry["adminFirstName"],
                    "adminLastName": entry["adminLastName"],
                    "adminEmail": entry["adminEmail"],
                },
                actor,
            )
            client = provisioned.organization
            self.stdout.write(self.style.SUCCESS("Created client #%s %s" % (client.client_number, client.name)))

            staff_by_role: dict[str, User] = {}
            for first_name, last_name, email, role in entry["staff"]:
                staff = User(
                    username=email,
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    role=role,
                    organization=client,
                    is_active=True,
                )
                staff.set_password(staff_password)
                staff.full_clean()
                staff.save()
                staff_by_role[role] = staff

            therapist = staff_by_role.get(User.Role.THERAPIST)
            scheduler = staff_by_role.get(User.Role.SCHEDULER)
            if therapist and scheduler and client.name in PATIENT_ROSTERS:
                _seed_clinical_workspace(client, therapist, scheduler)
                self.stdout.write(
                    self.style.SUCCESS(
                        "  Seeded locations, providers, online booking, %d patients, and chart data"
                        % len(PATIENT_ROSTERS[client.name])
                    )
                )

            if entry["suspend"]:
                suspend_client(client, actor, "Demo suspended account for testing.")
                self.stdout.write(self.style.WARNING("Suspended client #%s" % client.client_number))

        self.stdout.write(self.style.SUCCESS("Demo client seeding complete."))
