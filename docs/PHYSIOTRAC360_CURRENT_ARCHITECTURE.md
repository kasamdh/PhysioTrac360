# Source Motion PT — Current Architecture

Audit date: 2026-09-08. This document reflects the codebase as it actually
exists today, verified by reading `care/models.py`, `care/access.py`,
`care/urls.py`, `care/api/urls.py`, `config/settings.py`,
`care/tests.py`, the full `care/` service-layer module set, the full
`care/api/` package, and the React frontend under `frontend/src/`.

It supersedes the narrative in `docs/phase1-architecture.md` and
`docs/implementation-checklist.md` (kept in place, not deleted — they were a
forward-looking plan written earlier and most of what they call "not yet
built" is now built). Treat *this* document as the source of truth for what
exists; treat `PHYSIOTRAC360_PRODUCT_ROADMAP.md` as the source of truth for
what's next.

**Headline finding: this is not a green-field or thin prototype.** It is a
working, tested, multi-tenant PT EMR with real tenant isolation, real RBAC,
immutable signed documentation, append-only audit logging, license tracking,
provider scheduling with conflict prevention, a deterministic (non-LLM)
AI-draft engine with strict source-provenance, and 213 passing tests
including explicit cross-tenant isolation tests. Anything in the product
vision that looks unbuilt below should be treated as "the next increment,"
not "starting from zero."

---

## 1. Stack

| Layer | Technology |
|---|---|
| Backend | Django 5.2, Python 3.11+ |
| Database | SQLite (dev convenience only) / PostgreSQL via `psycopg[binary]` (production path, driven by `POSTGRES_*` env vars) |
| Frontend | React 19 + TypeScript 5.9 + Vite 7 |
| Styling | Tailwind CSS 4 (CSS-first `@theme`) **and** a hand-written CSS custom-property design-token system (`styles.css`) — mid-migration, both active simultaneously |
| Component library | Hand-rolled shadcn/ui-style components (`class-variance-authority`, Radix dropdown-menu, `lucide-react`) under `frontend/src/components/ui/` |
| State/data | No state-management or data-fetching library (no Redux/Zustand/React Query). Local `useState`/`useEffect` per feature, calling a typed `fetch`-based API client directly |
| Routing (frontend) | Hand-rolled hash routing in `App.tsx`, no router library |
| Auth | Django session cookies (HttpOnly, SameSite=Lax) + CSRF double-submit token, never a bearer/localStorage token |
| File storage | `MEDIA_ROOT` (public, org logos only) vs. `PRIVATE_MEDIA_ROOT` (patient documents, license documents — no URL route ever maps to it; every read goes through an authenticated, audited download view) |

Both the legacy server-rendered app (Django templates under `templates/care/`)
and the React SPA (served at `/app/` from `frontend/dist/`) are live at once,
mounted from the same Django project and sharing the same session/CSRF model
and the same lower-level Python modules — see §4.

## 2. Multi-tenant hierarchy

```
Platform Super Admin (organization=None, is_superuser=True)
    ↓  (no standing clinical access — see §6.4)
Organization  ("client", client_number 1000+, status active/suspended, archived_at soft-delete)
    ↓
Location  (per-org clinic/treatment site; Provider is M2M to Location)
    ↓
User  (organization FK, role, status) — NOT currently FK'd to a Location
    ↓
Patient  (organization FK) — NOT currently FK'd to a Location
```

Note the one structural gap versus the idealized hierarchy: `Provider` is
scoped to `Location` (M2M, for availability/booking), but `User` and
`Patient` are scoped only to `Organization`, not to a specific `Location`.
For a single-location tenant this is invisible; for a multi-location tenant
it means "front desk staff scoped to Location A only" isn't a thing yet —
worth a deliberate decision before building it (see roadmap).

### Canonical tenant-isolation code path (`care/access.py`)

Every authenticated code path — legacy views and API views alike — is
expected to route through this module rather than trusting a client-supplied
id:

```python
def organization_required(user):
    if is_platform_super_admin(user):
        raise PermissionDenied(...)      # super admin has NO standing org
    if not user.organization_id:
        raise PermissionDenied(...)
    if user.organization.archived_at is not None:
        raise PermissionDenied(...)
    if not user.organization.is_active or user.organization.status == SUSPENDED:
        raise PermissionDenied(...)
    return user.organization

def patients_for(user, *, clinical=True):
    organization = organization_required(user)
    queryset = Patient.objects.filter(organization=organization)
    if not clinical:
        return queryset
    if user.role in {ADMIN, DIRECTOR, COMPLIANCE}:
        return queryset
    if user.role in {THERAPIST, ASSISTANT}:
        return queryset.filter(assigned_therapist=user)
    return queryset.none()

def require_patient_access(request, patient, *, clinical=True) -> Patient:
    # Never trusts a browser-supplied patient id in isolation — re-derives
    # the allowed set every time, and audits denials (no PHI in metadata).
```

This single module is the choke point for: org-suspension/archival checks,
row-level patient scoping, role-based caseload narrowing (a THERAPIST only
sees their own assigned patients), and denied-access audit logging. The API
layer wraps it in one more helper, `organization_or_error(request, roles=…)`
(`care/api/utils.py`), used by nearly every JSON view. The **public** booking
surface (`care/api/public_booking.py`, `care/booking.py`) has no
authenticated user at all, so it re-derives the tenant boundary independently
by resolving the organization from the URL slug and filtering every
subsequent query by it — documented in-code as a deliberate, parallel
tenant-isolation implementation for the unauthenticated case.

**Verified by tests**, not just by reading the code:
`test_seed_demo_clients_creates_isolated_tenants`,
`test_tenant_isolation_prevents_cross_org_status_changes`,
`test_documentation_list_is_tenant_isolated`,
`test_cross_organization_provider_is_rejected`,
`test_cross_organization_appointment_type_is_rejected`,
`test_organization_admin_cannot_manage_users_in_another_org`,
`test_organization_admin_cannot_revoke_sessions_for_another_orgs_user`,
`test_another_organizations_admin_cannot_download_this_license_document`.

**Known, documented, intentional gap:** application-layer scoping only —
there is no PostgreSQL row-level security yet. Both this doc and the code
comments call that out explicitly as required before real PHI in production.

## 3. Data model (`care/models.py`, 1669 lines, 22 migrations)

All PHI-bearing models inherit `UUIDTimeStampedModel` (UUID pk, `created_at`,
`updated_at`).

**Tenant/platform**: `Organization` (status, subscription_tier,
`pta_cosign_required` policy flag, soft-delete via `archived_at`/
`suspended_at`), `ClientNumberSequence` (locked counter for client numbers),
`ClientInvitation` (hashed, expiring, single-use), `PrivilegedAccessGrant`
(break-glass, time-boxed, reasoned — see §6.4).

**Scheduling**: `Location`, `AppointmentType` (org-configurable label,
separate from the fixed `Appointment.Kind` clinical enum), `Provider`
(optionally linked to a `User`), `ProviderAppointmentType`,
`ProviderAvailability` (recurring weekly windows, multiple rows per day
supported for split shifts), `ProviderTimeOff`, `LocationClosure`,
`BookingConfiguration` (per-org opt-in online booking policy), `Appointment`
(kind, status, booking_source, a `CheckConstraint` that `ends_at > starts_at`,
and model-level double-booking rejection as a backstop behind the
concurrency-safe `select_for_update()` checks in the creation paths).

**SaaS**: `Feature`, `SubscriptionPlan`, `OrganizationSubscription`
(trial/active/past_due/suspended/cancelled, `has_feature()` gate).

**Identity**: `User` (`AbstractUser` subclass; roles: `super_admin`, `admin`,
`director`, `therapist`, `assistant`, `scheduler`, `biller`, `compliance`,
`patient`; status: active/inactive/locked_out/suspended/deleted; lockout
tracking; `must_change_password`), `UserSession` (independent
per-device/browser session tracking layered on Django sessions — see §6.3),
`UserLicense` (multiple licenses per clinician, `alert_tier`/`color_bucket`
computed from `expires_at`, never stored — matches the exact 90/60/30/14/7
escalation the product vision asks for, already shipped).

**Clinical**: `Patient`, `Referral`, `Consent` (versioned, signed,
immutable), `IntakeSubmission` (structured JSON answers), `PatientDocument`
(private storage), `ClinicalNote` (types: evaluation/daily/progress/
re_evaluation/discharge/handoff; statuses: draft/review_required/signed/
amended; **immutable once signed** — enforced in `save()`, raises if a signed
row is written to again; structured JSON sub-blobs for ROM/MMT/discharge
detail; snapshotted `diagnosis_snapshot`/`precautions_snapshot`; embedded
plan-of-care fields — start/end/frequency/duration/reassessment_due —
**not yet a separate model**, see roadmap; PTA cosign fields), `NoteAddendum`
(signed notes only, original never mutated), `NoteIntervention` (the
"treatment timer" line-item table — description/body_region/minutes/units/
is_timed — summed for billing-adjacent reporting later), `FunctionalGoal`
(baseline/target/current/unit/target_date/status, `progress_percent`
computed), `OutcomeScore` (LEFS/ODI/NDI/QuickDASH/TUG/Berg/PSFS, one per
patient/measure/day, deterministic trend logic in `services.py`).

**AI safety boundary**: `AIArtifact` — every AI-adjacent draft (progress,
discharge, handoff, goal suggestion, HEP suggestion, patient summary,
compliance check) is stored here with `source_note_ids` + a sha256
`source_fingerprint` of the exact signed notes it was built from, a fixed
`safety_notice` ("Draft only. A licensed therapist must verify, edit,
approve, and sign."), and a status machine (draft → approved/rejected →
applied). Never auto-signs; never becomes a `ClinicalNote` without an
explicit clinician "apply" action gated by `can_sign_notes`.

**HEP/voice/messaging/billing**: `HomeProgram`/`HomeExercise`,
`VoiceCapture` (transcript metadata only — **no raw audio stored**, consent
required before save), `SecureMessage`, `Superbill` (JSON `codes`, no
CPT/ICD-10 structured fields yet), `PaymentRecord` (processor
**reference** only, `payment_processor_reference` — deliberately never a
place cardholder data could land).

**Audit**: `AuditEvent` — append-only (`save()`/`delete()` both raise on
attempted mutation of an existing row; enforced a second time at the Django
admin layer via `has_change_permission`/`has_delete_permission`), organization
always resolved and required (`record_audit_event` raises `ValueError` if it
can't determine a tenant), metadata deliberately narrative-free (no PHI, no
clinical text — action/object/ids/IP/route only).

## 4. Service layer (`care/*.py`, function-module style — not class-based
`XService` objects, but the same separation of concerns)

