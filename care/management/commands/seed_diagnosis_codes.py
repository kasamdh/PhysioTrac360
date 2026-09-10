"""Seed a starter set of ICD-10-CM diagnosis codes commonly used in
outpatient physical therapy documentation and billing.

This is reference data, not per-tenant data — every organization draws from
the same DiagnosisCode rows (care/models.py), matching how
seed_subscription_catalog seeds the platform Feature/SubscriptionPlan
catalog. Idempotent (get_or_create by code) and safe to re-run; it never
removes or overwrites a code an admin has since edited, only fills in ones
that are missing.

This starter set is deliberately not a full ICD-10-CM master list (tens of
thousands of codes) — it covers common outpatient PT diagnoses (spine,
shoulder, knee, hip, ankle/foot, elbow/wrist, general pain/weakness/gait,
post-surgical status, balance/neuro). Extend CODES below, or add rows
through the Django admin, as billing staff need additional codes.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from care.models import DiagnosisCode

# (code, description)
CODES = [
    # Spine
    ("M54.2", "Cervicalgia"),
    ("M54.6", "Pain in thoracic spine"),
    ("M54.50", "Low back pain, unspecified"),
    ("M54.30", "Sciatica, unspecified side"),
    ("M54.31", "Sciatica, right side"),
    ("M54.32", "Sciatica, left side"),
    ("M51.26", "Intervertebral disc disorder with radiculopathy, lumbar region"),
    ("M48.06", "Spinal stenosis, lumbar region"),
    ("M43.16", "Spondylolisthesis, lumbar region"),
    ("M62.830", "Muscle spasm of back"),
    # Shoulder
    ("M25.511", "Pain in right shoulder"),
    ("M25.512", "Pain in left shoulder"),
    ("M75.100", "Unspecified rotator cuff tear/rupture of right shoulder, not specified as traumatic"),
    ("M75.101", "Unspecified rotator cuff tear/rupture of left shoulder, not specified as traumatic"),
    ("M75.30", "Calcific tendinitis of unspecified shoulder"),
    ("M75.00", "Adhesive capsulitis of unspecified shoulder"),
    # Elbow / wrist / hand
    ("M77.10", "Lateral epicondylitis, unspecified elbow"),
    ("M77.11", "Lateral epicondylitis, right elbow"),
    ("M77.12", "Lateral epicondylitis, left elbow"),
    ("G56.00", "Carpal tunnel syndrome, unspecified upper limb"),
    # Hip
    ("M25.551", "Pain in right hip"),
    ("M25.552", "Pain in left hip"),
    ("M16.11", "Unilateral primary osteoarthritis, right hip"),
    ("M16.12", "Unilateral primary osteoarthritis, left hip"),
    ("Z96.641", "Presence of right artificial hip joint"),
    ("Z96.642", "Presence of left artificial hip joint"),
    # Knee
    ("M25.561", "Pain in right knee"),
    ("M25.562", "Pain in left knee"),
    ("M17.11", "Unilateral primary osteoarthritis, right knee"),
    ("M17.12", "Unilateral primary osteoarthritis, left knee"),
    ("S83.511A", "Sprain of anterior cruciate ligament of right knee, initial encounter"),
    ("S83.512A", "Sprain of anterior cruciate ligament of left knee, initial encounter"),
    ("Z96.651", "Presence of right artificial knee joint"),
    ("Z96.652", "Presence of left artificial knee joint"),
    # Ankle / foot
    ("S93.401A", "Sprain of unspecified ligament of right ankle, initial encounter"),
    ("S93.402A", "Sprain of unspecified ligament of left ankle, initial encounter"),
    ("M76.61", "Achilles tendinitis, right leg"),
    ("M76.62", "Achilles tendinitis, left leg"),
    ("S86.011A", "Strain of right Achilles tendon, initial encounter"),
    ("S86.012A", "Strain of left Achilles tendon, initial encounter"),
    # General pain / weakness / function
    ("M79.601", "Pain in right arm"),
    ("M79.602", "Pain in left arm"),
    ("M79.604", "Pain in right leg"),
    ("M79.605", "Pain in left leg"),
    ("M79.7", "Fibromyalgia"),
    ("M62.81", "Muscle weakness (generalized)"),
    ("R26.2", "Difficulty in walking, not elsewhere classified"),
    ("R26.81", "Unsteadiness on feet"),
    ("R27.0", "Ataxia, unspecified"),
    ("R29.6", "Repeated falls"),
    # Post-surgical / status
    ("Z98.890", "Other specified postprocedural states"),
]


class Command(BaseCommand):
    help = "Seed a starter ICD-10-CM diagnosis code catalog for outpatient PT (idempotent)."

    def handle(self, *args, **options):
        with transaction.atomic():
            created = 0
            for code, description in CODES:
                _, was_created = DiagnosisCode.objects.get_or_create(
                    code=code, defaults={"description": description}
                )
                created += int(was_created)
        self.stdout.write(self.style.SUCCESS(f"Diagnosis code catalog seeded: {created} code(s) created."))
