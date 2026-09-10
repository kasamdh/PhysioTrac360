export interface Capabilities {
  isSuperAdmin: boolean;
  isPatient: boolean;
  canAccessClinical: boolean;
  canManageSchedule: boolean;
  canSignNotes: boolean;
  canCosignNotes: boolean;
  canManageAccess: boolean;
  canManageOperations: boolean;
  canManageBilling: boolean;
  canReviewAudit: boolean;
}

export interface PatientDocumentSummary {
  id: string;
  title: string;
  description: string;
  originalFilename: string;
  sizeBytes: number;
  uploadedBy: string;
  uploadedAt: string;
  visibleToPatient: boolean;
  uploadedByPatient: boolean;
}

export interface ClinicLocation {
  id: string;
  name: string;
  addressLine1: string;
  addressLine2: string;
  city: string;
  state: string;
  zipCode: string;
  phone: string;
  timezone: string;
  isActive: boolean;
}

export interface AppointmentType {
  id: string;
  name: string;
  defaultDurationMinutes: number;
  color: string;
  isActive: boolean;
}

export interface Payer {
  id: string;
  name: string;
  payerId: string;
  electronicPayerId: string;
  addressLine1: string;
  addressLine2: string;
  city: string;
  state: string;
  zipCode: string;
  phone: string;
  isActive: boolean;
  timelyFilingDays: number;
  authorizationRequired: boolean;
  authorizationNotes: string;
  notes: string;
  createdAt: string;
}

export interface PatientInsurancePolicy {
  id: string;
  payerId: string;
  payerName: string;
  rank: "primary" | "secondary" | "tertiary";
  rankLabel: string;
  planName: string;
  memberId: string;
  groupNumber: string;
  subscriberName: string;
  subscriberDateOfBirth: string | null;
  relationshipToSubscriber: "self" | "spouse" | "child" | "other";
  relationshipToSubscriberLabel: string;
  effectiveDate: string;
  terminationDate: string | null;
  isActive: boolean;
  copay: string | null;
  coinsurancePercent: string | null;
  deductible: string | null;
  authorizationRequired: boolean;
  hasCardFront: boolean;
  hasCardBack: boolean;
  createdAt: string;
}

export interface DiagnosisCode {
  code: string;
  description: string;
  isBillable: boolean;
}

export interface Charge {
  id: string;
  serviceDate: string;
  patientId: string;
  episodeOfCareId: string | null;
  noteId: string | null;
  providerId: string;
  providerName: string;
  locationId: string | null;
  locationName: string | null;
  cptCode: string;
  modifiers: string[];
  units: number;
  minutes: number | null;
  recommendedUnits: number | null;
  unitsDifference: number | null;
  unitsOverrideReason: string;
  diagnosisCodes: DiagnosisCode[];
  chargeAmount: string;
  status: "draft" | "ready" | "billed" | "void";
  statusLabel: string;
  claimId: string | null;
  createdAt: string;
}

export type ClaimStatus =
  | "draft" | "ready" | "validation_error" | "submitted" | "accepted" | "rejected" | "processing"
  | "denied" | "partial_payment" | "paid" | "appealed" | "corrected" | "closed";

export interface Claim {
  id: string;
  patientId: string;
  patientInsuranceId: string;
  payerId: string;
  payerName: string;
  diagnosisCodeList: string[];
  status: ClaimStatus;
  statusLabel: string;
  clearinghouseClaimId: string;
  submittedAt: string | null;
  closedAt: string | null;
  totalChargeAmount: string;
  totalPaid: string;
  totalAdjusted: string;
  balance: string;
  chargeIds: string[];
  createdAt: string;
}

export interface ClaimValidationFinding {
  code: string;
  field: string;
  severity: "error" | "warning";
  message: string;
}

export interface Cms1500Data {
  claimId: string;
  status: string;
  patient: { fullName: string; dateOfBirth: string; address: string; phone: string };
  subscriber: { name: string; dateOfBirth: string; relationshipToPatient: string; memberId: string; groupNumber: string };
  payer: { name: string; payerId: string; electronicPayerId: string; address: Record<string, string> };
  billingProvider: { name: string; npi: string; taxId: string; address: Record<string, string>; phone: string };
  diagnoses: { pointer: string; code: string }[];
  serviceLines: {
    lineNumber: number; serviceDate: string; placeOfService: string; cptCode: string; modifiers: string[];
    diagnosisPointers: string[]; units: number; chargeAmount: string; renderingProviderNpi: string; renderingProviderName: string;
  }[];
  totalChargeAmount: string;
}

