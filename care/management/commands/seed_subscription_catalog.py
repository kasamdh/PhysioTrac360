"""Seed the platform-wide Feature and SubscriptionPlan catalog.

These are reference data, not per-tenant data — every organization draws
from the same Feature/SubscriptionPlan rows (care/models.py), so unlike
seed_demo_clients this creates no organizations or users. Idempotent
(get_or_create by code) and safe to re-run; it never removes a feature or
plan a super admin has since edited, only fills in ones that are missing.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from care.models import Feature, SubscriptionPlan


FEATURES = [
    ("ai_scribe", "AI Scribe", "AI-assisted draft documentation (progress notes, discharge summaries, handoffs)."),
    ("billing", "Billing", "Cash-pay superbills and payment recording."),
    ("claims", "Claims", "Insurance claim lifecycle tracking."),
    ("patient_portal", "Patient Portal", "Self-service patient access to their own chart."),
    ("telehealth", "Telehealth", "Video-visit appointment types and workflow."),
    ("advanced_analytics", "Advanced Analytics", "Extended operational and financial reporting."),
    ("hep", "Home Exercise Program", "Home exercise program authoring and tracking."),
    ("outcome_measures", "Outcome Measures", "Standardized outcome-measure capture and trending."),
    ("crm", "CRM", "Lead and referral pipeline tracking."),
    ("mobile_care", "In-Home PT", "In-home PT request intake, provider matching, and home-visit scheduling."),
]

# (code, name, monthly_price, annual_price, provider_seat_limit, feature_codes)
PLANS = [
    ("free_trial", "Free Trial", 0, 0, 3, ["hep", "outcome_measures"]),
    ("starter", "Starter", 99, 990, 3, ["hep", "outcome_measures"]),
    ("professional", "Professional", 249, 2490, 10, ["hep", "outcome_measures", "billing", "crm", "ai_scribe"]),
    (
        "enterprise",
        "Enterprise",
        499,
        4990,
        50,
        [
            "hep", "outcome_measures", "billing", "claims", "crm", "ai_scribe", "telehealth",
            "advanced_analytics", "mobile_care",
        ],
    ),
    ("custom", "Custom", 0, 0, 1, []),
]


class Command(BaseCommand):
    help = "Seed the platform Feature and SubscriptionPlan catalog (idempotent)."

    def handle(self, *args, **options):
        with transaction.atomic():
            features_by_code = {}
            created_features = 0
            for code, name, description in FEATURES:
                feature, created = Feature.objects.get_or_create(
                    code=code, defaults={"name": name, "description": description}
                )
                features_by_code[code] = feature
                created_features += int(created)

            created_plans = 0
            for code, name, monthly_price, annual_price, seat_limit, feature_codes in PLANS:
                plan, created = SubscriptionPlan.objects.get_or_create(
                    code=code,
                    defaults={
                        "name": name,
                        "monthly_price": monthly_price,
                        "annual_price": annual_price,
                        "provider_seat_limit": seat_limit,
                    },
                )
                created_plans += int(created)
                if created:
                    plan.features.set([features_by_code[c] for c in feature_codes])

        self.stdout.write(
            self.style.SUCCESS(
                f"Subscription catalog seeded: {created_features} feature(s), {created_plans} plan(s) created."
            )
        )
