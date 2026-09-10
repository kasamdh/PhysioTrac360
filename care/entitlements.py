"""Organization feature entitlement checks.

Kept deliberately separate from billing/subscription CRUD (care/api/super_admin.py)
so any view — clinical, scheduling, billing — can check "is this organization
entitled to feature X" without importing the admin API surface. This is the
single place that decision is made; callers must not infer entitlement from
anything else (subscription tier strings, org settings, etc.).
"""
from __future__ import annotations

from .models import Organization


def _current_subscription(organization: Organization):
    """The organization's most recent subscription record, or None if it
    has never been assigned one."""
    return organization.subscriptions.order_by("-starts_at").first()


def organization_has_feature(organization: Organization, feature_code: str) -> bool:
    """True if this organization is entitled to the given feature.

    An organization with no subscription record at all is treated as
    unrestricted (legacy/unmetered) — assigning a subscription is what turns
    on enforcement for that organization, so shipping this never
    retroactively breaks an organization nobody has configured yet. Once a
    subscription exists, entitlement is exactly `OrganizationSubscription
    .has_feature()` — the subscription's own feature set, and only while
    that subscription is active (trial/past_due/suspended/cancelled grant
    nothing).
    """
    subscription = _current_subscription(organization)
    if subscription is None:
        return True
    return subscription.has_feature(feature_code)


def organization_feature_codes(organization: Organization) -> set[str]:
    """Every feature code this organization is currently entitled to. Empty
    for an inactive/absent subscription; unlike `organization_has_feature`,
    this does NOT treat "no subscription" as unrestricted, since there is no
    sensible "every feature" set to enumerate — callers needing that
    permissive behavior should check `organization_has_feature` per-code
    instead of iterating this set."""
    subscription = _current_subscription(organization)
    if subscription is None or not subscription.is_active:
        return set()
    return set(subscription.features.values_list("code", flat=True))