export type ClaimTransactionKind = "insurance_payment" | "patient_payment" | "adjustment" | "write_off" | "refund" | "transfer";

export interface ClaimTransaction {
  id: string;
  patientId: string;
  claimId: string | null;
  transferredToClaimId: string | null;
  kind: ClaimTransactionKind;
  kindLabel: string;
  method: string;
  methodLabel: string;
  amount: string;
  paymentDate: string;
  reference: string;
  denialCode: string;
  denialReason: string;
  notes: string;
  isMatched: boolean;
  recordedBy: string | null;
  createdAt: string;
}

export interface ArAgingRow {
  claimId: string;
  patientId: string;
  patientName: string;
  payerName: string;
  status: ClaimStatus;
  statusLabel: string;
  balance: string;
  ageDays: number;
  bucket: string;
}

export interface ArAgingReport {
  buckets: Record<string, string>;
  totalOutstanding: string;
  claims: ArAgingRow[];
}

export type DenialAppealStatus = "not_appealed" | "preparing" | "submitted" | "won" | "lost";
export type DenialResolution = "open" | "resolved_paid" | "resolved_written_off" | "resolved_patient_billed";

export interface ClaimDenial {
  id: string;
  patientId: string;
  claimId: string;
  payerName: string;
  denialCode: string;
  denialReason: string;
  deniedOn: string;
  ownerId: string | null;
  ownerName: string | null;
  dueDate: string | null;
  isOverdue: boolean;
  actionNotes: string;
  appealStatus: DenialAppealStatus;
  appealStatusLabel: string;
  resolution: DenialResolution;
  resolutionLabel: string;
  resolvedAt: string | null;
  createdAt: string;
}

export interface PatientStatement {
  id: string;
  patientId: string;
  statementDate: string;
  dueDate: string;
  balanceAtGeneration: string;
  generatedBy: string | null;
  createdAt: string;
}

export interface PatientStatementData {
  statementId: string;
  statementDate: string;
  dueDate: string;
  patient: { fullName: string; address: string };
  practice: { name: string; npi: string; taxId: string; address: Record<string, string>; phone: string };
  insuranceClaims: { claimId: string; payerName: string; statusLabel: string; chargeTotal: string; paid: string; adjusted: string; balance: string }[];
  cashCharges: { superbillId: string; serviceDate: string; amount: string; paid: string; balance: string }[];
  totalBalance: string;
  paymentInstructions: string;
}

export interface ServicePrice {
  id: string;
  cptCode: string;
  label: string;
  price: string;
  isActive: boolean;
  createdAt: string;
}

export interface CashPackage {
  id: string;
  patientId: string;
  kind: "package" | "membership";
  kindLabel: string;
  name: string;
  visitsIncluded: number | null;
  visitsUsed: number;
  visitsRemaining: number | null;
  price: string;
  discountPercent: string | null;
  purchasedOn: string;
  expiresAt: string | null;
  status: "active" | "expired" | "cancelled";
  statusLabel: string;
  isActive: boolean;
  createdAt: string;
}

export interface PatientSuperbillData {
  superbillId: string;
  status: string;
  serviceDate: string;
  patient: { fullName: string; dateOfBirth: string };
  provider: { name: string };
  diagnosisCodes: string[];
  diagnosisText: string;
  lines: { serviceDate: string; cptCode: string; modifiers: string[]; units: number | null; chargeAmount: string | null; diagnosisCodes: string[]; providerName: string }[];
  totalAmount: string;
  practice: { name: string; npi: string; taxId: string; address: Record<string, string>; phone: string };
}

export interface BillingRevenueRow {
  id: string;
  name: string;
  amount: string;
}

export interface BillingSummaryReport {
  windowStart: string;
  windowEnd: string;
  charges: { count: number; totalAmount: string };
  collections: { totalAmount: string };
  payments: { insurancePayments: string; patientPayments: string; adjustments: string; writeOffs: string; refunds: string };
  claimsByStatus: Record<string, number>;
  cleanClaimRate: string | null;
  claimsSubmittedInWindow: number;
  revenueByProvider: BillingRevenueRow[];
  revenueByLocation: BillingRevenueRow[];
  revenueByPayer: BillingRevenueRow[];
  patientBalances: { patientId: string; patientName: string; balance: string }[];
}

