// Types and calls for the backend API. The types mirror backend/app/models.py, the API
// contract: change both together and tell the backend owners.
// Every call is a relative /api/... URL; next.config.ts proxies it to FastAPI on localhost.

export const FIELD_TYPES = [
  "name", "address", "phone", "email", "relatives", "age", "birthdate",
  "employer", "ssn", "password", "financial", "health", "school",
] as const;
export type FieldType = (typeof FIELD_TYPES)[number];
export type Tier = "proven" | "likely" | "possible";
export type DateSource = "wayback" | "published_date" | "unknown";
export type TextSource = "extract" | "snippet";
export type PolicyCategory = "sale" | "sharing" | "advertising" | "affiliates" | "data_broker";
export type RemovalStatus = "removed" | "still_listed" | "unconfirmed";
// A data broker, or a public profile such as a sports results page.
export type SourceKind = "broker" | "public_profile";

// ---------- Stages 1 and 2: scan ----------

export interface ScanRequest {
  name: string;
  city: string;
  state: string;
  // Someone scanned before gets their newest saved scan back; true forces a fresh scan.
  refresh?: boolean;
}

export interface FieldFinding {
  field: FieldType;
  quote: string;
}

export type RiskLevel = "high" | "medium" | "low";

// What one kind of information on a listing means for the person (backend: explain.py).
export interface FieldInsight {
  field: FieldType;
  label: string;
  found: string[]; // the exact text the page shows, one entry per value
  why_it_matters: string;
  misuse: string[]; // what someone could do with it
  protect: string;
}

export interface Lead {
  company: string;
  tier: Tier;
  reasons: string[];
  source_urls: string[];
}

export interface Exposure {
  id: string;
  broker: string; // the site's name; for a public profile this is the site, not a broker
  broker_id: string | null;
  source_kind: SourceKind;
  url: string;
  other_urls?: string[]; // more pages on the same site, merged into this card
  title: string;
  found_via: "tavily" | "exa" | null;
  text_source: TextSource;
  fields: FieldFinding[];
  published_date: string | null;
  // Dates always carry their source. null with source "unknown" means no evidence, never a guess.
  public_by: string | null;
  public_by_source: DateSource;
  public_by_evidence_url: string | null;
  opt_out_url: string | null;
  leads: Lead[]; // strongest first
  summary: string;
  risk: RiskLevel | null;
  risk_reason: string;
  insights: FieldInsight[];
}

export interface ScanResponse {
  scan_id: string;
  exposures: Exposure[];
  errors: string[];
  saved_at: string | null; // ISO timestamp when this came from a saved scan; null for a fresh one
}

// ---------- Stages 3 and 4: accounts ----------

export interface BreachEvent {
  company_id: string;
  company: string;
  date: string | null;
  date_kind: "occurred" | "disclosed" | "unknown";
  data_types: FieldType[];
  source_url: string;
  source_kind: "ag_notice" | "news" | "web";
  summary: string;
}

export interface PolicyClause {
  category: PolicyCategory;
  quote: string; // verbatim from the policy
  explanation: string;
}

export interface PolicyResult {
  company_id: string;
  company: string;
  policy_url: string | null;
  clauses: PolicyClause[];
}

export interface AccountsResponse {
  breaches: BreachEvent[];
  policies: PolicyResult[];
  errors: string[];
}

// ---------- Stages 5 to 7 ----------

export interface LeadsResponse {
  exposures: Exposure[];
  errors: string[];
}

export interface Draft {
  kind: "broker" | "company" | "public_profile";
  recipient: string;
  send_to_url: string | null;
  send_to_email: string | null;
  subject: string;
  body: string;
  errors: string[];
}

export interface RescanItem {
  exposure_id: string;
  url: string;
  status: RemovalStatus;
}

export interface RescanResponse {
  results: RescanItem[];
  errors: string[];
}

export type AliasStatus = "active" | "disabled";

export interface Alias {
  alias: string;
  company: string;
  company_domains: string[]; // expected senders; mail from anywhere else is unexpected
  created_at: string;
  site: string; // the website this alias was made for, if any
  label: string;
  status: AliasStatus;
  disabled_at: string | null;
  note: string;
  demo: boolean; // from the demo data, not one the user made
  message_count: number; // in the mock inbox
  unexpected_count: number;
  last_message_at: string | null;
}

