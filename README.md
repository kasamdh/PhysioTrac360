# PhysioTrac360

PhysioTrac360 is the clinical EMR product of Source Motion Physical Therapy.

This is a standalone Django clinical-workspace project located at
`C:\Users\kasam\Projects\PhysioTrac360`. It does not replace or alter the
separate public website project. Django owns the data, authorization, sessions,
and APIs; the modern workspace UI is a React application under `frontend/`.

It is a HIPAA-oriented application foundation, not a claim of HIPAA compliance
or a substitute for a security/legal review. Production compliance depends on
the complete system: contracts, hosting, people, policies, technical controls,
and operational evidence.

## Included workflows

- Tenant-scoped roles and chart access with organization, clinician, scheduling,
  billing, and compliance roles, plus administrator-facing account provisioning,
  role updates, deactivation, password reset, MFA policy flags, and audit events
- Patient charts, scheduling, intake/consent data models, secure in-app
  messaging, superbill data model, and a searchable chart timeline
- Structured SOAP-style notes, plan-of-care/reassessment fields, therapist
  signature gating, immutable signed notes, and addendum support
- Explainable finalization checks for objective findings, assessment, plan,
  plan-of-care details, overdue reassessments, and signatures
- Functional-limitation-first SMART-goal suggestions. Suggestions become active
  only after a therapist provides baseline/target/unit/timeframe and approves
  the goal.
- LEFS, ODI, NDI, QuickDASH, Timed Up and Go, Berg, and PSFS score capture and
  deterministic trend summaries
- Source-backed progress, discharge, handoff, and patient-summary drafts using
  prior signed visits only. Drafts are never automatically signed, sent, or
  made final.
- Transcript-review workflow for mobile/home visits. The demo stores a reviewed
  transcript, not raw audio.
- Home-program drafts with precaution review and therapist activation
- Append-only application audit events that intentionally store metadata rather
  than duplicating clinical narratives

## Local setup

Use Python 3.11 or newer supported by the pinned Django version.

~~~powershell
cd C:\Users\kasam\Projects\PhysioTrac360
& 'C:\Users\kasam\AppData\Local\Programs\Python\Python311\python.exe' -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py bootstrap_demo --password "admin"
.\.venv\Scripts\python.exe manage.py seed_demo_clients --staff-password "admin"
.\.venv\Scripts\python.exe manage.py runserver
~~~

`seed_demo_clients` provisions 5 demo clients (client numbers 1000-1004) with a
primary administrator and, for two of them, additional staff and a demo patient, so
Super Admin -> Client Management has realistic data to exercise. It is idempotent and
safe to re-run.

Then visit http://127.0.0.1:8000/login/ and sign in as `clinic_admin` with
password `admin`. This platform super-admin account can manage every client
and provision client users from Client Management. The bootstrap command and
this weak credential are for local development only; do not use them or a
local SQLite database with real PHI.

## React frontend

The React workspace uses Django's session cookie and CSRF protections. It does
not store access tokens in local storage or accept a client-provided tenant ID.

For React development, start Django in one terminal and Vite in another:

~~~powershell
cd C:\Users\kasam\Projects\PhysioTrac360
.\.venv\Scripts\python.exe manage.py runserver
~~~

~~~powershell
cd C:\Users\kasam\Projects\PhysioTrac360\frontend
npm.cmd install
npm.cmd run dev
~~~

Open http://127.0.0.1:5173/. Vite proxies `/api` and `/media` to Django, so the
browser remains on one development origin and no permissive CORS policy is
needed.

To serve the built React app from Django on the same origin, build it first:

~~~powershell
cd C:\Users\kasam\Projects\PhysioTrac360\frontend
npm.cmd run build
~~~

Then open http://127.0.0.1:8000/app/. The production build uses
`/static/react/` assets; run the frontend build before Django `collectstatic` in
deployment.

The React workspace covers secure sign-in, role-scoped dashboard, draggable
schedule, and a role-aware patient workspace. The patient workspace brings
together clinical documentation drafts, compliance findings, measurable goals,
outcomes, transcript review, HEP drafts, patient-summary drafts, timeline
search, intake/consent, appointment creation, secure in-app messages,
superbills/payment references, and authorized patient audit history. Django
HTML note-edit/addendum routes remain available while the full React note editor
is migrated.

### React API surface

React calls the versioned, explicit allow-list API at `/api/v1/`:

- `auth/csrf/`, `auth/login/`, `auth/logout/`, and `auth/me/`
- `dashboard/`, `patients/`, `patients/<id>/`, `patients/<id>/workspace/`,
  `patients/<id>/timeline/`, and `schedule/`
- patient-scoped workflow actions for drafts/review, goal suggestions/goals,
  outcome totals, reviewed transcripts, HEP drafts/approval, intake, consent,
  secure messages, appointments, superbills, and payment references
- `appointments/<id>/move/` and `audit-events/`

The backend keeps all tenant, role, appointment-lifecycle, overlap, audit, and
documentation checks authoritative. The frontend only presents permitted
actions; it never grants access itself.

The current demo is intentionally conservative: AI drafts are clinician
triggered and source-backed (not background-autogenerated), outcome totals are
entered/reviewed rather than question-level instrument scoring, and voice work
is reviewed transcript capture only. It does not upload raw audio, auto-send a
patient summary, integrate with a payment processor, or claim HIPAA compliance.

Environment variables are read from the process environment (or a deployment
secret manager). .env.example is a values checklist; this project does not
automatically load an .env file.

## Validate

~~~powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test
~~~

## Production controls still required

Before handling PHI, complete at least the following with qualified security,
privacy, legal, and clinical leadership:

1. Use HIPAA-eligible hosting, managed PostgreSQL, encrypted object storage,
   backups, and a business associate agreement for every service that handles
   PHI, including AI, transcription, email, monitoring, and support tools.
2. Enforce database row-level security and tenant policies in PostgreSQL. The
   Django query scoping here is a defense layer, not a replacement for RLS.
3. Enable TLS, KMS-managed encryption at rest, encrypted backups, key rotation,
   malware scanning for uploads, secret management, and tested disaster
   recovery/restoration.
4. Connect MFA/SSO, automatic session expiry, device/access review,
   least-privilege role assignment, break-glass controls, and audit-log
   retention/immutability appropriate to the organization.
5. Keep PHI out of logs, error trackers, analytics, browser storage,
   notifications, and email/SMS body text. Validate every third-party SDK and
   worker queue.
6. Establish record-retention, amendment, consent, transcription, AI-use,
   patient-notification, incident-response, workforce-training, and risk
   analysis policies.
7. Validate payer, jurisdiction, supervision/co-signature, and outcome
   instrument licensing/scoring requirements before relying on this workflow.

8. Serve the React build and Django API from the same HTTPS origin in
   production. If separate origins are unavoidable, configure a narrow,
   reviewed CORS and `CSRF_TRUSTED_ORIGINS` allow-list rather than a wildcard.

The local clinical-draft composer is deliberately deterministic and stays
inside Django. Do not enable an external LLM or transcription API until
minimum-necessary data flow, data retention, provider controls, and contractual
requirements have been approved.
