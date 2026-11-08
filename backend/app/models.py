"""Pydantic models: the API contract with the frontend (frontend/lib/api.ts mirrors them).

Shared file. Keep changes additive (new optional fields are safe), call them out in the
commit message, and tell the UI owner before renaming or removing anything.

Every date carries a source label. A missing date is null with source "unknown", never a guess.
"""

import re
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.outbound import assert_minimal_query

# One vocabulary for listing fields (Stage 1) and breach data types (Stage 3), so Stage 5
# can compare them directly. The LLM's answers are filtered to these values.
FieldType = Literal[
    "name", "address", "phone", "email", "relatives", "age", "birthdate",
    "employer", "ssn", "password", "financial", "health", "school",
]
FIELD_TYPES: tuple[str, ...] = get_args(FieldType)

Tier = Literal["proven", "likely", "possible"]
TIERS: tuple[str, ...] = get_args(Tier)  # strongest first

DateSource = Literal["wayback", "published_date", "unknown"]
TextSource = Literal["extract", "snippet"]
PolicyCategory = Literal["sale", "sharing", "advertising", "affiliates", "data_broker"]
RemovalStatus = Literal["removed", "still_listed", "unconfirmed"]
# Where an exposure was found: a data broker (data/brokers.json, or an unlisted people-search
# site), or a public profile such as a sports results page (data/public_profiles.json).
SourceKind = Literal["broker", "public_profile"]


# ---------- Stages 1 and 2: scan ----------


class ScanRequest(BaseModel):
    """The only personal data the app takes: name and city/state. Nothing else."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=100)
    city: str = Field(min_length=2, max_length=100)
    state: str = Field(min_length=2, max_length=2)
    consent: bool = False
    # A person scanned before gets their newest saved scan back from local Postgres, with no
    # searching. refresh=True skips that and runs a fresh scan.
    refresh: bool = False

    @field_validator("state")
    @classmethod
    def _upper_state(cls, v: str) -> str:
        if not v.isascii() or not v.isalpha():
            raise ValueError("State must be a two-letter code, e.g. IL.")
        return v.upper()

    @field_validator("name", "city")
    @classmethod
    def _no_digits(cls, v: str) -> str:
        # Digits mean a street address, ZIP code or similar, which we never send out.
        assert_minimal_query(v)  # first, so a phone or email gets its specific message
        if any(ch.isdigit() for ch in v):
            raise ValueError("Use letters only: no street address, ZIP code or numbers.")
        return v

    @model_validator(mode="after")
    def _minimal_query(self) -> "ScanRequest":
        # Reject a phone number or email typed into a field before anything is searched.
        assert_minimal_query(f"{self.name} {self.city} {self.state}")
        return self


class FieldFinding(BaseModel):
    field: FieldType
    quote: str  # short quote copied from the page, so the UI can show the evidence


RiskLevel = Literal["high", "medium", "low"]


class FieldInsight(BaseModel):
    """What one kind of information on a listing means for the person (set by explain.py)."""

    field: FieldType
    label: str  # "Home address"
    found: list[str]  # the exact text the page shows, one entry per value
    why_it_matters: str
    misuse: list[str]  # what someone could do with it
    protect: str  # one concrete thing the person can do about it


class Lead(BaseModel):
    """A likely source for one exposure. Never call it "who leaked it"."""

    company: str
    tier: Tier
    reasons: list[str]  # human-readable sentences that cite dates and their sources
    source_urls: list[str] = []


class Exposure(BaseModel):
    id: str
    broker: str  # the site's name; for a public profile this is the site, not a broker
    broker_id: str | None = None
    source_kind: SourceKind = "broker"
    url: str
    title: str = ""
    found_via: Literal["tavily", "exa"] | None = None
    text_source: TextSource = "snippet"
    fields: list[FieldFinding] = []
    published_date: str | None = None  # from the search API, if it had one
    public_by: str | None = None  # YYYY-MM-DD, set by Stage 2
    public_by_source: DateSource = "unknown"
    public_by_evidence_url: str | None = None  # Wayback snapshot link when source is "wayback"
    opt_out_url: str | None = None
    leads: list[Lead] = []  # set by Stage 5, strongest first
    # Set by explain.py after Stage 2: a plain-English write-up of what this listing shows.
    summary: str = ""
    risk: RiskLevel | None = None
    risk_reason: str = ""
    insights: list[FieldInsight] = []


class ScanResponse(BaseModel):
    scan_id: str
    exposures: list[Exposure]
    errors: list[str]
    saved_at: str | None = None  # ISO timestamp when this came from a saved scan; null for a fresh one


# ---------- Stages 3 and 4: accounts ----------


class CompanyRequest(BaseModel):
    """A company typed into the account picker: a name ("Tinder") or a website ("tinder.com").
    It's searched for, so it gets the same guard as every query: no phone, email or other contact detail."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=80)

    @field_validator("name")
    @classmethod
    def _company_name_only(cls, v: str) -> str:
        assert_minimal_query(v)
        return v


class AccountsRequest(BaseModel):
    companies: list[str]  # ids from GET /api/companies: the checked-in list plus companies the user added