// Mock inbox only: nothing is received from the internet.
export interface AliasMessage {
  alias: string;
  from_address: string;
  from_domain: string;
  subject: string;
  date: string | null;
  expected: boolean;
  blocked: boolean; // arrived on or after the day the alias was disabled (a label, not a real rejection)
}

export type SenderKind = "data_broker" | "known_company" | "unknown";
export type AliasCategory = "legit" | "marketing" | "data_sharing" | "possible_phishing" | "unknown";

export interface SenderFact {
  domain: string;
  kind: SenderKind;
  name: string;
  count: number;
  first_seen: string | null;
}

// Rules set the facts and the tier; Gemini only explains them.
export interface AliasInvestigation {
  alias: string;
  company: string;
  tier: "proven" | null;
  facts: string[];
  senders: SenderFact[];
  days_to_first_unexpected: number | null;
  category: AliasCategory;
  explanation: string;
  explained_locally: boolean;
  errors: string[];
}

export interface AliasHit {
  alias: string;
  company: string;
  from_address: string;
  from_domain: string;
  subject: string;
  date: string | null;
  tier: "proven";
}

// ---------- Reference data, status, outbound log ----------

export interface Broker {
  id: string;
  name: string;
  domain: string;
  opt_out_url: string | null;
}

export interface Company {
  id: string;
  name: string;
  domains: string[];
  privacy_url: string | null;
  // The checked-in list is "list". Companies the user typed are custom: "typed" (a website),
  // "search" (found with one Exa company search) or "guessed" (the search failed; name + .com).
  custom?: boolean;
  domain_source?: "list" | "typed" | "search" | "guessed";
}

export interface Status {
  keys: Record<string, boolean>;
  ollama_running: boolean; // GEMINI_API_KEY is set (named before the switch to Gemini)
  ollama_model: string; // GEMINI_MODEL
  public?: boolean; // the public site (SITE_URL set): no Threat Monitor there yet
  model_pulled: boolean;
  database: boolean;
}

export interface OutboundEntry {
  id: number;
  time: string;
  service: string;
  purpose: string;
  local: boolean;
  method: string;
  url: string;
  headers: Record<string, string>;
  body: unknown;
  status: number | null;
  ms: number | null;
  error: string | null;
}

// ---------- Local accounts (backend: models.User; stored in the local Postgres) ----------

// "admin": the first account made, and anyone an admin promotes.
export type Role = "user" | "admin";

export interface User {
  email: string;
  id: string | null;
  role: Role;
  created_at: string | null;
}

// Shown to the admin once, to hand over in person (backend: models.ResetCode).
export interface ResetCode {
  email: string;
  code: string;
  expires_at: string;
}

// ---------- Threat monitor (backend: app/monitor/, models.py "Threat monitor") ----------
// Severity, confidence and involvement are separate answers: a critical breach can still be
// "unconfirmed" for this user. Rules in the backend set all three; Gemini only explains.

export type Severity = "critical" | "high" | "medium" | "low";
export type Confidence = "high" | "medium" | "low";
export type Involvement = "confirmed" | "not_found" | "unconfirmed";
export type IncidentSourceKind = "hibp" | "official" | "ag_notice" | "news" | "web";
export type EmailCheckStatus = "never" | "ok" | "not_configured" | "rate_limited" | "error";

export interface MonitoredCompany {
  id: string;
  name: string;
  domains: string[];
  added_at: string;
  last_checked: string | null; // last match against HIBP's breach list
  last_news_check: string | null;
  incidents: number;
  messages: string[];
}

export interface MonitoredEmail {
  id: string;
  display: string; // the address until verified; then a masked form
  added_at: string;
  verified: boolean;
  verified_at: string | null;
  code_sent_at: string | null;
  code_expires_at: string | null;
  check_status: EmailCheckStatus;
  check_message: string;
  last_checked: string | null;
  breaches_found: number;
}

export interface IncidentDate {
  kind: "occurred" | "disclosed" | "added_to_hibp";
  date: string;
  source: string;
  source_url: string | null;
}

