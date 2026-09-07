export interface Capabilities {
  isSuperAdmin: boolean;
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
}

export interface HomeExercise {
  id: string;
  name: string;
  instructions: string;
  dosage: string;
  precautionNote: string;
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

export interface SecureMessage {
  id: string;
  direction: "inbound" | "outbound";
  sender: string;
  recipient: string;
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
  };
  clinical?: {
    notes: NoteSummary[];
    goals: Goal[];
    outcomes: OutcomeTrend[];
    complianceFindings: ComplianceFinding[];
    artifacts: Artifact[];
    homePrograms: HomeProgram[];
    voiceCaptures: VoiceCapture[];
    timeline: TimelineEvent[];
  };
  operations?: {
    consents: ConsentSummary[];
    intakes: IntakeSummary[];
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
