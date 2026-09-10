import type {
  AppointmentType,
  ArAgingReport,
  BillingSummaryReport,
  Artifact,
  AuditEvent,
  CashPackage,
  Charge,
  Claim,
  ClaimDenial,
  ClaimTransaction,
  ClaimValidationFinding,
  ClinicLocation,
  CodingSuggestions,
  Cms1500Data,
  DashboardData,
  DiagnosisCode,
  DocumentationListFilters,
  EpisodeOfCare,
  Goal,
  GoalSuggestion,
  HomeExercise,
  HomeProgram,
  HomeProgramSuggestion,
  PatientStatement,
  PatientStatementData,
  PatientSuperbillData,
  ServicePrice,
  NoteDetail,
  NoteSummary,
  OperationalReport,
  Patient,
  PatientAuthorization,
  PatientDetail,
  PatientDocumentSummary,
  PatientInsurancePolicy,
  PatientWorkspace,
  Payer,
  ManagedClient,
  ManagedClientUser,
  PrivilegedAccessGrant,
  PrivilegedPatientDetail,
  PublicAvailability,
  PortalAppointment,
  PortalAppointmentsList,
  PortalAppointmentType,
  PortalDashboard,
  FormSubmissionDetail,
  PortalDocument,
  PortalFormOverview,
  PortalFormSubmission,
  PortalHepLog,
  PortalHepProgram,
  PortalInsurancePolicy,
  PortalInviteResult,
  PortalMessage,
  PortalOutcomeAssignment,
  PortalOutcomeSchema,
  PortalOutcomeSubmitResult,
  PortalPaymentChargeResult,
  PortalPayerOption,
  PortalPayments,
  PortalProfile,
  PortalProfileChangeRequest,
  PortalSuperbillSummary,
  ProfileChangeRequestStaff,
  TelehealthJoinResult,
  PortalWaitlistEntry,
  PortalWaitlistStaffEntry,
  PublicAppointmentType,
  PublicBookingConfirmation,
  PublicBookingPatient,
  PublicLocation,
  PublicOrganization,
  PublicProvider,
  Referral,
  ScheduleData,
  StaffOption,
  ClientSubscriptionDetail,
  CredentialDashboardRow,
  SuperAdminDashboard,
  TimelineEvent,
  UserLicenseInfo,
  UserSessionInfo,
  WorkspaceUser,
} from "./types";

import { notifySessionEnded } from "../lib/sessionEvents";

const API_ROOT = import.meta.env.VITE_API_ROOT || "/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly fields: Record<string, string> = {},
    readonly code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

let csrfToken: string | null = null;

async function readJson<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail =
      typeof payload.detail === "string" ? payload.detail : "The request could not be completed.";
    // A 401 carrying `code` means an already-established session just ended
    // (new login elsewhere, timeout, password change, admin action) — as
    // opposed to a plain "not logged in yet" 401, which has no code.
    if (response.status === 401 && typeof payload.code === "string") {
      notifySessionEnded(detail);
    }
    throw new ApiError(detail, response.status, payload.errors || {}, payload.code);
  }
  return payload as T;
}