export interface IncidentSource {
  url: string;
  kind: IncidentSourceKind;
  label: string;
  official: boolean;
}

export interface SecurityAction {
  id: string;
  text: string;
  why: string;
  link: string | null;
  done: boolean;
  done_at: string | null;
}

export interface ThreatAnalysis {
  summary: string;
  impact: string;
  guidance: string; // "" when the sources give no advice
  uncertainty: string;
  severity_explanation: string;
  removed_sentences: number;
  analyzed_at: string;
  model: string;
  stale: boolean;
}

export interface RelatedListing {
  exposure_id: string;
  site: string;
  url: string;
  shared_fields: FieldType[];
  lead_tier: Tier | null;
  reason: string;
}

export interface Incident {
  id: string;
  company_id: string | null;
  company: string;
  title: string;
  domain: string | null;
  description: string;
  data_classes: string[];
  data_types: FieldType[];
  pwn_count: number | null;
  dates: IncidentDate[];
  sources: IncidentSource[];
  threat: string;
  risks: string[];
  severity: Severity;
  severity_reasons: string[];
  confidence: Confidence;
  confidence_reason: string;
  involvement: Involvement;
  involvement_reason: string;
  flags: string[];
  actions: SecurityAction[];
  analysis: ThreatAnalysis | null;
  related_listings: RelatedListing[];
  first_seen: string;
  new: boolean;
  steps_done: boolean; // every step marked done by the user; never means "secure"
}

export interface MonitorSummary {
  monitored_companies: number;
  verified_emails: number;
  email_breaches: number;
  company_breaches: number;
  open_alerts: number;
  new_alerts: number;
  actions_done: number;
  actions_total: number;
  last_check: string | null;
}

export interface MonitorEvent {
  id: string;
  time: string;
  kind: "refresh" | "new_incident" | "confirmed" | "company" | "email" | "error" | "schedule";
  message: string;
  incident_id: string | null;
}

export interface MonitorSchedule {
  enabled: boolean;
  interval_hours: 6 | 12 | 24 | 168;
  include_news: boolean;
  last_run: string | null;
  next_run: string | null;
}

export interface RefreshStatus {
  running: boolean;
  trigger: "manual" | "scheduled" | null;
  started_at: string | null;
  finished_at: string | null;
  step: string;
  done: number;
  total: number;
  include_news: boolean;
  errors: string[];
  new_incidents: number;
}

export interface MonitorConfig {
  hibp_email_key: boolean;
  smtp: boolean;
  news_search: boolean;
  local_llm: boolean;
  local_llm_model: string;
}

export interface MonitorDashboard {
  summary: MonitorSummary;
  companies: MonitoredCompany[];
  emails: MonitoredEmail[];
  incidents: Incident[];
  events: MonitorEvent[];
  schedule: MonitorSchedule;
  refresh: RefreshStatus;
  config: MonitorConfig;
  scan_loaded: boolean;
}

// ---------- Digital footprint (backend: models.TrackedCompany and friends) ----------
// The user's own records, in the local Postgres for the signed-in account. Never sent anywhere:
// drafts are local templates, and Dossier doesn't send requests or change company settings.

export type RequestKind = "access" | "deletion";
export type RequestStatus =
  | "draft"
  | "ready_to_send"
  | "sent"
  | "response_received"
  | "completed"
  | "unable_to_complete";
export type LawBasis = "none" | "gdpr" | "ccpa"; // a law is named in a draft only if the user picks one
export type ControlState = "on" | "off" | "unknown";

export interface PrivacyControl {
  name: string;
  state: ControlState;
  checked_on: string | null; // YYYY-MM-DD the user checked; null means they didn't record one
  note: string;
}

export interface TrackedCompanyInput {
  name: string;
  website: string;
  account_label: string; // how the company knows the user: email, username or account number
  notes: string;
  controls: PrivacyControl[];
}

export interface RequestEvent {
  status: RequestStatus;
  happened_on: string; // YYYY-MM-DD, as the user recorded it
  note: string;
  recorded_at: string; // when Dossier saved this step
}