export interface OperationalReport {
  windowDays: number;
  newPatients: number;
  appointmentsByStatus: Record<string, number>;
  notes: { signed: number; unsigned: number };
  outcomesRecorded: number;
  reassessmentsOverdue: number;
  caseloadByProvider: Array<{ id: string; displayName: string; activePatientCount: number }>;
}

export interface ManagedClient {
  id: string;
  clientNumber: number;
  clientName: string;
  slug: string;
  portalUrl: string;
  email: string;
  phone: string;
  city: string;
  state: string;
  addressLine1: string;
  addressLine2: string;
  zipCode: string;
  country: string;
  subscriptionTier: string;
  subscriptionTierLabel: string;
  timezone: string;
  status: string;
  statusLabel: string;
  comments: string;
  userCount: number;
  primaryAdmin: { id: string; name: string; email: string } | null;
  createdAt: string;
  updatedAt: string;
  suspendedAt: string | null;
  archivedAt: string | null;
}

export interface PrivilegedAccessGrant {
  id: string;
  actor: string;
  reason: string;
  requestedAt: string;
  expiresAt: string;
  revokedAt: string | null;
  revokedBy: string | null;
  isActive: boolean;
}

export interface PrivilegedPatientDetail {
  patient: Patient & { diagnoses: string; precautions: string };
  notes: NoteSummary[];
  appointments: Appointment[];
  goals: Goal[];
  outcomes: OutcomeTrend[];
  grant: PrivilegedAccessGrant;
}

export type UserAccountStatus = "active" | "inactive" | "locked_out" | "suspended" | "deleted";

export type LicenseAlertStatus = "none" | "valid" | "expiring_soon" | "critical" | "expired";
export type LicenseVerificationStatus = "pending_verification" | "verified";

export interface UserLicenseInfo {
  id: string;
  licenseNumber: string;
  issuingState: string;
  licenseType: string;
  issueDate: string | null;
  expiresAt: string;
  verificationStatus: LicenseVerificationStatus;
  verifiedAt: string | null;
  verifiedByName: string | null;
  verificationNotes: string;
  hasDocument: boolean;
  documentFilename: string;
  alertTier: string;
  colorBucket: Exclude<LicenseAlertStatus, "none">;
  daysRemaining: number;
}

export interface ManagedClientUser {
  id: string;
  name: string;
  firstName: string;
  lastName: string;
  email: string;
  username: string;
  role: string;
  roleLabel: string;
  active: boolean;
  credential: string;
  licenses: UserLicenseInfo[];
  licenseAlertStatus: LicenseAlertStatus;
  licenseDaysRemaining: number | null;
  mustUseMfa: boolean;
  archivedAt: string | null;
  clientNumber: number | null;
  clientName: string | null;
  status: UserAccountStatus;
  statusLabel: string;
  lastLogin: string | null;
  failedLoginAttempts: number;
  lastFailedLoginAt: string | null;
  lockedAt: string | null;
  lockedUntil: string | null;
  suspendedAt: string | null;
  suspendedBy: string | null;
  suspensionReason: string;
  archivedBy: string | null;
  statusChangedAt: string | null;
  statusChangedBy: string | null;
  activeSessions: UserSessionInfo[];
}

export interface UserSessionInfo {
  id: string;
  deviceName: string;
  browserName: string;
  ipAddress: string | null;
  createdAt: string;
  lastActivityAt: string;
  isCurrent: boolean;
}

export interface WorkspaceUser {
  id: string;
  username: string;
  displayName: string;
  role: string;
  roleLabel: string;
  lastLogin: string | null;
  mustChangePassword: boolean;
  organization: {
    id: string;
    name: string;
    logoUrl: string | null;
    timezone: string;
  } | null;
  capabilities: Capabilities;
}

export interface Appointment {
  id: string;
  date: string;
  startsAt: string;
  endsAt: string;
  status: string;
  statusLabel: string;
  kind: string;
  kindLabel: string;
  location: string;
  isHomeVisit: boolean;
  episodeOfCareId: string | null;
  authorizationId: string | null;
  patient: { id: string; fullName: string };
  therapist: { id: string; displayName: string };
}