| Module | Responsibility |
|---|---|
| `access.py` | Canonical tenant + RBAC gate (§2) |
| `services.py` | Audit-write entrypoint (`record_audit_event`), outcome trend computation, note compliance findings, goal-suggestion templates, deterministic draft composition (`compose_draft`) from signed notes only, HEP suggestion review cards |
| `note_management.py` | Note permission predicates + sign/cosign/addendum state machine, shared by both the legacy views and the API views so both surfaces enforce identical rules |
| `booking.py` / `availability.py` | Authoritative, re-validated public booking slot computation and transactional booking creation (provider row locked via `select_for_update()` to close the double-booking race) |
| `client_management.py` | Tenant provisioning (org + first admin + invitation), suspend/reactivate/archive lifecycle, all soft-delete (never hard-deletes a tenant) |
| `user_management.py` | Account status transitions with two safety guards: never remove an org's last active admin; never strip clinical access from a therapist/assistant with an active caseload/future visits/unsigned notes without reassignment. License-expiry suspension deliberately bypasses these guards (compliance overrides discretion) but logs what it bypassed |
| `privileged_access.py` | Break-glass grant request/revoke, fully audited both directions |
| `session_management.py` | Per-device session tracking, role-based concurrency limits, idle/absolute timeout enforcement — **documented fail-open** for sessions created before this feature existed or via test helpers |
| `notifications.py` | Best-effort transactional email (invitations only); swallows transport errors so email outages never block provisioning |
| `forms.py` | Django forms that exclude tenant/actor/signature fields by design — those are always server-set, never form-editable; FK querysets scoped to the given organization |
| `admin.py` | Django admin registrations; `AuditEventAdmin` enforces immutability at the admin layer too |
| `management/commands/` | `bootstrap_demo` (dev-only super admin), `seed_demo_clients` (idempotent 5-tenant realistic dataset), `check_license_expirations` (external-scheduler-invoked sweep — **does not self-schedule**, must be wired to cron/Task Scheduler in production) |