export interface DataRequest {
  id: string;
  kind: RequestKind;
  law: LawBasis;
  subject: string;
  body: string;
  status: RequestStatus;
  created_at: string;
  updated_at: string;
  history: RequestEvent[]; // oldest first
  next_statuses: RequestStatus[]; // what the user can record next
  editable: boolean; // false once marked sent: the text stays as it was sent
}

export interface TrackedCompany extends TrackedCompanyInput {
  id: string;
  created_at: string;
  updated_at: string;
  requests: DataRequest[]; // newest first
}

// ---------- Calls ----------

// FastAPI errors look like {detail: "message"}, or {detail: [{msg}, ...]} for validation errors.
function errorMessage(data: unknown, status: number): string {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = (detail as { msg?: unknown }[])
      .map((d) => (typeof d.msg === "string" ? d.msg.replace(/^Value error, /, "") : ""))
      .filter(Boolean);
    if (messages.length > 0) return messages.join(" ");
  }
  if (data === null && status >= 500) {
    const local = typeof window === "undefined" || ["localhost", "127.0.0.1"].includes(window.location.hostname);
    return local
      ? "The backend didn't answer. Is it running? (cd backend && uvicorn app.main:app --reload)"
      : // The public site: the backend was asleep or slow, or Vercel stopped waiting after 2 minutes.
        "The server didn't answer in time. Try again in a minute: a scan that was cut off keeps running, and scanning again loads it.";
  }
  return `Request failed (${status}).`;
}

async function request<T>(
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data: unknown = await res.json().catch(() => null);
  if (!res.ok) throw Object.assign(new Error(errorMessage(data, res.status)), { status: res.status });
  return data as T;
}