export interface Patient {
  id: string;
  fullName: string;
  firstName: string;
  lastName: string;
  medicalRecordNumber: string;
  dateOfBirth: string;
  status: string;
  statusLabel: string;
  assignedTherapist: { id: string; displayName: string } | null;
  // Only present when the endpoint opts in with include_contact=True
  // (create/update/edit-form responses) — never on the list/workspace views.
  phone?: string;
  email?: string;
  address?: string;
  emergencyContact?: string;
  // Only present on the workspace endpoint (include_portal_status=True).
  portalStatus?: "none" | "invited" | "active";
}

export interface PatientDetail {
  patient: Patient & { diagnoses: string; precautions: string };
  notes: Array<{
    id: string;
    patientId: string;
    patientName: string;
    noteType: string;
    noteTypeLabel: string;
    status: string;
    statusLabel: string;
    serviceDate: string;
    reassessmentDue: string | null;
  }>;
  goals: Array<{
    id: string;
    functionalTask: string;
    baselineValue: number;
    targetValue: number;
    currentValue: number | null;
    unit: string;
    targetDate: string;
    status: string;
    statusLabel: string;
    progressPercent: number | null;
  }>;
  outcomes: Array<{
    measure: string;
    label: string;
    latest: number;
    maximum: number | null;
    unit: string;
    trend: string;
    delta: number;
    points: Array<{ measuredOn: string; score: number; maximumScore: number | null }>;
  }>;
  appointments: Appointment[];
  complianceFindings: Array<{
    code: string;
    severity: string;
    title: string;
    detail: string;
    finalizationBlocker: boolean;
  }>;
}

export interface DashboardData {
  today: string;
  metrics: {
    appointments: number;
    pendingNotes: number;
    dueReassessments: number;
    unreadMessages: number;
  };
  appointments: Appointment[];
  alerts: Array<{
    patientId: string;
    patientName: string;
    code: string;
    severity: string;
    title: string;
    detail: string;
  }>;
  pendingNotes: PatientDetail["notes"];
  drafts: Array<{
    id: string;
    kind: string;
    kindLabel: string;
    patientId: string;
    patientName: string;
    createdAt: string;
  }>;
}

export interface ScheduleData {
  month: string;
  visibleStart: string;
  visibleEnd: string;
  events: Appointment[];
}

export interface ComplianceFinding {
  code: string;
  severity: string;
  title: string;
  detail: string;
  finalizationBlocker: boolean;
}

export interface NoteSummary {
  id: string;
  patientId: string;
  patientName: string;
  noteType: string;
  noteTypeLabel: string;
  status: string;
  statusLabel: string;
  serviceDate: string;
  reassessmentDue: string | null;
  updatedAt: string;
  therapistId: string;
  therapistName: string;
  appointmentId: string | null;
  episodeOfCareId: string | null;
  cosignRequired: boolean;
  complianceFindings?: ComplianceFinding[];
}

export interface NoteIntervention {
  id: string;
  description: string;
  bodyRegion: string;
  minutes: number;
  units: number | null;
  isTimed: boolean;
  patientResponse: string;
  order: number;
  category: string;
  categoryLabel: string;
}

export interface NoteAddendumInfo {
  id: string;
  author: string;
  reason: string;
  body: string;
  createdAt: string;
}

export interface NoteDetail extends NoteSummary {
  diagnosisSnapshot: string;
  precautionsSnapshot: string;
  subjective: string;
  objective: string;
  interventions: string;
  assessment: string;
  plan: string;
  subjectiveDetails: Record<string, unknown>;
  objectiveMeasurements: Record<string, unknown>;
  dischargeDetails: Record<string, unknown>;
  planOfCareStart: string | null;
  planOfCareEnd: string | null;
  frequencyPerWeek: number | null;
  durationWeeks: number | null;
  signatureName: string;
  signedAt: string | null;
  finalizationAttestation: boolean;
  cosignedBy: string | null;
  cosignedAt: string | null;
  interventionItems: NoteIntervention[];
  addenda: NoteAddendumInfo[];
  complianceFindings: ComplianceFinding[];
}

export interface DocumentationListFilters {
  status?: string;
  noteType?: string;
  providerId?: string;
  quick?: string;
  q?: string;
  pageSize?: string;
  page?: string;
}

export interface Goal {
  id: string;
  functionalTask: string;
  baselineValue: number;
  targetValue: number;
  currentValue: number | null;
  unit: string;
  targetDate: string;
  status: string;
  statusLabel: string;
  progressPercent: number | null;
  functionalLimitation?: string;
  measurementMethod?: string;
  suggestedWording?: string;
  approvedBy?: string | null;
  approvedAt?: string | null;
}

