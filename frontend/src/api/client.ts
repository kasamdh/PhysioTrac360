import type {
  AppointmentType,
  Artifact,
  AuditEvent,
  ClinicLocation,
  DashboardData,
  Goal,
  GoalSuggestion,
  HomeProgram,
  HomeProgramSuggestion,
  OperationalReport,
  Patient,
  PatientDetail,
  PatientDocumentSummary,
  PatientWorkspace,
  ManagedClient,
  ManagedClientUser,
  PrivilegedAccessGrant,
  PrivilegedPatientDetail,
  PublicAvailability,
  PublicAppointmentType,
  PublicBookingConfirmation,
  PublicBookingPatient,
  PublicLocation,
  PublicOrganization,
  PublicProvider,
  Referral,
  ScheduleData,
  StaffOption,
  TimelineEvent,
  WorkspaceUser,
} from "./types";

const API_ROOT = import.meta.env.VITE_API_ROOT || "/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly fields: Record<string, string> = {},
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
    throw new ApiError(detail, response.status, payload.errors || {});
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
  options: { method?: "GET" | "POST" | "PATCH" | "DELETE"; body?: Record<string, unknown> } = {},
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
  async logout() {
    await request("/auth/logout/", { method: "POST" });
    csrfToken = null;
  },
  async changePassword(currentPassword: string, newPassword: string) {
    return request<{ detail: string }>("/auth/change-password/", {
      method: "POST",
      body: { currentPassword, newPassword },
    });
  },
  async me() {
    const payload = await request<{ user: WorkspaceUser }>("/auth/me/");
    return payload.user;
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
  async setOrganizationUserActive(userId: string, active: boolean) {
    return request<{ user: ManagedClientUser }>(`/users/${userId}/`, { method: "PATCH", body: { active } });
  },
  async archiveOrganizationUser(userId: string) {
    return request<{ user: ManagedClientUser }>(`/users/${userId}/`, { method: "DELETE" });
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
  async uploadPatientDocument(patientId: string, file: File, title: string, description: string) {
    const token = await ensureCsrfToken();
    const formData = new FormData();
    formData.append("file", file);
    formData.append("title", title);
    formData.append("description", description);
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
  async createIntake(patientId: string, body: Record<string, unknown>) {
    return request(`/patients/${patientId}/intakes/`, { method: "POST", body });
  },
  async createConsent(patientId: string, body: Record<string, unknown>) {
    return request(`/patients/${patientId}/consents/`, { method: "POST", body });
  },
  async createReferral(patientId: string, body: Record<string, unknown>) {
    return request<{ referral: Referral }>(`/patients/${patientId}/referrals/`, { method: "POST", body });
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
  async setUserActive(userId: string, active: boolean) {
    return request<{ user: ManagedClientUser }>(`/super-admin/users/${userId}/`, { method: "PATCH", body: { active } });
  },
  async archiveUser(userId: string) {
    return request<{ user: ManagedClientUser }>(`/super-admin/users/${userId}/`, { method: "DELETE" });
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