## 5. API layer (`care/api/`, versioned at `/api/v1/`)

Explicit allow-list routing (`care/api/urls.py`) — no DRF router/viewset
auto-generation, no DRF `ModelSerializer` introspection either
(`serializers.py` is hand-written, per-shape functions with opt-in
contact/clinical-detail flags — a deliberate minimum-necessary pattern, e.g.
`serialize_patient(include_contact=…)`).

- **Auth/session**: `auth/csrf`, `auth/login`, `auth/logout`,
  `auth/change-password`, `auth/me`, `auth/sessions*` (self-service device
  list/revoke).
- **Dashboard/patients/schedule**: role- and caseload-scoped throughout.
- **Patient workspace** (`workflow_views.patient_workspace`): one bundled
  call returns only the panels the caller's role permits — clinical bundle
  (notes/goals/outcomes/compliance findings/AI artifacts/home programs/voice
  captures/merged timeline), operations bundle (consents/intake/referrals/
  appointments/superbills/payments, each independently role-gated),
  safety bundle (recent audit events, `ADMIN`/`DIRECTOR`/`COMPLIANCE` only).
  This is a genuinely good performance pattern — one round trip instead of
  N — but it does mean the frontend's patient-detail tab structure (5 tabs:
  Overview/Documentation/Care plan/Operations/Safety & audit) is coarser
  than a fully granular Patient-360 tab set; see roadmap.