export const api = {
  status: () => request<Status>("GET", "/api/status"),
  brokers: () => request<Broker[]>("GET", "/api/brokers"),
  companies: () => request<Company[]>("GET", "/api/companies"),
  // Any company: a name ("Tinder") is matched to its website with one logged search; a website is used as typed.
  addCompany: (name: string) => request<Company>("POST", "/api/companies", { name }),
  scan: (body: ScanRequest) => request<ScanResponse>("POST", "/api/scan", body),
  latestScan: () => request<ScanResponse>("GET", "/api/scans/latest"),
  accounts: (companies: string[]) => request<AccountsResponse>("POST", "/api/accounts", { companies }),
  leads: () => request<LeadsResponse>("GET", "/api/leads"),
  optOut: (target: { exposure_id: string } | { company: string }) =>
    request<Draft>("POST", "/api/optout", target),
  rescan: () => request<RescanResponse>("POST", "/api/rescan"),
  aliases: () => request<Alias[]>("GET", "/api/aliases"),
  newAlias: (company: string) => request<Alias>("POST", "/api/aliases", { company }),
  newSiteAlias: (site: string, label = "") => request<Alias>("POST", "/api/aliases", { site, label }),
  updateAlias: (alias: string, change: { status?: AliasStatus; note?: string }) =>
    request<Alias>("PATCH", `/api/aliases/${encodeURIComponent(alias)}`, change),
  aliasMessages: (alias: string) =>
    request<AliasMessage[]>("GET", `/api/aliases/${encodeURIComponent(alias)}/messages`),
  investigateAlias: (alias: string) =>
    request<AliasInvestigation>("POST", `/api/aliases/${encodeURIComponent(alias)}/investigate`),
  checkInbox: () => request<AliasHit[]>("GET", "/api/inbox/check"),
  outboundLog: (includeLocal: boolean) =>
    request<OutboundEntry[]>("GET", `/api/outbound-log?include_local=${includeLocal}`),
  clearOutboundLog: () => request<{ cleared: boolean }>("DELETE", "/api/outbound-log"),
  signup: (body: { email: string; password: string }) =>
    request<User>("POST", "/api/auth/signup", body),
  login: (body: { email: string; password: string }) => request<User>("POST", "/api/auth/login", body),
  logout: () => request<{ ok: boolean }>("POST", "/api/auth/logout"),
  me: () => request<User>("GET", "/api/auth/me"),
  changePassword: (body: { current_password: string; new_password: string }) =>
    request<{ changed: boolean }>("POST", "/api/auth/password", body),
  resetPassword: (body: { email: string; code: string; new_password: string }) =>
    request<User>("POST", "/api/auth/reset", body),
  // Admins only (403 otherwise).
  users: () => request<User[]>("GET", "/api/admin/users"),
  setRole: (userId: string, role: Role) => request<User>("PATCH", `/api/admin/users/${encodeURIComponent(userId)}`, { role }),
  deleteUser: (userId: string) => request<{ deleted: boolean }>("DELETE", `/api/admin/users/${encodeURIComponent(userId)}`),
  resetCode: (userId: string) => request<ResetCode>("POST", `/api/admin/users/${encodeURIComponent(userId)}/reset-code`),

  // Threat monitor. Email addresses and codes go in POST bodies, never URLs.
  monitor: {
    dashboard: () => request<MonitorDashboard>("GET", "/api/monitor"),
    refreshStatus: () => request<RefreshStatus>("GET", "/api/monitor/refresh"),
    refresh: (body: { company_id?: string; include_news?: boolean }) =>
      request<RefreshStatus>("POST", "/api/monitor/refresh", body),
    addCompany: (name: string) => request<MonitoredCompany>("POST", "/api/monitor/companies", { name }),
    removeCompany: (id: string) =>
      request<{ removed: boolean }>("DELETE", `/api/monitor/companies/${encodeURIComponent(id)}`),
    addEmail: (address: string) => request<MonitoredEmail>("POST", "/api/monitor/emails", { address }),
    sendCode: (id: string) => request<MonitoredEmail>("POST", `/api/monitor/emails/${encodeURIComponent(id)}/code`),
    verifyEmail: (id: string, code: string) =>
      request<MonitoredEmail>("POST", `/api/monitor/emails/${encodeURIComponent(id)}/verify`, { code }),
    removeEmail: (id: string) =>
      request<{ removed: boolean }>("DELETE", `/api/monitor/emails/${encodeURIComponent(id)}`),
    setAction: (incidentId: string, actionId: string, done: boolean) =>
      request<Incident>(
        "POST",
        `/api/monitor/incidents/${encodeURIComponent(incidentId)}/actions/${encodeURIComponent(actionId)}`,
        { done },
      ),
    analyze: (incidentId: string) =>
      request<Incident>("POST", `/api/monitor/incidents/${encodeURIComponent(incidentId)}/analyze`),
    markSeen: (incidentIds?: string[]) =>
      request<{ marked: number }>("POST", "/api/monitor/seen", { incident_ids: incidentIds ?? null }),
    setSchedule: (body: Pick<MonitorSchedule, "enabled" | "interval_hours" | "include_news">) =>
      request<MonitorSchedule>("POST", "/api/monitor/schedule", body),
  },
  // Digital footprint. Ids are random UUIDs; everything personal goes in the request body.
  footprint: () => request<TrackedCompany[]>("GET", "/api/footprint"),
  trackCompany: (body: TrackedCompanyInput) => request<TrackedCompany>("POST", "/api/footprint", body),
  editTrackedCompany: (id: string, body: TrackedCompanyInput) =>
    request<TrackedCompany>("PUT", `/api/footprint/${encodeURIComponent(id)}`, body),
  removeTrackedCompany: (id: string) =>
    request<{ deleted: boolean }>("DELETE", `/api/footprint/${encodeURIComponent(id)}`),
  draftDataRequest: (companyId: string, body: { kind: RequestKind; law: LawBasis }) =>
    request<TrackedCompany>("POST", `/api/footprint/${encodeURIComponent(companyId)}/requests`, body),
  editDataRequest: (requestId: string, body: { subject: string; body: string }) =>
    request<TrackedCompany>("PATCH", `/api/footprint/requests/${encodeURIComponent(requestId)}`, body),
  recordRequestUpdate: (requestId: string, body: { status: RequestStatus; happened_on: string; note: string }) =>
    request<TrackedCompany>("POST", `/api/footprint/requests/${encodeURIComponent(requestId)}/updates`, body),
  undoRequestUpdate: (requestId: string) =>
    request<TrackedCompany>("DELETE", `/api/footprint/requests/${encodeURIComponent(requestId)}/updates/last`),
  removeDataRequest: (requestId: string) =>
    request<TrackedCompany>("DELETE", `/api/footprint/requests/${encodeURIComponent(requestId)}`),
};