export interface OutcomeTrend {
  measure: string;
  label: string;
  latest: number;
  maximum: number | null;
  unit: string;
  trend: string;
  delta: number;
  points: Array<{ measuredOn: string; score: number; maximumScore: number | null }>;
}

export interface ArtifactSection {
  key: string;
  label: string;
  draftText: string;
  status: "pending" | "accepted" | "edited" | "rejected";
  reviewedText: string;
}

export interface Artifact {
  id: string;
  kind: string;
  kindLabel: string;
  status: string;
  statusLabel: string;
  sourceNoteCount: number;
  provider: string;
  modelVersion: string;
  safetyNotice: string;
  requestedBy: string;
  createdAt: string;
  reviewedBy: string | null;
  reviewedAt: string | null;
  reviewNote: string;
  appliedNoteId: string | null;
  draftText?: string;
  sections: ArtifactSection[];
}

export interface CptCodeSuggestion {
  code: string;
  label: string;
  category: string;
  minutes: number;
  suggestedUnits: number;
}

export interface CodingSuggestions {
  cptSuggestions: CptCodeSuggestion[];
  totalTimedMinutes: number;
  totalSuggestedUnits: number;
  documentationGaps: string[];
  disclaimer: string;
}

export interface HomeExercise {
  id: string;
  name: string;
  instructions: string;
  dosage: string;
  precautionNote: string;
  videoUrl: string;
  sortOrder: number;
}

export interface HomeProgram {
  id: string;
  title: string;
  diagnosisContext: string;
  precautions: string;
  patientInstructions: string;
  status: string;
  statusLabel: string;
  prescribedBy: string;
  approvedAt: string | null;
  createdAt: string;
  exercises: HomeExercise[];
}

export interface VoiceCapture {
  id: string;
  status: string;
  statusLabel: string;
  consentConfirmed: boolean;
  durationSeconds: number;
  therapist: string;
  createdAt: string;
  linkedNoteId: string | null;
  transcript?: string;
}

export interface TimelineEvent {
  id: string;
  occurredAt: string;
  kind: string;
  label: string;
  detail: string;
}

export interface Referral {
  id: string;
  direction: string;
  directionLabel: string;
  providerName: string;
  providerContact: string;
  reason: string;
  status: string;
  statusLabel: string;
  createdBy: string;
  createdAt: string;
}

export interface EpisodeOfCare {
  id: string;
  diagnosis: string;
  status: string;
  statusLabel: string;
  startDate: string;
  endDate: string | null;
  notes: string;
  primaryTherapistName: string | null;
  referralId: string | null;
  createdBy: string | null;
  createdAt: string;
}

export interface PatientAuthorization {
  id: string;
  insuranceName: string;
  authorizationNumber: string;
  visitsApproved: number;
  visitsUsed: number;
  visitsRemaining: number;
  startDate: string;
  expiresAt: string;
  daysRemaining: number;
  status: string;
  statusLabel: string;
  dateAlertTier: string;
  visitAlertTier: string;
  colorBucket: Exclude<LicenseAlertStatus, "none">;
  episodeOfCareId: string | null;
  notes: string;
  createdAt: string;
}

export interface ConsentSummary {
  id: string;
  kind: string;
  kindLabel: string;
  documentVersion: string;
  status: string;
  statusLabel: string;
  signedAt: string | null;
  recordedBy: string;
}

export interface IntakeSummary {
  id: string;
  formVersion: string;
  status: string;
  statusLabel: string;
  submittedAt: string | null;
  createdAt: string;
}

export interface FormSubmissionSummary {
  id: string;
  templateName: string;
  category: string;
  status: string;
  statusLabel: string;
  submittedAt: string | null;
  createdAt: string;
}

export interface FormSubmissionDetail extends FormSubmissionSummary {
  schema: PortalFormSection[];
  data: Record<string, unknown>;
  signatureName: string;
  signedAt: string | null;
}

export interface SecureMessage {
  id: string;
  direction: "inbound" | "outbound";
  sender: string;
  recipient: string;
  category: string;
  categoryLabel: string;
  subject: string;
  body: string;
  createdAt: string;
  readAt: string | null;
}

export interface StaffOption {
  id: string;
  displayName: string;
  roleLabel: string;
}