class BreachEvent(BaseModel):
    company_id: str
    company: str
    date: str | None = None  # YYYY-MM-DD, YYYY-MM or YYYY; null means unknown
    date_kind: Literal["occurred", "disclosed", "unknown"] = "unknown"
    data_types: list[FieldType] = []
    source_url: str
    source_kind: Literal["ag_notice", "news", "web"] = "web"  # prefer AG notices
    summary: str = ""


class PolicyClause(BaseModel):
    category: PolicyCategory
    quote: str  # verbatim from the policy: this is the "they sold it" evidence
    explanation: str  # one plain-English line


class PolicyResult(BaseModel):
    company_id: str
    company: str
    policy_url: str | None = None
    clauses: list[PolicyClause] = []


class AccountsResponse(BaseModel):
    breaches: list[BreachEvent]
    policies: list[PolicyResult]
    errors: list[str]


# ---------- Stage 5: leads ----------


class LeadsResponse(BaseModel):
    exposures: list[Exposure]
    errors: list[str]


# ---------- Stage 6: resolve ----------


class OptOutRequest(BaseModel):
    exposure_id: str | None = None
    company: str | None = None  # company id from GET /api/companies

    @model_validator(mode="after")
    def _exactly_one(self) -> "OptOutRequest":
        if (self.exposure_id is None) == (self.company is None):
            raise ValueError("Send exactly one of exposure_id or company.")
        return self


class Draft(BaseModel):
    kind: Literal["broker", "company", "public_profile"]
    recipient: str  # broker, site or company name
    send_to_url: str | None = None  # opt-out page or privacy request form
    send_to_email: str | None = None  # privacy@ style address, if one was found
    subject: str
    body: str
    errors: list[str] = []  # e.g. "privacy contact not found"


class RescanItem(BaseModel):
    exposure_id: str
    url: str
    status: RemovalStatus


class RescanResponse(BaseModel):
    results: list[RescanItem]
    errors: list[str]


# ---------- Stage 7: aliases ----------


class AliasRequest(BaseModel):
    company: str  # company id from GET /api/companies, or a name for a demo company


class Alias(BaseModel):
    alias: str
    company: str
    company_domains: list[str]
    created_at: str


class AliasHit(BaseModel):
    """Mail to a company-only alias from someone else. Always tier "proven"."""

    alias: str
    company: str
    from_address: str
    from_domain: str
    subject: str
    date: str | None = None
    tier: Literal["proven"] = "proven"


# ---------- Status ----------


class StatusResponse(BaseModel):
    keys: dict[str, bool]  # which API keys are set, never their values
    ollama_running: bool
    ollama_model: str
    model_pulled: bool
    database: bool


# ---------- Local accounts (stored in the local Postgres only) ----------


class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        local, _, domain = v.partition("@")
        if not local or "." not in domain or " " in v:
            raise ValueError("Enter a valid email address.")
        return v

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Use at least 8 characters for your password.")
        return v


class User(BaseModel):
    email: str


# ---------- Threat monitor (app/monitor/) ----------
# Severity, confidence and involvement are separate on purpose: a serious breach can be
# "critical" while the user's involvement is still "unconfirmed". Rules in code set all three;
# the local LLM only explains them.

Severity = Literal["critical", "high", "medium", "low"]
SEVERITIES: tuple[str, ...] = get_args(Severity)  # strongest first
Confidence = Literal["high", "medium", "low"]  # how well the incident itself is evidenced
# "confirmed": a verified email's hash matched this breach in HIBP. "not_found": every verified
# email was checked and this breach didn't list it. "unconfirmed": nobody could check.
Involvement = Literal["confirmed", "not_found", "unconfirmed"]
IncidentSourceKind = Literal["hibp", "official", "ag_notice", "news", "web"]
EmailCheckStatus = Literal["never", "ok", "not_configured", "rate_limited", "error"]

_EMAIL_FORMAT = r"^[^\s@<>\"']+@[^\s@<>\"']+\.[a-z]{2,}$"


class EmailRequest(BaseModel):
    """An address the user wants monitored. It's only ever sent to the user's own SMTP server
    (for the ownership code); HIBP gets the first 6 characters of its SHA-1 hash."""

    model_config = ConfigDict(str_strip_whitespace=True)

    address: str = Field(min_length=3, max_length=254)

    @field_validator("address")
    @classmethod
    def _address(cls, v: str) -> str:
        v = v.lower()
        if not re.match(_EMAIL_FORMAT, v):
            raise ValueError("Enter a valid email address.")
        return v


class VerifyCodeRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(pattern=r"^\d{6}$")


class RefreshRequest(BaseModel):
    company_id: str | None = None  # one monitored company; None checks everything
    include_news: bool = False  # also search news and official notices (Tavily/Exa credits, local LLM time)


class ActionUpdate(BaseModel):
    done: bool


class SeenRequest(BaseModel):
    incident_ids: list[str] | None = None  # None marks every incident as seen


