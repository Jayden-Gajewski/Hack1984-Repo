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
  consent: boolean;
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

export interface Alias {
  alias: string;
  company: string;
  company_domains: string[];
  created_at: string;
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
  ollama_running: boolean;
  ollama_model: string;
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

export interface User {
  email: string;
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
    return "The backend didn't answer. Is it running? (cd backend && uvicorn app.main:app --reload)";
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
  checkInbox: () => request<AliasHit[]>("GET", "/api/inbox/check"),
  outboundLog: (includeLocal: boolean) =>
    request<OutboundEntry[]>("GET", `/api/outbound-log?include_local=${includeLocal}`),
  clearOutboundLog: () => request<{ cleared: boolean }>("DELETE", "/api/outbound-log"),
  signup: (body: { email: string; password: string }) =>
    request<User>("POST", "/api/auth/signup", body),
  login: (body: { email: string; password: string }) => request<User>("POST", "/api/auth/login", body),
  logout: () => request<{ ok: boolean }>("POST", "/api/auth/logout"),
  me: () => request<User>("GET", "/api/auth/me"),
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