export interface Superbill {
  id: string;
  serviceDate: string;
  codes: string[];
  amount: number;
  status: string;
  statusLabel: string;
  clinician: string;
  createdAt: string;
}

export interface Payment {
  id: string;
  superbillId: string | null;
  amount: number;
  receivedOn: string;
  status: string;
  statusLabel: string;
  recordedBy: string;
}

export interface AuditEvent {
  id: string;
  action: string;
  objectType: string;
  objectId: string | null;
  patientId: string | null;
  actor: string;
  createdAt: string;
  metadata: Record<string, unknown>;
}

export interface GlobalAuditEvent extends AuditEvent {
  clientNumber: number | null;
  clientName: string | null;
}

export interface SuperAdminDashboard {
  organizations: { total: number; active: number; suspended: number; archived: number };
  locationsTotal: number;
  users: { total: number; activePts: number; activePtas: number };
  patientsTotal: number;
  credentialAlerts: { expired: number; critical: number; expiring_soon: number; valid: number };
  subscriptionTiers: Record<string, number>;
  recentOrganizations: Array<{ clientNumber: number; clientName: string; status: string; statusLabel: string; createdAt: string }>;
  recentAuditEvents: GlobalAuditEvent[];
  recentUserActivity: GlobalAuditEvent[];
  failedLoginTrend: Array<{ date: string; count: number }>;
}

export interface CredentialDashboardRow {
  licenseId: string;
  providerId: string;
  providerName: string;
  providerRole: string;
  providerRoleLabel: string;
  clientNumber: number | null;
  clientName: string;
  location: string;
  licenseType: string;
  licenseNumber: string;
  issuingState: string;
  expiresAt: string;
  daysRemaining: number;
  alertTier: string;
  colorBucket: Exclude<LicenseAlertStatus, "none">;
  requiredAction: string;
  accountStatus: string;
}

export interface FeatureFlag {
  code: string;
  name: string;
  description: string;
}

export interface SubscriptionPlanSummary {
  code: string;
  name: string;
  description: string;
  monthlyPrice: string;
  annualPrice: string;
  providerSeatLimit: number;
  featureCodes: string[];
}

export type OrganizationSubscriptionStatus = "trial" | "active" | "past_due" | "suspended" | "cancelled";
export type BillingCycle = "monthly" | "annual";

export interface OrganizationSubscriptionInfo {
  id: string;
  planCode: string;
  planName: string;
  status: OrganizationSubscriptionStatus;
  statusLabel: string;
  billingCycle: BillingCycle;
  billingCycleLabel: string;
  startsAt: string;
  endsAt: string | null;
  providerSeatCount: number;
  featureCodes: string[];
  isActive: boolean;
}

export interface ClientSubscriptionDetail {
  subscription: OrganizationSubscriptionInfo | null;
  plans: SubscriptionPlanSummary[];
  features: FeatureFlag[];
}

export interface GoalSuggestion {
  functional_limitation: string;
  functional_task: string;
  baseline_hint: string;
  target_hint: string;
  measurement_method: string;
  wording: string;
  timeframe_weeks: number;
}

export interface HomeProgramSuggestion {
  warnings: string[];
  exercises: Array<{ name: string; dosage: string; reason: string }>;
}

export interface PatientWorkspace {
  patient: Patient & { diagnoses?: string; precautions?: string };
  permissions: {
    canAccessClinical: boolean;
    canManageOperations: boolean;
    canSignNotes: boolean;
    canManageBilling: boolean;
    canReviewAudit: boolean;
    canManagePortalAccess: boolean;
  };
  clinical?: {
    episodesOfCare: EpisodeOfCare[];
    notes: NoteSummary[];
    goals: Goal[];
    outcomes: OutcomeTrend[];
    outcomeAssignments?: PortalOutcomeAssignment[];
    complianceFindings: ComplianceFinding[];
    artifacts: Artifact[];
    homePrograms: HomeProgram[];
    voiceCaptures: VoiceCapture[];
    timeline: TimelineEvent[];
  };
  operations?: {
    consents: ConsentSummary[];
    intakes: IntakeSummary[];
    formSubmissions?: FormSubmissionSummary[];
    referrals?: Referral[];
    messages: SecureMessage[];
    recipients: StaffOption[];
    canManageSchedule: boolean;
    canManageBilling: boolean;
    canCollectPayments: boolean;
    appointments?: Appointment[];
    schedulingStaff?: StaffOption[];
    superbills?: Superbill[];
    payments?: Payment[];
    authorizations?: PatientAuthorization[];
  };
  safety?: { recentAuditEvents: AuditEvent[] };
}