class MonitorSchedule(BaseModel):
    """Local scheduled checks. They run inside the backend process, so only while it's running."""

    enabled: bool = False
    interval_hours: Literal[6, 12, 24, 168] = 24
    include_news: bool = False
    last_run: str | None = None  # read-only
    next_run: str | None = None  # read-only


class MonitoredCompany(BaseModel):
    id: str  # company id from app.companies
    name: str
    domains: list[str]
    added_at: str
    last_checked: str | None = None  # last match against HIBP's breach list
    last_news_check: str | None = None  # last news and official-notice search
    incidents: int = 0
    messages: list[str] = []  # problems from the last check


class MonitoredEmail(BaseModel):
    id: str
    display: str  # the address until it's verified; after that only a masked form is kept
    added_at: str
    verified: bool = False
    verified_at: str | None = None
    code_sent_at: str | None = None
    code_expires_at: str | None = None
    check_status: EmailCheckStatus = "never"
    check_message: str = ""
    last_checked: str | None = None
    breaches_found: int = 0


class IncidentDate(BaseModel):
    kind: Literal["occurred", "disclosed", "added_to_hibp"]
    date: str  # YYYY-MM-DD, YYYY-MM or YYYY
    source: str  # where the date comes from, shown next to it
    source_url: str | None = None


class IncidentSource(BaseModel):
    url: str
    kind: IncidentSourceKind
    label: str
    official: bool = False  # the company's own notice, a government notice, or HIBP's verified entry


class SecurityAction(BaseModel):
    id: str
    text: str
    why: str
    link: str | None = None
    done: bool = False
    done_at: str | None = None


class ThreatAnalysis(BaseModel):
    """The local LLM's plain-English explanation, after evidence checks in code."""

    summary: str
    impact: str
    guidance: str  # empty when the sources contain no official guidance
    uncertainty: str
    severity_explanation: str
    removed_sentences: int = 0  # sentences dropped by the evidence checks
    analyzed_at: str
    model: str
    stale: bool = False  # the incident's facts changed since this was written


class RelatedListing(BaseModel):
    """A listing from the current exposure scan that shows data this breach reportedly exposed.
    Overlap is not proof that the breach caused the listing."""

    exposure_id: str
    site: str
    url: str
    shared_fields: list[FieldType]
    lead_tier: Tier | None = None  # Stage 5's tier for this company on that listing, if any
    reason: str


class Incident(BaseModel):
    id: str
    company_id: str | None = None  # the monitored company, or None for a breach found by email only
    company: str
    title: str
    domain: str | None = None
    description: str = ""  # plain text from the source (HIBP's description or the news summary)
    data_classes: list[str] = []  # as reported (HIBP's names, or Stage 3's types)
    data_types: list[FieldType] = []  # the same, in the listing vocabulary
    pwn_count: int | None = None
    dates: list[IncidentDate] = []
    sources: list[IncidentSource] = []
    threat: str
    risks: list[str] = []
    severity: Severity
    severity_reasons: list[str] = []
    confidence: Confidence
    confidence_reason: str
    involvement: Involvement
    involvement_reason: str
    flags: list[str] = []
    actions: list[SecurityAction] = []
    analysis: ThreatAnalysis | None = None
    related_listings: list[RelatedListing] = []
    first_seen: str
    new: bool = False
    # Every recommended step is marked done by the user. It never means the account is secure.
    steps_done: bool = False


class MonitorSummary(BaseModel):
    monitored_companies: int
    verified_emails: int
    email_breaches: int  # incidents a verified email is confirmed in
    company_breaches: int  # incidents at monitored companies, confirmed or not
    open_alerts: int  # incidents with steps still open
    new_alerts: int
    actions_done: int
    actions_total: int
    last_check: str | None = None


class MonitorEvent(BaseModel):
    id: str
    time: str
    kind: Literal["refresh", "new_incident", "confirmed", "company", "email", "error", "schedule"]
    message: str
    incident_id: str | None = None


class RefreshStatus(BaseModel):
    running: bool = False
    trigger: Literal["manual", "scheduled"] | None = None
    started_at: str | None = None
    finished_at: str | None = None
    step: str = ""
    done: int = 0
    total: int = 0
    include_news: bool = False
    errors: list[str] = []
    new_incidents: int = 0


class MonitorConfig(BaseModel):
    """What the monitor can do with this laptop's .env. Never key values."""

    hibp_email_key: bool  # HIBP_API_KEY (hashed email search; Pro or High RPM plan)
    smtp: bool  # SMTP_HOST and SMTP_FROM, for ownership codes
    news_search: bool  # TAVILY_API_KEY or EXA_API_KEY
    local_llm: bool  # Ollama running with OLLAMA_MODEL pulled
    local_llm_model: str


class MonitorDashboard(BaseModel):
    summary: MonitorSummary
    companies: list[MonitoredCompany]
    emails: list[MonitoredEmail]
    incidents: list[Incident]
    events: list[MonitorEvent]
    schedule: MonitorSchedule
    refresh: RefreshStatus
    config: MonitorConfig
    scan_loaded: bool  # an exposure scan is loaded, so related listings can be shown