async function ensureCsrfToken(): Promise<string> {
  if (csrfToken) {
    return csrfToken;
  }
  const response = await fetch(`${API_ROOT}/auth/csrf/`, {
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  const payload = await readJson<{ csrfToken: string }>(response);
  csrfToken = payload.csrfToken;
  return csrfToken;
}

async function request<T>(
  path: string,
  options: { method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE"; body?: Record<string, unknown> } = {},
): Promise<T> {
  const method = options.method || "GET";
  const isWrite = method !== "GET";
  const headers: HeadersInit = { Accept: "application/json" };
  if (isWrite) {
    headers["Content-Type"] = "application/json";
    headers["X-CSRFToken"] = await ensureCsrfToken();
  }
  const response = await fetch(`${API_ROOT}${path}`, {
    method,
    credentials: "include",
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  return readJson<T>(response);
}

export const api = {
  async login(username: string, password: string, portalSlug = "") {
    const payload = await request<{ user: WorkspaceUser; csrfToken: string }>("/auth/login/", {
      method: "POST",
      body: { username, password, portalSlug },
    });
    csrfToken = payload.csrfToken;
    return payload.user;
  },
  async facility(slug: string) {
    return request<{ name: string; slug: string; status: string }>(`/auth/facility/?slug=${encodeURIComponent(slug)}`);
  },
  async previewInvitation(token: string) {
    return request<{ organizationName: string; email: string }>(`/auth/activate-invitation/?token=${encodeURIComponent(token)}`);
  },
  async activateInvitation(token: string, password: string) {
    const payload = await request<{ user: WorkspaceUser; csrfToken: string }>("/auth/activate-invitation/", {
      method: "POST",
      body: { token, password },
    });
    csrfToken = payload.csrfToken;
    return payload.user;
  },
  async invitePatientToPortal(patientId: string, email: string) {
    return request<PortalInviteResult>(`/patients/${patientId}/portal-invite/`, { method: "POST", body: { email } });
  },
  async portalDashboard() {
    return request<PortalDashboard>("/portal/dashboard/");
  },
  async portalAppointments() {
    return request<PortalAppointmentsList>("/portal/appointments/");
  },
  async portalCancelAppointment(appointmentId: string) {
    return request<{ appointment: PortalAppointment }>(`/portal/appointments/${appointmentId}/cancel/`, { method: "POST" });
  },
  async portalRescheduleAppointment(appointmentId: string, startDatetime: string) {
    return request<{ appointment: PortalAppointment }>(`/portal/appointments/${appointmentId}/reschedule/`, {
      method: "POST",
      body: { startDatetime },
    });
  },
  async portalConfirmAppointment(appointmentId: string) {
    return request<{ appointment: PortalAppointment }>(`/portal/appointments/${appointmentId}/confirm/`, { method: "POST" });
  },
  async portalBookingLocations() {
    return request<{ locations: PublicLocation[] }>("/portal/booking/locations/");
  },
  async portalBookingAppointmentTypes(locationId = "") {
    const params = locationId ? `?location_id=${encodeURIComponent(locationId)}` : "";
    return request<{ appointmentTypes: PortalAppointmentType[] }>(`/portal/booking/appointment-types/${params}`);
  },
  async portalBookingProviders(locationId: string, appointmentTypeId: string) {
    const params = new URLSearchParams({ location_id: locationId, appointment_type_id: appointmentTypeId });
    return request<{ providers: PublicProvider[] }>(`/portal/booking/providers/?${params}`);
  },
  async portalBookingAvailability(
    locationId: string,
    appointmentTypeId: string,
    date: string,
    providerId = "",
    excludeAppointmentId = "",
  ) {
    const params = new URLSearchParams({ location_id: locationId, appointment_type_id: appointmentTypeId, date });
    if (providerId) params.set("provider_id", providerId);
    if (excludeAppointmentId) params.set("exclude_appointment_id", excludeAppointmentId);
    return request<PublicAvailability>(`/portal/booking/availability/?${params}`);
  },
  async portalCreateBooking(body: {
    locationId: string;
    appointmentTypeId: string;
    providerId: string;
    startDatetime: string;
    reasonForVisit?: string;
  }) {
    return request<{ appointment: PortalAppointment }>("/portal/booking/", { method: "POST", body });
  },
  async portalWaitlist() {
    return request<{ entries: PortalWaitlistEntry[] }>("/portal/waitlist/");
  },
  async portalJoinWaitlist(body: {
    locationId?: string;
    appointmentTypeId?: string;
    providerId?: string;
    earliestDate: string;
    latestDate?: string;
    notes?: string;
  }) {
    return request<{ entry: PortalWaitlistEntry }>("/portal/waitlist/", { method: "POST", body });
  },
  async portalLeaveWaitlist(entryId: string) {
    return request<{ entry: PortalWaitlistEntry }>(`/portal/waitlist/${entryId}/leave/`, { method: "POST" });
  },
  async waitlistStaffList() {
    return request<{ entries: PortalWaitlistStaffEntry[] }>("/waitlist/");
  },
  async waitlistStaffUpdateStatus(entryId: string, status: "fulfilled" | "cancelled") {
    return request<{ entry: PortalWaitlistStaffEntry }>(`/waitlist/${entryId}/status/`, {
      method: "POST",
      body: { status },
    });
  },
  async portalForms() {
    return request<{ forms: PortalFormOverview[] }>("/portal/forms/");
  },
  async portalFormDetail(slug: string) {
    return request<{ submission: PortalFormSubmission }>(`/portal/forms/${slug}/`);
  },
  async portalFormSave(slug: string, data: Record<string, unknown>) {
    return request<{ submission: PortalFormSubmission }>(`/portal/forms/${slug}/save/`, { method: "POST", body: { data } });
  },
  async portalFormSubmit(slug: string, data: Record<string, unknown>) {
    return request<{ submission: PortalFormSubmission }>(`/portal/forms/${slug}/submit/`, { method: "POST", body: { data } });
  },
  async portalInsurancePayers() {
    return request<{ payers: PortalPayerOption[] }>("/portal/insurance/payers/");
  },
  async portalInsurancePolicies() {
    return request<{ policies: PortalInsurancePolicy[] }>("/portal/insurance/");
  },
  async portalCreateInsurancePolicy(body: Record<string, unknown>) {
    return request<{ policy: PortalInsurancePolicy }>("/portal/insurance/", { method: "POST", body });
  },
  async portalUploadInsuranceCard(policyId: string, side: "front" | "back", file: File) {
    const token = await ensureCsrfToken();
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(`${API_ROOT}/portal/insurance/${policyId}/card/${side}/`, {
      method: "POST",
      credentials: "include",
      headers: { Accept: "application/json", "X-CSRFToken": token },
      body: formData,
    });
    return readJson<{ policy: PortalInsurancePolicy }>(response);
  },
  async portalDocuments() {
    return request<{ documents: PortalDocument[] }>("/portal/documents/");
  },
  async portalUploadDocument(file: File, title: string, description: string) {
    const token = await ensureCsrfToken();
    const formData = new FormData();
    formData.append("file", file);
    formData.append("title", title);
    formData.append("description", description);
    const response = await fetch(`${API_ROOT}/portal/documents/`, {
      method: "POST",
      credentials: "include",
      headers: { Accept: "application/json", "X-CSRFToken": token },
      body: formData,
    });
    return readJson<{ document: PortalDocument }>(response);
  },
  portalDocumentDownloadUrl(documentId: string) {
    return `${API_ROOT}/portal/documents/${documentId}/download/`;
  },
  async portalHep() {
    return request<{ program: PortalHepProgram | null }>("/portal/hep/");
  },
  async portalHepLogs() {
    return request<{ logs: PortalHepLog[] }>("/portal/hep/logs/");
  },
  async portalCompleteExercise(exerciseId: string, body: { painLevel?: number | null; difficultyLevel?: number | null; comment?: string }) {
    return request<{ log: PortalHepLog }>(`/portal/hep/exercises/${exerciseId}/complete/`, { method: "POST", body });
  },
  async portalOutcomes() {
    return request<{ assignments: PortalOutcomeAssignment[] }>("/portal/outcomes/");
  },
  async portalOutcomeDetail(assignmentId: string) {
    return request<{ assignment: PortalOutcomeAssignment; schema: PortalOutcomeSchema }>(`/portal/outcomes/${assignmentId}/`);
  },
  async portalOutcomeSubmit(assignmentId: string, itemResponses: Record<string, unknown>) {
    return request<PortalOutcomeSubmitResult>(`/portal/outcomes/${assignmentId}/submit/`, {
      method: "POST",
      body: { itemResponses },
    });
  },
  async portalMessages() {
    return request<{ messages: PortalMessage[] }>("/portal/messages/");
  },
  async portalSendMessage(body: { category: string; subject: string; body: string }) {
    return request<{ message: PortalMessage }>("/portal/messages/", { method: "POST", body });
  },
  async portalMarkMessageRead(messageId: string) {
    return request<{ message: PortalMessage }>(`/portal/messages/${messageId}/read/`, { method: "POST" });
  },
  async portalPayments() {
    return request<PortalPayments>("/portal/payments/");
  },
  async portalStatementDetail(statementId: string) {
    return request<{ statement: PatientStatementData }>(`/portal/payments/statements/${statementId}/`);
  },
  async portalPaymentCharge(amount: string) {
    return request<PortalPaymentChargeResult>("/portal/payments/charge/", { method: "POST", body: { amount } });
  },
  async portalSuperbills() {
    return request<{ superbills: PortalSuperbillSummary[] }>("/portal/superbills/");
  },
  async portalSuperbillDetail(superbillId: string) {
    return request<{ superbill: PatientSuperbillData }>(`/portal/superbills/${superbillId}/`);
  },
  async portalJoinTelehealth(appointmentId: string) {
    return request<TelehealthJoinResult>(`/portal/appointments/${appointmentId}/telehealth/join/`, { method: "POST" });
  },
  async portalProfile() {
    return request<{ profile: PortalProfile }>("/portal/profile/");
  },
  async portalUpdateProfilePreferences(body: Record<string, unknown>) {
    return request<{ profile: PortalProfile }>("/portal/profile/preferences/", { method: "PATCH", body });
  },
  async portalSubmitProfileChangeRequest(body: Record<string, unknown>) {
    return request<{ changeRequest: PortalProfileChangeRequest }>("/portal/profile/change-requests/", {
      method: "POST",
      body,
    });
  },
  async profileChangeRequestsStaffList() {
    return request<{ requests: ProfileChangeRequestStaff[] }>("/profile-change-requests/");
  },
  async decideProfileChangeRequest(requestId: string, decision: "approve" | "reject", note = "") {
    return request<{ changeRequest: ProfileChangeRequestStaff }>(`/profile-change-requests/${requestId}/decide/`, {
      method: "POST",
      body: { decision, note },
    });
  },
  async logout() {
    await request("/auth/logout/", { method: "POST" });
    csrfToken = null;
  },
  async changePassword(body: { currentPassword?: string; newPassword: string; confirmPassword?: string }) {
    return request<{ detail: string }>("/auth/change-password/", { method: "POST", body });
  },
  async me() {
    const payload = await request<{ user: WorkspaceUser }>("/auth/me/");
    return payload.user;
  },
  async mySessions() {
    return request<{ sessions: UserSessionInfo[] }>("/auth/sessions/");
  },
  async revokeMySession(sessionId: string) {
    return request<{ detail: string }>(`/auth/sessions/${sessionId}/revoke/`, { method: "POST" });
  },
  async revokeMyOtherSessions() {
    return request<{ detail: string; revokedCount: number }>("/auth/sessions/revoke-others/", { method: "POST" });
  },
  async dashboard() {
    return request<DashboardData>("/dashboard/");
  },
  async organizationUsers(filters: Record<string, string> = {}) {
    const params = new URLSearchParams(filters);
    const search = params.toString() ? `?${params.toString()}` : "";
    return request<{ users: ManagedClientUser[]; total: number; page: number; pageSize: number }>(`/users/${search}`);
  },
  async createOrganizationUser(body: Record<string, unknown>) {
    return request<{ user: ManagedClientUser }>("/users/", { method: "POST", body });
  },
  async updateOrganizationUser(userId: string, body: Record<string, unknown>) {
    return request<{ user: ManagedClientUser }>(`/users/${userId}/`, { method: "PATCH", body });
  },
  async organizationUserStatusAction(userId: string, action: string, reason = "") {
    return request<{ user: ManagedClientUser }>(`/users/${userId}/status-action/`, {
      method: "POST",
      body: { action, reason },
    });
  },
  async organizationUserRevokeSessions(userId: string) {
    return request<{ user: ManagedClientUser; revokedCount: number }>(`/users/${userId}/revoke-sessions/`, {
      method: "POST",
    });
  },
  async createOrganizationUserLicense(userId: string, body: Record<string, unknown>) {
    return request<{ license: UserLicenseInfo }>(`/users/${userId}/licenses/`, { method: "POST", body });
  },
  async updateOrganizationUserLicense(userId: string, licenseId: string, body: Record<string, unknown>) {
    return request<{ license: UserLicenseInfo }>(`/users/${userId}/licenses/${licenseId}/`, { method: "PATCH", body });
  },
  async deleteOrganizationUserLicense(userId: string, licenseId: string) {
    return request<Record<string, never>>(`/users/${userId}/licenses/${licenseId}/`, { method: "DELETE" });
  },
  async uploadOrganizationUserLicenseDocument(userId: string, licenseId: string, file: File) {
    const token = await ensureCsrfToken();
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(`${API_ROOT}/users/${userId}/licenses/${licenseId}/document/`, {
      method: "POST",
      credentials: "include",
      headers: { Accept: "application/json", "X-CSRFToken": token },
      body: formData,
    });
    return readJson<{ license: UserLicenseInfo }>(response);
  },
  organizationUserLicenseDocumentUrl(userId: string, licenseId: string) {
    return `${API_ROOT}/users/${userId}/licenses/${licenseId}/document/`;
  },
  async verifyOrganizationUserLicense(userId: string, licenseId: string, notes = "") {
    return request<{ license: UserLicenseInfo }>(`/users/${userId}/licenses/${licenseId}/verify/`, {
      method: "POST",
      body: { notes },
    });
  },
  async patients(query = "") {
    const search = query ? `?q=${encodeURIComponent(query)}` : "";
    return request<{ query: string; count: number; truncated: boolean; patients: Patient[] }>(
      `/patients/${search}`,
    );
  },
  async patient(id: string) {
    return request<PatientDetail>(`/patients/${id}/`);
  },
  async createPatient(body: Record<string, unknown>) {
    return request<{ patient: Patient }>("/patients/", { method: "POST", body });
  },
  async patientForEdit(id: string) {
    return request<{ patient: Patient }>(`/patients/${id}/edit/`);
  },
  async patientDocuments(patientId: string) {
    return request<{ documents: PatientDocumentSummary[] }>(`/patients/${patientId}/documents/`);
  },
  async uploadPatientDocument(patientId: string, file: File, title: string, description: string, visibleToPatient = false) {
    const token = await ensureCsrfToken();
    const formData = new FormData();
    formData.append("file", file);
    formData.append("title", title);
    formData.append("description", description);
    formData.append("visibleToPatient", visibleToPatient ? "true" : "false");
    const response = await fetch(`${API_ROOT}/patients/${patientId}/documents/`, {
      method: "POST",
      credentials: "include",
      headers: { Accept: "application/json", "X-CSRFToken": token },
      body: formData,
    });
    return readJson<{ document: PatientDocumentSummary }>(response);
  },
  patientDocumentDownloadUrl(patientId: string, documentId: string) {
    return `${API_ROOT}/patients/${patientId}/documents/${documentId}/download/`;
  },
  async updatePatientDocumentVisibility(patientId: string, documentId: string, visibleToPatient: boolean) {
    return request<{ document: PatientDocumentSummary }>(`/patients/${patientId}/documents/${documentId}/visibility/`, {
      method: "PATCH",
      body: { visibleToPatient },
    });
  },
  async updatePatient(id: string, body: Record<string, unknown>) {
    return request<{ patient: Patient }>(`/patients/${id}/`, { method: "PATCH", body });
  },
  async deactivatePatient(id: string) {
    return request<{ patient: Patient }>(`/patients/${id}/`, { method: "DELETE" });
  },
  async staffOptions() {
    return request<{ staff: StaffOption[] }>("/staff/");
  },
  async locations() {
    return request<{ locations: ClinicLocation[] }>("/locations/");
  },
  async createLocation(body: Record<string, unknown>) {
    return request<{ location: ClinicLocation }>("/locations/", { method: "POST", body });
  },
  async updateLocation(id: string, body: Record<string, unknown>) {
    return request<{ location: ClinicLocation }>(`/locations/${id}/`, { method: "PATCH", body });
  },
  async deactivateLocation(id: string) {
    return request<{ location: ClinicLocation }>(`/locations/${id}/`, { method: "DELETE" });
  },
  async appointmentTypes() {
    return request<{ appointmentTypes: AppointmentType[] }>("/appointment-types/");
  },
  async createAppointmentType(body: Record<string, unknown>) {
    return request<{ appointmentType: AppointmentType }>("/appointment-types/", { method: "POST", body });
  },
  async updateAppointmentType(id: string, body: Record<string, unknown>) {
    return request<{ appointmentType: AppointmentType }>(`/appointment-types/${id}/`, { method: "PATCH", body });
  },
  async deactivateAppointmentType(id: string) {
    return request<{ appointmentType: AppointmentType }>(`/appointment-types/${id}/`, { method: "DELETE" });
  },
  async operationalReport() {
    return request<OperationalReport>("/reports/operations/");
  },
  async payers(activeOnly = false) {
    return request<{ payers: Payer[] }>(`/payers/${activeOnly ? "?activeOnly=1" : ""}`);
  },
  async createPayer(body: Record<string, unknown>) {
    return request<{ payer: Payer }>("/payers/", { method: "POST", body });
  },
  async updatePayer(id: string, body: Record<string, unknown>) {
    return request<{ payer: Payer }>(`/payers/${id}/`, { method: "PATCH", body });
  },
  async deactivatePayer(id: string) {
    return request<{ payer: Payer }>(`/payers/${id}/`, { method: "DELETE" });
  },
  async patientInsurancePolicies(patientId: string) {
    return request<{ policies: PatientInsurancePolicy[] }>(`/patients/${patientId}/insurance/`);
  },
  async createPatientInsurancePolicy(patientId: string, body: Record<string, unknown>) {
    return request<{ policy: PatientInsurancePolicy }>(`/patients/${patientId}/insurance/`, { method: "POST", body });
  },
  async updatePatientInsurancePolicy(patientId: string, policyId: string, body: Record<string, unknown>) {
    return request<{ policy: PatientInsurancePolicy }>(`/patients/${patientId}/insurance/${policyId}/`, { method: "PATCH", body });
  },
  async terminatePatientInsurancePolicy(patientId: string, policyId: string) {
    return request<{ policy: PatientInsurancePolicy }>(`/patients/${patientId}/insurance/${policyId}/`, { method: "DELETE" });
  },
  async uploadPatientInsuranceCard(patientId: string, policyId: string, side: "front" | "back", file: File) {
    const token = await ensureCsrfToken();
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(`${API_ROOT}/patients/${patientId}/insurance/${policyId}/card/${side}/upload/`, {
      method: "POST",
      credentials: "include",
      headers: { Accept: "application/json", "X-CSRFToken": token },
      body: formData,
    });
    return readJson<{ policy: PatientInsurancePolicy }>(response);
  },
  patientInsuranceCardUrl(patientId: string, policyId: string, side: "front" | "back") {
    return `${API_ROOT}/patients/${patientId}/insurance/${policyId}/card/${side}/`;
  },
  async diagnosisCodes(query = "") {
    const search = query ? `?q=${encodeURIComponent(query)}` : "";
    return request<{ diagnosisCodes: DiagnosisCode[] }>(`/diagnosis-codes/${search}`);
  },
  async patientCharges(patientId: string) {
    return request<{ charges: Charge[] }>(`/patients/${patientId}/charges/`);
  },
  async createPatientCharge(patientId: string, body: Record<string, unknown>) {
    return request<{ charge: Charge }>(`/patients/${patientId}/charges/`, { method: "POST", body });
  },
  async updatePatientCharge(patientId: string, chargeId: string, body: Record<string, unknown>) {
    return request<{ charge: Charge }>(`/patients/${patientId}/charges/${chargeId}/`, { method: "PATCH", body });
  },
  async patientClaims(patientId: string) {
    return request<{ claims: Claim[] }>(`/patients/${patientId}/claims/`);
  },
  async createPatientClaim(patientId: string, body: Record<string, unknown>) {
    return request<{ claim: Claim }>(`/patients/${patientId}/claims/`, { method: "POST", body });
  },
  async validateClaim(patientId: string, claimId: string) {
    return request<{ claim: Claim; findings: ClaimValidationFinding[] }>(
      `/patients/${patientId}/claims/${claimId}/validate/`, { method: "POST" },
    );
  },
  async submitClaim(patientId: string, claimId: string) {
    return request<{ claim: Claim; clearinghouseMessage: string }>(`/patients/${patientId}/claims/${claimId}/submit/`, { method: "POST" });
  },
  async checkClaimStatus(patientId: string, claimId: string) {
    return request<{ claim: Claim; clearinghouseStatus: string; clearinghouseMessage: string }>(
      `/patients/${patientId}/claims/${claimId}/check-status/`, { method: "POST" },
    );
  },
  async verifyPatientInsuranceEligibility(patientId: string, policyId: string) {
    return request<{ verified: boolean; message: string }>(
      `/patients/${patientId}/insurance/${policyId}/verify-eligibility/`, { method: "POST" },
    );
  },
  async updateClaimStatus(patientId: string, claimId: string, status: string) {
    return request<{ claim: Claim }>(`/patients/${patientId}/claims/${claimId}/status/`, {
      method: "POST", body: { status },
    });
  },
  async claimCms1500(patientId: string, claimId: string) {
    return request<{ cms1500: Cms1500Data }>(`/patients/${patientId}/claims/${claimId}/cms1500/`);
  },
  async patientTransactions(patientId: string) {
    return request<{ transactions: ClaimTransaction[] }>(`/patients/${patientId}/transactions/`);
  },
  async createPatientTransaction(patientId: string, body: Record<string, unknown>) {
    return request<{ transaction: ClaimTransaction }>(`/patients/${patientId}/transactions/`, { method: "POST", body });
  },
  async matchTransaction(patientId: string, transactionId: string, claimId: string) {
    return request<{ transaction: ClaimTransaction }>(`/patients/${patientId}/transactions/${transactionId}/match/`, {
      method: "POST", body: { claimId },
    });
  },
  async arAgingReport(filters: Record<string, string> = {}) {
    const params = new URLSearchParams(filters);
    const search = params.toString() ? `?${params.toString()}` : "";
    return request<ArAgingReport>(`/reports/ar-aging/${search}`);
  },
  async claimDenials(patientId: string, claimId: string) {
    return request<{ denials: ClaimDenial[] }>(`/patients/${patientId}/claims/${claimId}/denials/`);
  },
  async createClaimDenial(patientId: string, claimId: string, body: Record<string, unknown>) {
    return request<{ denial: ClaimDenial }>(`/patients/${patientId}/claims/${claimId}/denials/`, { method: "POST", body });
  },
  async updateDenial(patientId: string, denialId: string, body: Record<string, unknown>) {
    return request<{ denial: ClaimDenial }>(`/patients/${patientId}/denials/${denialId}/`, { method: "PATCH", body });
  },
  async denialWorkQueue(filters: Record<string, string> = {}) {
    const params = new URLSearchParams(filters);
    const search = params.toString() ? `?${params.toString()}` : "";
    return request<{ denials: ClaimDenial[] }>(`/reports/denials/${search}`);
  },
  async patientStatements(patientId: string) {
    return request<{ statements: PatientStatement[] }>(`/patients/${patientId}/statements/`);
  },
  async generatePatientStatement(patientId: string, body: Record<string, unknown>) {
    return request<{ statement: PatientStatement; data: PatientStatementData }>(`/patients/${patientId}/statements/`, {
      method: "POST", body,
    });
  },
  async patientStatementDetail(patientId: string, statementId: string) {
    return request<{ statement: PatientStatement; data: PatientStatementData }>(
      `/patients/${patientId}/statements/${statementId}/`,
    );
  },
  async servicePrices(activeOnly = false) {
    return request<{ servicePrices: ServicePrice[] }>(`/service-prices/${activeOnly ? "?activeOnly=1" : ""}`);
  },
  async createServicePrice(body: Record<string, unknown>) {
    return request<{ servicePrice: ServicePrice }>("/service-prices/", { method: "POST", body });
  },
  async updateServicePrice(id: string, body: Record<string, unknown>) {
    return request<{ servicePrice: ServicePrice }>(`/service-prices/${id}/`, { method: "PATCH", body });
  },
  async deactivateServicePrice(id: string) {
    return request<{ servicePrice: ServicePrice }>(`/service-prices/${id}/`, { method: "DELETE" });
  },
  async patientCashPackages(patientId: string) {
    return request<{ cashPackages: CashPackage[] }>(`/patients/${patientId}/cash-packages/`);
  },
  async createCashPackage(patientId: string, body: Record<string, unknown>) {
    return request<{ cashPackage: CashPackage }>(`/patients/${patientId}/cash-packages/`, { method: "POST", body });
  },
  async updateCashPackage(patientId: string, packageId: string, body: Record<string, unknown>) {
    return request<{ cashPackage: CashPackage }>(`/patients/${patientId}/cash-packages/${packageId}/`, {
      method: "PATCH", body,
    });
  },
  async superbillData(patientId: string, superbillId: string) {
    return request<{ superbill: PatientSuperbillData }>(`/patients/${patientId}/superbills/${superbillId}/data/`);
  },
  async billingSummaryReport(filters: Record<string, string> = {}) {
    const params = new URLSearchParams(filters);
    const search = params.toString() ? `?${params.toString()}` : "";
    return request<BillingSummaryReport>(`/reports/billing-summary/${search}`);
  },
  async workspace(id: string) {
    return request<PatientWorkspace>(`/patients/${id}/workspace/`);
  },
  async timeline(id: string, query = "") {
    const search = query ? `?q=${encodeURIComponent(query)}` : "";
    return request<{ query: string; events: TimelineEvent[] }>(`/patients/${id}/timeline/${search}`);
  },
  async createDraft(patientId: string, kind: string) {
    return request<{ artifact: Artifact }>(`/patients/${patientId}/drafts/`, {
      method: "POST",
      body: { kind },
    });
  },
  async reviewDraft(artifactId: string, action: "approve" | "reject" | "apply", reviewNote = "") {
    return request<{ artifact: Artifact; appliedNote?: unknown }>(`/drafts/${artifactId}/review/`, {
      method: "POST",
      body: { action, reviewNote },
    });
  },
  async reviewDraftSection(artifactId: string, sectionKey: string, sectionStatus: "accepted" | "edited" | "rejected", reviewedText?: string) {
    return request<{ artifact: Artifact }>(`/drafts/${artifactId}/review/`, {
      method: "POST",
      body: { action: "section_review", sectionKey, sectionStatus, reviewedText },
    });
  },
  async goalSuggestions(patientId: string, functionalLimitation: string, measure = "") {
    return request<{ suggestions: GoalSuggestion[] }>(`/patients/${patientId}/goal-suggestions/`, {
      method: "POST",
      body: { functionalLimitation, measure },
    });
  },
  async createGoal(patientId: string, body: Record<string, unknown>) {
    return request<{ goal: Goal }>(`/patients/${patientId}/goals/`, { method: "POST", body });
  },
  async approveGoal(goalId: string) {
    return request<{ goal: Goal }>(`/goals/${goalId}/approve/`, { method: "POST" });
  },
  async recordOutcome(patientId: string, body: Record<string, unknown>) {
    return request(`/patients/${patientId}/outcomes/`, { method: "POST", body });
  },
  async assignOutcomeMeasure(patientId: string, measure: string) {
    return request<{ assignment: PortalOutcomeAssignment }>(`/patients/${patientId}/outcome-assignments/`, {
      method: "POST",
      body: { measure },
    });
  },
  async listDocumentation(filters: DocumentationListFilters = {}) {
    const params = new URLSearchParams(filters as Record<string, string>);
    const search = params.toString() ? `?${params.toString()}` : "";
    return request<{ notes: NoteSummary[]; total: number; page: number; pageSize: number }>(`/documentation/${search}`);
  },
  async createNote(patientId: string, body: Record<string, unknown>) {
    return request<{ note: NoteDetail }>(`/patients/${patientId}/notes/`, { method: "POST", body });
  },
  async patientEpisodesOfCare(patientId: string) {
    return request<{ episodesOfCare: EpisodeOfCare[] }>(`/patients/${patientId}/episodes/`);
  },
  async getNote(noteId: string) {
    return request<{ note: NoteDetail }>(`/notes/${noteId}/`);
  },
  async updateNote(noteId: string, body: Record<string, unknown>) {
    return request<{ note: NoteDetail }>(`/notes/${noteId}/`, { method: "PATCH", body });
  },
  async signNote(noteId: string, attestation: boolean) {
    return request<{ note: NoteDetail }>(`/notes/${noteId}/sign/`, { method: "POST", body: { attestation } });
  },
  async cosignNote(noteId: string) {
    return request<{ note: NoteDetail }>(`/notes/${noteId}/cosign/`, { method: "POST" });
  },
  async createAddendum(noteId: string, reason: string, body: string) {
    return request<{ note: NoteDetail }>(`/notes/${noteId}/addenda/`, { method: "POST", body: { reason, body } });
  },
  async replaceInterventions(noteId: string, items: Record<string, unknown>[]) {
    return request<{ interventionItems: NoteDetail["interventionItems"] }>(`/notes/${noteId}/interventions/`, {
      method: "PUT",
      body: { items },
    });
  },
  async createCodingSuggestions(noteId: string) {
    return request<{ artifact: Artifact; codingSuggestions: CodingSuggestions }>(`/notes/${noteId}/coding-suggestions/`, {
      method: "POST",
    });
  },
  async saveVoiceCapture(patientId: string, body: Record<string, unknown>) {
    return request(`/patients/${patientId}/voice-captures/`, { method: "POST", body });
  },
  async createNoteFromVoice(captureId: string) {
    return request(`/voice-captures/${captureId}/create-note/`, { method: "POST" });
  },
  async homeProgramSuggestions(patientId: string) {
    return request<{ suggestions: HomeProgramSuggestion[] }>(
      `/patients/${patientId}/home-program-suggestions/`,
    );
  },
  async createHomeProgram(patientId: string, body: Record<string, unknown>) {
    return request<{ homeProgram: HomeProgram }>(`/patients/${patientId}/home-programs/`, {
      method: "POST",
      body,
    });
  },
  async approveHomeProgram(programId: string) {
    return request<{ homeProgram: HomeProgram }>(`/home-programs/${programId}/approve/`, {
      method: "POST",
    });
  },
  async createHomeExercise(programId: string, body: Record<string, unknown>) {
    return request<{ exercise: HomeExercise }>(`/home-programs/${programId}/exercises/`, { method: "POST", body });
  },
  async updateHomeExercise(programId: string, exerciseId: string, body: Record<string, unknown>) {
    return request<{ exercise: HomeExercise }>(`/home-programs/${programId}/exercises/${exerciseId}/`, {
      method: "PATCH",
      body,
    });
  },
  async createIntake(patientId: string, body: Record<string, unknown>) {
    return request(`/patients/${patientId}/intakes/`, { method: "POST", body });
  },
  async createConsent(patientId: string, body: Record<string, unknown>) {
    return request(`/patients/${patientId}/consents/`, { method: "POST", body });
  },
  async formSubmissionDetail(patientId: string, submissionId: string) {
    return request<{ submission: FormSubmissionDetail }>(`/patients/${patientId}/forms/${submissionId}/`);
  },
  async createReferral(patientId: string, body: Record<string, unknown>) {
    return request<{ referral: Referral }>(`/patients/${patientId}/referrals/`, { method: "POST", body });
  },
  async createEpisodeOfCare(patientId: string, body: Record<string, unknown>) {
    return request<{ episodeOfCare: EpisodeOfCare }>(`/patients/${patientId}/episodes/`, { method: "POST", body });
  },
  async createAuthorization(patientId: string, body: Record<string, unknown>) {
    return request<{ authorization: PatientAuthorization }>(`/patients/${patientId}/authorizations/`, { method: "POST", body });
  },
  async updateReferralStatus(referralId: string, status: string) {
    return request<{ referral: Referral }>(`/referrals/${referralId}/status/`, { method: "POST", body: { status } });
  },
  async sendSecureMessage(patientId: string, body: Record<string, unknown>) {
    return request(`/patients/${patientId}/messages/`, { method: "POST", body });
  },
  async createSuperbill(patientId: string, body: Record<string, unknown>) {
    return request(`/patients/${patientId}/superbills/`, { method: "POST", body });
  },
  async createPayment(patientId: string, body: Record<string, unknown>) {
    return request(`/patients/${patientId}/payments/`, { method: "POST", body });
  },
  async createAppointment(patientId: string, body: Record<string, unknown>) {
    return request(`/patients/${patientId}/appointments/`, { method: "POST", body });
  },
  async auditEvents(limit = 60) {
    return request<{ events: AuditEvent[]; limit: number }>(`/audit-events/?limit=${limit}`);
  },
  async superAdminDashboard() {
    return request<SuperAdminDashboard>("/super-admin/dashboard/");
  },
  async credentialDashboard(filters: Record<string, string> = {}) {
    const params = new URLSearchParams(filters);
    const search = params.toString() ? `?${params.toString()}` : "";
    return request<{ licenses: CredentialDashboardRow[]; total: number; page: number; pageSize: number }>(`/super-admin/credentials/${search}`);
  },
  async clientSubscription(clientNumber: number) {
    return request<ClientSubscriptionDetail>(`/super-admin/clients/${clientNumber}/subscription/`);
  },
  async updateClientSubscription(clientNumber: number, body: Record<string, unknown>) {
    return request<{ subscription: ClientSubscriptionDetail["subscription"] }>(`/super-admin/clients/${clientNumber}/subscription/`, {
      method: "PATCH",
      body,
    });
  },
  async managedClients(query = "", filters: Record<string, string> = {}) {
    const params = new URLSearchParams({ ...(query ? { q: query } : {}), ...filters });
    const search = params.toString() ? `?${params.toString()}` : "";
    return request<{ clients: ManagedClient[]; total: number; page: number; pageSize: number }>(`/super-admin/clients/${search}`);
  },
  async createManagedClient(body: Record<string, unknown>) {
    return request<{ client: ManagedClient; administrator: { id: string; email: string }; developmentInviteToken: string; invitationUrl: string }>("/super-admin/clients/create/", { method: "POST", body });
  },
  async managedClient(clientNumber: number) {
    return request<{ client: ManagedClient }>(`/super-admin/clients/${clientNumber}/`);
  },
  async updateManagedClient(clientNumber: number, body: Record<string, unknown>) {
    return request<{ client: ManagedClient }>(`/super-admin/clients/${clientNumber}/`, { method: "PATCH", body });
  },
  async setManagedClientStatus(clientNumber: number, action: "suspend" | "activate", reason = "") {
    return request<{ client: ManagedClient }>(`/super-admin/clients/${clientNumber}/${action}/`, { method: "PATCH", body: { reason } });
  },
  async archiveManagedClient(clientNumber: number, reason = "") {
    return request<{ client: ManagedClient }>(`/super-admin/clients/${clientNumber}/`, { method: "DELETE", body: { reason } });
  },
  async clientAuditEvents(clientNumber: number) {
    return request<{ events: AuditEvent[] }>(`/super-admin/clients/${clientNumber}/audit-events/`);
  },
  async privilegedAccessGrants(clientNumber: number) {
    return request<{ grants: PrivilegedAccessGrant[] }>(`/super-admin/clients/${clientNumber}/privileged-access/`);
  },
  async requestPrivilegedAccess(clientNumber: number, reason: string, durationHours: number) {
    return request<{ grant: PrivilegedAccessGrant }>(`/super-admin/clients/${clientNumber}/privileged-access/`, {
      method: "POST",
      body: { reason, durationHours },
    });
  },
  async revokePrivilegedAccess(clientNumber: number, grantId: string) {
    return request<{ grant: PrivilegedAccessGrant }>(`/super-admin/clients/${clientNumber}/privileged-access/${grantId}/revoke/`, {
      method: "PATCH",
    });
  },
  async privilegedPatients(clientNumber: number) {
    return request<{ patients: Patient[] }>(`/super-admin/clients/${clientNumber}/privileged-patients/`);
  },
  async privilegedPatientDetail(clientNumber: number, patientId: string) {
    return request<PrivilegedPatientDetail>(`/super-admin/clients/${clientNumber}/privileged-patients/${patientId}/`);
  },
  async resendAdminInvitation(clientNumber: number) {
    return request<{ detail: string; email: string; invitationUrl: string }>(`/super-admin/clients/${clientNumber}/admin/resend-invite/`, { method: "POST" });
  },
  async managedClientUsers(clientNumber: number) {
    return request<{ client: ManagedClient; users: ManagedClientUser[] }>(`/super-admin/clients/${clientNumber}/users/`);
  },
  async createManagedClientUser(clientNumber: number, body: Record<string, unknown>) {
    return request<{ user: ManagedClientUser }>(`/super-admin/clients/${clientNumber}/users/`, {
      method: "POST",
      body,
    });
  },
  async allUsers(filters: Record<string, string> = {}) {
    const params = new URLSearchParams(filters);
    const search = params.toString() ? `?${params.toString()}` : "";
    return request<{ users: ManagedClientUser[]; total: number; page: number; pageSize: number }>(`/super-admin/users/${search}`);
  },
  async createUser(body: Record<string, unknown>) {
    return request<{ user: ManagedClientUser }>("/super-admin/users/", { method: "POST", body });
  },
  async updateUser(userId: string, body: Record<string, unknown>) {
    return request<{ user: ManagedClientUser }>(`/super-admin/users/${userId}/`, { method: "PATCH", body });
  },
  async userStatusAction(userId: string, action: string, reason = "") {
    return request<{ user: ManagedClientUser }>(`/super-admin/users/${userId}/status-action/`, {
      method: "POST",
      body: { action, reason },
    });
  },
  async userRevokeSessions(userId: string) {
    return request<{ user: ManagedClientUser; revokedCount: number }>(`/super-admin/users/${userId}/revoke-sessions/`, {
      method: "POST",
    });
  },
  async createUserLicense(userId: string, body: Record<string, unknown>) {
    return request<{ license: UserLicenseInfo }>(`/super-admin/users/${userId}/licenses/`, { method: "POST", body });
  },
  async updateUserLicense(userId: string, licenseId: string, body: Record<string, unknown>) {
    return request<{ license: UserLicenseInfo }>(`/super-admin/users/${userId}/licenses/${licenseId}/`, { method: "PATCH", body });
  },
  async deleteUserLicense(userId: string, licenseId: string) {
    return request<Record<string, never>>(`/super-admin/users/${userId}/licenses/${licenseId}/`, { method: "DELETE" });
  },
  async uploadUserLicenseDocument(userId: string, licenseId: string, file: File) {
    const token = await ensureCsrfToken();
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(`${API_ROOT}/super-admin/users/${userId}/licenses/${licenseId}/document/`, {
      method: "POST",
      credentials: "include",
      headers: { Accept: "application/json", "X-CSRFToken": token },
      body: formData,
    });
    return readJson<{ license: UserLicenseInfo }>(response);
  },
  userLicenseDocumentUrl(userId: string, licenseId: string) {
    return `${API_ROOT}/super-admin/users/${userId}/licenses/${licenseId}/document/`;
  },
  async verifyUserLicense(userId: string, licenseId: string, notes = "") {
    return request<{ license: UserLicenseInfo }>(`/super-admin/users/${userId}/licenses/${licenseId}/verify/`, {
      method: "POST",
      body: { notes },
    });
  },
  async schedule(month: string) {
    return request<ScheduleData>(`/schedule/?month=${encodeURIComponent(month)}`);
  },
  async moveAppointment(id: string, targetDate: string, targetStart = "") {
    const token = await ensureCsrfToken();
    const response = await fetch(`${API_ROOT}/appointments/${id}/move/`, {
      method: "POST",
      credentials: "include",
      headers: {
        Accept: "application/json",
        "X-CSRFToken": token,
        "X-Requested-With": "XMLHttpRequest",
      },
      body: new URLSearchParams({ target_date: targetDate, target_start: targetStart }),
    });
    return readJson<{ moved: boolean; detail: string }>(response);
  },
  async publicOrganization(slug: string) {
    return request<PublicOrganization>(`/public/organizations/${slug}/`);
  },
  async publicLocations(slug: string) {
    return request<{ locations: PublicLocation[] }>(`/public/organizations/${slug}/locations/`);
  },
  async publicAppointmentTypes(slug: string, locationId: string) {
    return request<{ appointmentTypes: PublicAppointmentType[] }>(
      `/public/organizations/${slug}/appointment-types/?location_id=${encodeURIComponent(locationId)}`,
    );
  },
  async publicProviders(slug: string, locationId: string, appointmentTypeId: string) {
    const params = new URLSearchParams({ location_id: locationId, appointment_type_id: appointmentTypeId });
    return request<{ providers: PublicProvider[] }>(`/public/organizations/${slug}/providers/?${params}`);
  },
  async publicAvailability(
    slug: string,
    locationId: string,
    appointmentTypeId: string,
    date: string,
    providerId = "",
  ) {
    const params = new URLSearchParams({ location_id: locationId, appointment_type_id: appointmentTypeId, date });
    if (providerId) params.set("provider_id", providerId);
    return request<PublicAvailability>(`/public/organizations/${slug}/availability/?${params}`);
  },
  async publicCreateBooking(body: {
    organizationSlug: string;
    locationId: string;
    appointmentTypeId: string;
    providerId: string;
    startDatetime: string;
    isNewPatient: boolean;
    patient: PublicBookingPatient;
    reasonForVisit?: string;
  }) {
    return request<PublicBookingConfirmation>("/public/bookings/", { method: "POST", body });
  },
  async cancelAppointment(id: string) {
    const token = await ensureCsrfToken();
    const response = await fetch(`${API_ROOT}/appointments/${id}/move/`, {
      method: "POST",
      credentials: "include",
      headers: { Accept: "application/json", "X-CSRFToken": token, "X-Requested-With": "XMLHttpRequest" },
      body: new URLSearchParams({ action: "cancel" }),
    });
    return readJson<{ cancelled: boolean; detail: string }>(response);
  },
};