export interface PublicOrganization {
  name: string;
  slug: string;
  logoUrl: string | null;
  address: { line1: string; line2: string; city: string; state: string; zipCode: string };
  phone: string;
  timezone: string;
}

export interface PublicLocation {
  id: string;
  name: string;
  city: string;
  state: string;
  timezone: string;
}

export interface PublicAppointmentType {
  id: string;
  name: string;
  description: string;
  durationMinutes: number;
  price: number | null;
  requiresNewPatient: boolean;
}

export interface PublicProvider {
  id: string;
  displayName: string;
  credentials: string;
  specialty: string;
  bio: string;
}

export interface PublicSlot {
  start: string;
  end: string;
}

export interface PublicProviderSlots {
  provider: { id: string; displayName: string };
  slots: PublicSlot[];
}

export interface PublicAvailability {
  date: string;
  timezone: string;
  providers: PublicProviderSlots[];
}

export interface PublicBookingPatient {
  firstName: string;
  lastName: string;
  dateOfBirth: string;
  email: string;
  phone: string;
  address?: string;
  emergencyContact?: string;
}

export interface PublicBookingConfirmation {
  confirmationNumber: string;
  appointment: {
    id: string;
    startsAt: string;
    endsAt: string;
    provider: string | null;
    location: string | null;
    appointmentType: string | null;
    organization: string;
  };
}

export interface PortalAppointment {
  id: string;
  date: string;
  startsAt: string;
  endsAt: string;
  status: string;
  statusLabel: string;
  kind: string;
  kindLabel: string;
  providerName: string;
  location: string;
  isHomeVisit: boolean;
  isTelehealth: boolean;
  confirmedAt: string | null;
  canJoinTelehealth: boolean;
  // Only present when the endpoint opts in (upcoming lists) — never on
  // read-only history views, where these actions are never offered.
  canCancel?: boolean;
  canReschedule?: boolean;
  canConfirm?: boolean;
  // Only present when canReschedule is true — the ids needed to re-browse
  // availability for this appointment's own provider/location/type.
  locationId?: string | null;
  appointmentTypeId?: string | null;
  providerId?: string | null;
}

export interface PortalAppointmentType {
  id: string;
  name: string;
  description: string;
  durationMinutes: number;
}

export interface PortalWaitlistEntry {
  id: string;
  location: string | null;
  appointmentType: string | null;
  providerName: string | null;
  earliestDate: string;
  latestDate: string | null;
  notes: string;
  status: string;
  statusLabel: string;
  createdAt: string;
}

export interface PortalWaitlistStaffEntry extends PortalWaitlistEntry {
  patient: { id: string; fullName: string };
}

export interface PortalFormField {
  key: string;
  label: string;
  type: "text" | "textarea" | "number" | "checkbox";
  required: boolean;
}

export interface PortalFormSection {
  key: string;
  label: string;
  fields: PortalFormField[];
}

export interface PortalFormOverview {
  templateSlug: string;
  name: string;
  category: string;
  status: string;
  submissionId: string | null;
  submittedAt: string | null;
}

export interface PortalFormSubmission {
  id: string;
  templateSlug: string;
  templateName: string;
  category: string;
  status: string;
  data: Record<string, unknown>;
  startedAt: string | null;
  submittedAt: string | null;
  schema?: PortalFormSection[];
}

export interface PortalPayerOption {
  id: string;
  name: string;
}

export interface PortalInsurancePolicy {
  id: string;
  payerId: string;
  payerName: string;
  rank: string;
  rankLabel: string;
  planName: string;
  memberId: string;
  groupNumber: string;
  subscriberName: string;
  subscriberDateOfBirth: string | null;
  relationshipToSubscriber: string;
  relationshipToSubscriberLabel: string;
  effectiveDate: string;
  terminationDate: string | null;
  isActive: boolean;
  copay: string | null;
  coinsurancePercent: string | null;
  deductible: string | null;
  authorizationRequired: boolean;
  hasCardFront: boolean;
  hasCardBack: boolean;
  createdAt: string;
}

export interface PortalOutcomeAssignment {
  id: string;
  measure: string;
  measureLabel: string;
  status: string;
  assignedAt: string;
}

