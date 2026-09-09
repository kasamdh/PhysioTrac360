# Source Motion PT — Product Roadmap

Companion to `PHYSIOTRAC360_CURRENT_ARCHITECTURE.md`. Read that first — this
roadmap only lists what's genuinely missing or partial, phased by the
priority order already established for this project (audit → tenant
isolation → dashboard → Patient 360 → scheduling → documentation → goals →
plan of care → authorizations → notifications → audit logging → licenses →
tests), extended into the remaining product-vision areas (billing, AI,
CRM, enterprise).

Every phase below assumes: no rebuilding working features, no new tenant
system, no silent auto-signing of clinical content, server-side enforcement
of every permission check, forward-only migrations, and tests for every new
tenant-isolation-sensitive path.

---

## PHASE 1 — Core EMR (mostly done; this phase is about closing the last
gaps, not building from scratch)

**Already complete** (see architecture doc): multi-tenant org model, RBAC,
patient chart + access guardrails, clinical note lifecycle + signature
immutability, PTA cosign policy, audit logging, license tracking with
90/60/30/14/7 alert tiers, provider scheduling with availability/time-off/
closures and double-booking prevention, public booking with rate limiting,
subscription/feature-flag model, session security (lockout/idle/absolute
timeout/concurrent-device limits), 213 tests including explicit tenant-
isolation tests.

**Remaining Phase 1 work:**

1. **Fix the `README.md` merge-conflict markers.** Trivial, zero risk,
   should happen first just to stop the bleeding on the most-read file in
   the repo.
2. ~~**Plan of Care as a first-class, alertable concept.**~~ **Done.**
   `Patient.plan_of_care_alert_tier`/`plan_of_care_color_bucket`
   (`care/models.py`) now compute a 30/14/7-day expiring-soon/critical/
   expired tier from the most recently documented `ClinicalNote` carrying a
   `plan_of_care_end` date, reusing a new shared `expiry_alert_tier`/
   `expiry_color_bucket` helper that `UserLicense.alert_tier`/`color_bucket`
   was refactored onto (behavior-preserving — same 22 pre-existing license
   tests still pass unchanged). Thresholds are configurable via
   `PLAN_OF_CARE_WARNING_DAYS` (default `30,14,7`), matching
   `LICENSE_WARNING_DAYS`'s pattern. `services.patient_compliance_findings`
   now emits `poc_expiring_soon` (non-blocking) and `poc_expired`
   (blocking) findings, which the dashboard alerts feed and the patient
   workspace's compliance-findings panel already render generically — no
   frontend changes were needed. No migration required (computed, not
   stored, matching the codebase's existing "don't store what's derivable"
   convention). 6 new tests added (`PlanOfCareAlertTests`); full suite
   (219 tests) passes.
3. **Authorization tracking** (insurance authorization number, visits
   authorized/used/remaining, start/end date, status). Genuinely new — no
   existing model to extend. Should mirror the `UserLicense` alert-tier
   pattern for expiring/exhausted authorizations, and hook into
   `Appointment` completion the way license expiry already hooks into
   `user_management.py`'s status transitions (visits-used auto-increment on
   a completed visit, never on scheduling alone).
4. **Notification center** (persisted, read/unread/dismissed, not just
   computed-on-render banners). The pieces that should *feed* it already
   exist as computable facts (license alerts, note compliance findings,
   POC/authorization alerts once #2/#3 land, unsigned notes, new leads once
   CRM lands) — this phase is about the persistence/read-state layer and
   API, not inventing new alert logic.
5. **A handful of additional tenant-isolation tests** for the two new
   models in #2/#3, following the exact pattern already used for
   `UserLicense`/`Provider`/`AppointmentType` (`test_cross_organization_*`).

## PHASE 2 — Clinical Intelligence

1. **Compliance engine upgrade to explicit PASS/WARNING/BLOCKING tiers.**
   `note_compliance_findings` already returns findings with a
   `finalization_blocker` boolean — this phase formalizes a third state
   (non-blocking WARNING vs. informational PASS-with-note) and extends
   coverage toward the Medicare 8-minute-rule/timed-unit groundwork,
   without ever auto-modifying signed documentation (unchanged invariant).
2. **CPT/treatment-time engine.** `NoteIntervention` already captures
   minutes/units/`is_timed` per line item (the "treatment timer"). This
   phase adds configurable unit-suggestion rules on top of the existing
   summed minutes, surfaced as "Suggested Units" + "Documentation Support"
   for clinician review — never auto-submitted, matching the product
   vision's explicit requirement.
3. **Organization-customizable documentation templates.** Today note
   sections are a fixed `SECTIONS_BY_TYPE` map in the frontend per note
   type. This phase makes the section list admin-configurable per org
   without breaking existing signed notes (which must keep rendering their
   original section layout regardless of later template edits — an
   immutability-adjacent constraint, not just a UX one).
4. **Additional note types**: Cancellation Note, No-Show Note, Telephone
   Encounter, Administrative Note — straightforward additions to
   `ClinicalNote.Type`, each requiring only a migration and frontend
   section-list entry, no architectural change.

## PHASE 3 — Billing / Insurance

1. **Structured CPT/ICD-10 fields on `Superbill`** (today `codes` is a
   free JSON blob) — needed before any claim lifecycle work is meaningful.