- **Documentation**: `note_views.py` — list/create/detail/sign/cosign/
  addendum/interventions, sharing `note_management.py` with the legacy
  surface.
- **Super admin / break-glass** (`super_admin.py`): client CRUD, cross-tenant
  user management, invitations — none of that requires a privileged-access
  grant since it never touches PHI. Only `privileged_patients*` does, gated
  by `_require_active_grant`, which returns a structured
  `PRIVILEGED_ACCESS_REQUIRED` 403 telling the frontend exactly what to do,
  and every read taken under a grant is separately audited
  (`privileged_access.patient_list_viewed`, `.patient_viewed`).
- **Admin config**: locations, appointment types, and an `operational_report`
  that is explicitly real/derived-only (no fabricated revenue/NPS metrics —
  stated in-code as a deliberate scope limit).
- **Public booking** (`public_booking.py`): the one unauthenticated surface;
  IP-based rate limiting (dev-only cache backend — needs a shared backend
  like Redis for correctness under multiple worker processes in production);
  response payloads are deliberately minimized (no internal ids, no admin
  data).
- **Documents/licenses**: private storage, permission-checked download
  views, every download audited (not just upload), 15MB upload cap,
  extension allow-list enforced at the model layer.

Every non-public endpoint sits behind `api_login_required` (401 JSON, not a
redirect — this recovers a specific revocation reason from `UserSession`
before Django's own `get_user()` flushes the stale session key) plus
`organization_or_error(request, roles={...})`.

## 6. Security posture

### 6.1 Headers/cookies (`config/settings.py`)
HttpOnly + SameSite=Lax session and CSRF cookies; `SECURE_SSL_REDIRECT`/
`SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE`/HSTS all driven by
`DJANGO_SECURE_COOKIES`; `X_FRAME_OPTIONS=DENY`;
`SECURE_CONTENT_TYPE_NOSNIFF=True`; `SECURE_REFERRER_POLICY=same-origin`.

### 6.2 Login/lockout
`FAILED_LOGIN_LOCKOUT_THRESHOLD` (default 5) / `LOCKOUT_DURATION_MINUTES`
(default 15), generic error message on failed login regardless of failure
reason (anti-enumeration), lockout self-heals lazily for display but only
truly clears on the next real authentication attempt.

### 6.3 Sessions
`IDLE_TIMEOUT_MINUTES`(15)/`ABSOLUTE_SESSION_HOURS`(12) enforced per-request
via `validate_session`; `SESSION_LIMITS_BY_ROLE` caps concurrent devices per
role (super_admin/admin/biller/scheduler = 1, therapist/assistant = 2,
patient = 3), oldest session revoked first when exceeded. **Documented gap**:
sessions created before this feature existed (or via `Client.force_login()`
in tests) are untracked and fail open — not enforced, not limited.

### 6.4 Break-glass super-admin access
Platform super admins have **zero standing clinical access** — enforced at
the lowest level (`organization_required` rejects them outright). The only
path to a tenant's PHI is a time-boxed (`1|4|24` hours), reasoned
`PrivilegedAccessGrant`, fully audited on request, on every read taken under
it, and on revocation.

### 6.5 PHI storage
Patient documents and license documents live under `PRIVATE_MEDIA_ROOT`,
which has **no URL route at all** — every read is an authenticated,
permission-checked, audited view, never a static file serve. `media/` and
`private_media/` are correctly gitignored (verified: zero tracked files in
either directory).

### 6.6 Known, already-documented limitations (not surprises — flagged
in-repo)
No PostgreSQL RLS yet (app-layer scoping only); no MFA/SSO yet
(`must_use_mfa` flag exists but nothing enforces it); Django admin site
itself is a broad-trust surface without the app's own tenant scoping (a
generic Django-admin risk, not specific to this app); rate limiting on
public booking uses Django's default (per-process) cache backend, needs a
shared backend before multi-process production deployment; `AI_DRAFTING_ENABLED`
exists and defaults to `False` — no real LLM/transcription provider is wired
in yet, by design, pending a BAA and HIPAA-eligible provider.