export interface PortalOutcomeChoice {
  value: number;
  label: string;
}

export interface PortalOutcomeItem {
  key: string;
  label: string;
  choices: PortalOutcomeChoice[];
}

export interface PortalOutcomeSection {
  key: string;
  label: string;
  choices: string[];
}

export interface PortalOutcomeSchema {
  kind: "items" | "sections" | "activities" | "unsupported";
  instructions: string;
  items?: PortalOutcomeItem[];
  sections?: PortalOutcomeSection[];
}

export interface PortalOutcomeSubmitResult {
  assignment: PortalOutcomeAssignment;
  score: string;
  maximumScore: string;
}

export interface PortalMessage {
  id: string;
  direction: "inbound" | "outbound";
  category: string;
  categoryLabel: string;
  subject: string;
  body: string;
  counterpartName: string;
  createdAt: string;
  readAt: string | null;
}

export interface PortalNotification {
  id: string;
  type: string;
  categoryLabel: string;
  receivedAt: string;
}

export interface PortalStatementSummary {
  id: string;
  statementDate: string;
  dueDate: string;
  balanceAtGeneration: string;
}

export interface PortalReceipt {
  id: string;
  amount: string;
  receivedOn: string;
  status: string;
  statusLabel: string;
  superbillId: string | null;
}

export interface PortalPaymentAttempt {
  id: string;
  amount: string;
  status: string;
  statusLabel: string;
  attemptedAt: string;
  message: string;
}

export interface PortalPayments {
  insuranceBalance: string;
  cashBalance: string;
  totalBalance: string;
  statements: PortalStatementSummary[];
  receipts: PortalReceipt[];
  onlinePaymentAttempts: PortalPaymentAttempt[];
}

export interface PortalPaymentChargeResult {
  payment: PortalPaymentAttempt;
  succeeded: boolean;
  message: string;
}

export interface PortalSuperbillSummary {
  id: string;
  serviceDate: string;
  amount: string;
  status: string;
  statusLabel: string;
}

export interface TelehealthJoinResult {
  joinable: boolean;
  joinUrl: string | null;
  message: string;
}

export interface PortalProfileChangeRequest {
  id: string;
  changes: Record<string, string>;
  status: string;
  statusLabel: string;
  createdAt: string;
  reviewedAt: string | null;
  reviewerNote: string;
}

export interface ProfileChangeRequestStaff extends PortalProfileChangeRequest {
  patient: { id: string; fullName: string };
}

export interface PortalProfile {
  fullName: string;
  dateOfBirth: string;
  phone: string;
  email: string;
  address: string;
  emergencyContact: string;
  pharmacyName: string;
  pharmacyPhone: string;
  pharmacyAddress: string;
  preferredContactMethod: string;
  emailNotificationsEnabled: boolean;
  pendingChangeRequest: PortalProfileChangeRequest | null;
}

export interface PortalDocument {
  id: string;
  title: string;
  description: string;
  originalFilename: string;
  sizeBytes: number;
  uploadedAt: string;
  uploadedByPatient: boolean;
}

export interface PortalHepExercise {
  id: string;
  name: string;
  instructions: string;
  dosage: string;
  precautionNote: string;
  videoUrl: string;
  sortOrder: number;
  lastCompletedAt: string | null;
}

export interface PortalHepProgram {
  id: string;
  title: string;
  patientInstructions: string;
  precautions: string;
  exercises: PortalHepExercise[];
  completionsLast7Days: number;
}

export interface PortalHepLog {
  id: string;
  exerciseId: string;
  exerciseName: string;
  completedAt: string;
  painLevel: number | null;
  difficultyLevel: number | null;
  comment: string;
}

export interface PortalDashboard {
  patient: { fullName: string; firstName: string };
  nextAppointment: PortalAppointment | null;
  upcomingAppointments: PortalAppointment[];
  formsDue: PortalFormOverview[];
  outstandingBalance: string;
  newMessageCount: number;
  homeExerciseProgram: { id: string; title: string; exerciseCount: number } | null;
  outcomeMeasuresDue: PortalOutcomeAssignment[];
  recentDocuments: PortalDocument[];
  notifications: PortalNotification[];
}

export interface PortalInviteResult {
  email: string;
  reissued: boolean;
  invitationUrl: string;
}

export interface PortalAppointmentsList {
  upcoming: PortalAppointment[];
  past: PortalAppointment[];
}
