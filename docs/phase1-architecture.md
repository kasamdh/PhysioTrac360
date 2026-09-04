# Phase 1 Architecture and Implementation Plan

## 1. System architecture

This project already follows a pragmatic multi-tenant PT EMR foundation:

- Django serves the clinical backend, authentication, tenant validation, forms, and audit trail.
- React + Vite provides the modern patient-workspace frontend served from a single local origin.
- SQLite is used for local development and demos; PostgreSQL is the target production database with the same data model assumptions.
- Tenant isolation is enforced in the service layer and API layer rather than trusting browser state.

## 2. SaaS architecture

### Tenant model

Every organization owns:

- staff and providers
- patients and encounters
- documents, notes, goals, outcomes, bills, and payments
- user assignments and audit events
- subscription metadata and access rights

### Core boundaries

- Organization-level security boundary: all patient and clinical queries must include organization membership.
- Role-level boundary: users have least-privilege roles with explicit permissions.
- Clinical boundary: signed clinical notes are append-only and protected from silent edits.
- AI boundary: AI drafts remain draft-only and source-backed; they are never auto-signed.

## 3. Multi-tenant design

The project uses an Organization model as the tenant boundary and user.organization as the tenant owner. All patient-scoped queries should route through functions such as `patients_for(...)` and `organization_required(...)` before data is returned.

This protects the system from browser-supplied organization_id values and enforces tenant access on the backend.

## 4. Subscription architecture

The repository already has a strong foundation for organization-scoped roles and a clinic-first SaaS model. The next step in a production SaaS plan would be to add explicit subscription tables for:

- plans
- feature entitlements
- trial/active/past_due/suspended/cancelled states
- invoiceable seats
- billing provider integration

The model should remain separate from patient billing and payment collection.

## 5. User-role permission matrix

| Role | Clinical access | Scheduling | Billing | Admin | Patient portal |
| --- | --- | --- | --- | --- | --- |
| ADMIN | Yes | Yes | Yes | Yes | No |
| DIRECTOR | Yes | Yes | Yes | Limited | No |
| THERAPIST | Yes | Yes | No | No | No |
| ASSISTANT | Yes | Yes | No | No | No |
| SCHEDULER | No | Yes | No | No | No |
| BILLER | No | No | Yes | No | No |
| COMPLIANCE | Yes | No | No | No | No |
| PATIENT | No | No | No | No | Yes |

## 6. Authentication flow

1. User submits credentials to Django auth session endpoint.
2. Server validates username/password.
3. Server binds the authenticated user to their organization.
4. Session cookie is used for subsequent API requests.
5. Every API request validates session and tenant membership.

## 7. Security architecture

- Django sessions and CSRF protections are already in place.
- Organization validation is enforced in API/service logic.
- The project does not place PHI in public URLs or frontend storage.
- Audit events are generated for key actions.
- Production hardening should add PostgreSQL RLS, encryption at rest, secrets management, MFA, SSO, device review, and a BAA for PHI processors.

## 8. Audit architecture

The project has an append-only audit-event pattern and should continue to use it for:

- login events
- patient access attempts
- note creation, edits, and sign events
- AI requests and drafts
- permission changes
- payment and billing activity

## 9. AWS architecture

Recommended production footprint:

- Route 53 for DNS
- CloudFront for static assets
- ALB in front of Django app
- ECS Fargate for app containers
- RDS PostgreSQL
- ElastiCache Redis
- S3 for document storage
- KMS for encryption
- Secrets Manager for env vars
- SES for email
- CloudWatch + CloudTrail + GuardDuty + Security Hub

## 10. Monorepo layout

```text
PhysioTrac360/
├── care/
│   ├── api/
│   ├── management/
│   ├── migrations/
│   ├── __init__.py
│   ├── access.py
│   ├── admin.py
│   ├── forms.py
│   ├── models.py
│   ├── services.py
│   ├── tests.py
│   ├── urls.py
│   └── views.py
├── config/
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
├── frontend/
│   ├── src/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   └── index.html
├── docs/
├── media/
├── static/
├── templates/
├── .venv/
├── db.sqlite3
├── manage.py
├── README.md
├── requirements.txt
└── .env.example
```

## 11. Backend project structure

The backend is already structured around a clinical domain package and can be extended with module folders such as:

- `auth`
- `organizations`
- `subscriptions`
- `users`
- `providers`
- `patients`
- `scheduling`
- `encounters`
- `documentation`
- `forms`
- `goals`
- `outcomes`
- `billing`
- `claims`
- `payments`
- `referrals`
- `messages`
- `notifications`
- `reports`
- `audit`
- `ai`

## 12. Frontend structure

The existing frontend already contains a good UI shell:

- `src/App.tsx` runtime route and auth handling
- `src/features/` page-level screens
- `src/components/` reusable layout and shell
- `src/api/` client and types
- `src/styles.css` visual system

## 13. Database migrations

The project already contains migrations and uses Django migrations as the schema change mechanism. Production migrations should continue to be explicit and reviewable.

## 14. Docker Compose

A production-ready local compose file should include:

- Django app
- Redis
- PostgreSQL
- optional pgAdmin
- optional frontend proxy or separate container

## 15. Initial login page

The app already has a modern login shell in React, styled to match the brand palette. This is a strong Phase 1 user-facing baseline.

## 16. Implementation checklist

- [x] Multi-tenant organization model
- [x] User roles and organization links
- [x] Patient chart and access guardrails
- [x] Clinical note lifecycle and signatures
- [x] Audit event recording
- [x] Role-scoped frontend shell
- [x] Modern login page
- [ ] Subscription/plan model
- [ ] Tenant feature entitlements
- [ ] Provider and location detail models
- [ ] Scheduling enhancement and booking flows
- [ ] Billing and claim lifecycle
- [ ] AI documentation and safety guardrails
- [ ] End-to-end authorization tests

## 17. Phase 1 completion gate

This project is already aligned with a large share of Phase 1 and can be considered a working clinical foundation. The remaining work is to extend the subscription, provider, and scheduling domains while keeping the existing tenant-safe design intact.