## 7. Frontend architecture

Single-origin deployment: Vite dev proxies `/api` and `/media` to Django in
development; in production, `frontend/dist` is built and served by Django
itself at `/app/` (`STATICFILES_DIRS` includes the Vite build output).

- **Routing**: hand-rolled hash routing in `App.tsx`, with two path-based
  exceptions handled entirely outside the authenticated shell:
  `/book/:slug` (public booking) and the invitation-activation link.
- **Auth bootstrap**: `api.me()` on mount; global session-invalidation is
  event-driven — any request returning a coded 401 fires
  `notifySessionEnded()`, clearing the in-memory user immediately (defense
  in depth beyond just relying on stale UI state).
- **API client** (`api/client.ts`): plain `fetch`, `credentials: "include"`,
  CSRF token fetched once and cached, re-sent as `X-CSRFToken`; a single
  `request<T>()` helper centralizes error handling into a typed `ApiError`.
- **Nav** (`AppShell.tsx`/`HomeTopBar.tsx`): tab visibility is recomputed
  every render from `user.capabilities`/`role` — a stale hash can't expose a
  disallowed page, since the page itself checks capability before rendering,
  not just the nav.
- **Design system**: `frontend/src/components/ui/*` — a real, shared
  shadcn-style component set (button/input/label/card/dialog/dropdown-menu/
  badge/table/select/textarea/status-tabs/status-banner/license-banner/
  segmented-control/action-menu-trigger) — used by newer, Tailwind-migrated
  pages (`ClientManagementPage`, `AllUsersPage`, `DocumentationWorkspace`,
  `ModuleGrid`). Older pages (Dashboard, Schedule) still use the legacy
  `styles.css` token/BEM system. Both systems intentionally share the same
  brand color values so they render consistently — but the migration is not
  finished, and that's worth planning as deliberate design-system work
  rather than accidental drift.
- **37 feature files + 12 documentation-workspace files** already cover:
  login/session UI, org-admin home, super-admin home + administration hub,
  patient list/workspace/forms, day/week/workWeek/month drag-and-drop
  schedule, per-note-type structured documentation editor (ROM/strength/
  intervention tables, goals section, sign/addendum/cosign dialogs), clinic
  settings, reports, org user management, license management UI, client
  management (search/filter/status tabs/suspend/reactivate/archive),
  platform-wide user directory, break-glass privileged-access UI, and a
  full unauthenticated public-booking wizard.
- Responsive-design audit screenshots already exist in the repo
  (`frontend/audit2_{ipad,iphone,tablet}_*.png`) for clinic settings,
  reports, users, and the patient workspace — indicating tablet/phone
  layouts have already been checked at least once, not merely assumed.

## 8. Testing (`care/tests.py`, 4777 lines, 213 tests, 11 test classes)

`SubscriptionFoundationTests`, `ProviderLocationFoundationTests`,
`ClinicalWorkflowTests`, `PublicBookingTests`, `ChangePasswordTests`,
`UserAccountStatusTests`, `SessionManagementTests`, `LicenseExpirationTests`,
`UserLicenseTests`, `DocumentationApiTests`, `PtaCosignTests`.

Explicitly covers, by name: cross-org rejection for providers/appointment
types, tenant isolation for status changes/session revocation/documentation
lists/license documents, signed-note API immutability, addendum-only-on-
signed-notes, intervention-lock-on-sign, PTA cosign routing (including the
org opt-out path), demo-tenant isolation. This already satisfies the
project's stated non-negotiable ("a Client 1000 user must never access
Client 1001 data") at both the service layer and the API layer.

## 9. Known defects to fix opportunistically

- **`README.md` still contains unresolved git merge-conflict markers**
  (`<<<<<<<HEAD` / `=======` / `>>>>>>> b82d8ec...`) despite a prior commit
  titled "Resolve README merge conflict" — the merge was evidently redone or
  reverted without re-resolving. Low risk, high annoyance; worth a one-line
  fix (see roadmap Phase 1).