2. **Claim model + lifecycle** (draft/ready/submitted/accepted/rejected/
   denied/paid/partially_paid), built as a clean service interface
   (`BillingService`) so a real clearinghouse integration can be added
   later without a rewrite — matching the product vision's explicit
   "don't build a full clearinghouse integration yet" scope limit.
3. **Cash-pay packages/memberships** as their own models, deliberately
   *not* coupled to the insurance-billing models (`PaymentRecord`/
   `Superbill`), per the product vision's explicit separation requirement.
4. **Billing-focused reports**: outstanding balances, collections,
   revenue — these were explicitly deferred in `admin_config.py`'s current
   `operational_report` ("deliberately does not fabricate anything") and
   should stay honest (real derived numbers only) once the underlying
   billing data exists to derive them from.

## PHASE 4 — AI Automation

1. **Formal `AIProvider`/`AIService` abstraction.** The deterministic
   template engine in `services.py` already behaves like a safe reference
   implementation of this interface (fixed `provider="local-template"`,
   `model_version` field already on `AIArtifact`) — this phase is mostly
   about extracting an actual interface/protocol so a real provider
   (Bedrock/Claude/OpenAI) can be swapped in later behind
   `AI_DRAFTING_ENABLED`, without changing `AIArtifact`'s safety contract
   (source-fingerprinted, draft-only, therapist-review-required, never
   auto-signed).
2. **Ambient documentation pipeline** (recording → transcription →
   structured extraction → draft). `VoiceCapture` already models the
   "transcript reviewed, no raw audio" end state and requires consent
   before save — this phase is the transcription step itself, which must
   not ship until a HIPAA-eligible transcription provider + BAA is in
   place (explicit prerequisite, already called out in the README).
3. Do not start this phase until Phase 1–2 are stable, per the product
   vision's own sequencing rule ("Do NOT jump to advanced AI before the
   clinical architecture is stable").

## PHASE 5 — Patient Engagement / CRM

Genuinely unbuilt — no `Lead` model, no pipeline stage, no lead-source
tracking exists today.

1. **Lead model** + pipeline stages (new/contacted/discovery
   call/evaluation scheduled/evaluation completed/converted/lost) + lead
   source enum.
2. **Manual-trigger-only automation** (reminders, reactivation,
   birthday/review-request messages) — explicitly opt-in per the product
   vision ("do not send messages unless explicitly configured"); should
   reuse the existing best-effort, non-blocking email pattern already
   proven in `notifications.py`.
3. **CRM/referral reporting** once the underlying Lead/Referral data
   exists to report on.

## PHASE 6 — Enterprise Features

1. **MFA/SSO.** `User.must_use_mfa` already exists as a flag but nothing
   enforces it yet — this is the highest-value security item left.
2. **PostgreSQL row-level security**, to back up (not replace) the
   existing application-layer tenant scoping — this is the single biggest
   gap between "well-isolated at the app layer" (true today) and
   defense-in-depth production readiness.
3. **User↔Location scoping**, if multi-location tenants need staff/patient
   assignment narrower than whole-organization (currently only `Provider`
   is Location-scoped) — a real product decision, not just an engineering
   task; worth confirming demand before building.
4. **Design-system migration completion** — finish moving the remaining
   legacy `styles.css`/BEM pages (Dashboard, Schedule) onto the Tailwind +
   shared `components/ui/*` system already used by the newer pages, so the
   whole app is visually and structurally consistent (this is explicitly
   called out as a goal in the product vision and is currently a known,
   in-progress migration, not a defect).
5. **Global cross-entity search** (patients/MRN/phone/email/appointments/
   providers in one box) — today search exists per-page (patient list,
   documentation list) but not as a single global search.
6. **Task system** — no `Task` model exists yet; genuinely new.

---

## What is explicitly *not* being built right now, and why

- No real LLM/transcription integration until Phase 4, and even then not
  until a BAA and HIPAA-eligible provider are contractually in place — this
  matches both the product vision's non-negotiables and the project's own
  existing `AI_DRAFTING_ENABLED` flag design.
- No payment-card handling anywhere — `PaymentRecord`/`Superbill` are
  processor-*reference*-only by design, and that design is correct and
  should not change even when Phase 3 billing work lands.
- No claim-clearinghouse integration in Phase 3 — service interfaces only,
  matching the product vision's explicit scope limit.
- No hard-delete of tenants, users, or clinical data anywhere in the
  roadmap — every lifecycle model (`Organization`, `User`) already uses
  soft-delete (`archived_at`/`suspended_at`), and that pattern should
  continue for every new model (`Authorization`, `Lead`, `Task`, etc.).

## Sequencing rationale (why this order)

The remaining-Phase-1 items (Plan of Care alerts → Authorization tracking →
Notification center) are ordered specifically because each one is
incrementally riskier than the last, and each one builds on a pattern the
previous one already proved:

- Plan of Care alerts = copy the already-tested `UserLicense.alert_tier`
  pattern onto an existing field set. Lowest risk, immediate clinical value.
- Authorization tracking = a new model, but its alerting logic is now a
  *second* proven copy of the same pattern, and its "auto-decrement visits
  on completed appointment" behavior can reuse the exact transactional
  `select_for_update()` pattern already used in `booking.py` and
  `user_management.py`.
- Notification center = the first genuinely new piece of infrastructure
  (persisted read state), but by the time it's built there are three real
  alert sources (license, POC, authorization) to validate it against
  instead of designing it speculatively against one.
