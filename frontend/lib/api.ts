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
  user_id: number | null;
}

// ---------- Accounts ----------

export type Role = "user" | "admin";

export interface User {
  id: number;
  username: string;
  role: Role;
  created_at: string;
}

export interface Credentials {
  username: string;
  password: string;
}

export interface PasswordReset {
  username: string;
  code: string;
  new_password: string;
}

// Shown to the admin once, to hand to the user in person.
export interface ResetCode {
  username: string;
  code: string;
  expires_at: string;
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

async function request<T>(method: "GET" | "POST" | "PATCH" | "DELETE", path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new Error(errorMessage(data, res.status));
  return data as T;
}

export const api = {
  status: () => request<Status>("GET", "/api/status"),
  brokers: () => request<Broker[]>("GET", "/api/brokers"),
  companies: () => request<Company[]>("GET", "/api/companies"),
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
  // The login cookie is httpOnly and set by the backend; the browser sends it on its own.
  me: () => request<User>("GET", "/api/auth/me"),
  signup: (creds: Credentials) => request<User>("POST", "/api/auth/signup", creds),
  login: (creds: Credentials) => request<User>("POST", "/api/auth/login", creds),
  logout: () => request<{ logged_out: boolean }>("POST", "/api/auth/logout"),
  changePassword: (current_password: string, new_password: string) =>
    request<{ changed: boolean }>("POST", "/api/auth/password", { current_password, new_password }),
  resetPassword: (body: PasswordReset) => request<User>("POST", "/api/auth/reset", body),
  resetCode: (id: number) => request<ResetCode>("POST", `/api/admin/users/${id}/reset-code`),
  users: () => request<User[]>("GET", "/api/admin/users"),
  setRole: (id: number, role: Role) => request<User>("PATCH", `/api/admin/users/${id}`, { role }),
  deleteUser: (id: number) => request<{ deleted: boolean }>("DELETE", `/api/admin/users/${id}`),
};
