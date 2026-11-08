"""Pydantic models: the API contract with the frontend (frontend/lib/api.ts mirrors them).

Shared file. Keep changes additive (new optional fields are safe), call them out in the
commit message, and tell the UI owner before renaming or removing anything.

Every date carries a source label. A missing date is null with source "unknown", never a guess.
"""

import re
from datetime import date
from typing import Literal, get_args
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app import footprint
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
    # More pages about this person on the same site, merged into this card (Stage 1).
    other_urls: list[str] = []
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


_SITE_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def normalize_site(value: str) -> str:
    """A hostname from "shop.example", "www.shop.example" or a pasted signup URL. Only the
    hostname is kept: a URL's path and query can carry personal data."""
    text = value.strip().lower()
    host = (urlsplit(text if "://" in text else f"https://{text}").hostname or "").removeprefix("www.")
    if not _SITE_RE.match(host):
        raise ValueError("Enter a website like shop.example.")
    return host


class AliasRequest(BaseModel):
    # One of these: a company id from GET /api/companies (or a demo company's name), or the
    # website you're signing up on. A site gets its own alias, so every signup can have one.
    company: str | None = None
    site: str | None = None
    label: str = Field(default="", max_length=80)  # your own note, e.g. "newsletter signup"

    @field_validator("site")
    @classmethod
    def _site(cls, value: str | None) -> str | None:
        return normalize_site(value) if value and value.strip() else None

    @model_validator(mode="after")
    def _one_target(self) -> "AliasRequest":
        if not (self.company and self.company.strip()) and not self.site:
            raise ValueError("Pick a company or enter the website you're signing up on.")
        return self


AliasStatus = Literal["active", "disabled"]


class Alias(BaseModel):
    alias: str
    company: str
    company_domains: list[str]  # expected senders: mail from anywhere else is unexpected
    created_at: str
    # Identity manager (all additive; defaults keep older clients working).
    site: str = ""  # the website this alias was made for, if any
    label: str = ""
    status: AliasStatus = "active"
    disabled_at: str | None = None  # YYYY-MM-DD
    note: str = ""
    demo: bool = False  # from data/mock_aliases.json, not one you made
    message_count: int = 0  # in the mock inbox
    unexpected_count: int = 0  # from outside company_domains
    last_message_at: str | None = None


class AliasUpdate(BaseModel):
    status: AliasStatus | None = None
    note: str | None = Field(default=None, max_length=280)


class AliasMessage(BaseModel):
    """One message to an alias. Mock inbox only: nothing is received from the internet."""

    alias: str
    from_address: str
    from_domain: str
    subject: str
    date: str | None = None
    expected: bool  # sender is one of the alias's company_domains (or a subdomain)
    # The alias was disabled on or before this date. Mock inbox: a label, not a real rejection.
    blocked: bool = False


SenderKind = Literal["data_broker", "known_company", "unknown"]
AliasCategory = Literal["legit", "marketing", "data_sharing", "possible_phishing", "unknown"]


class SenderFact(BaseModel):
    """What the app knows about one unexpected sender, from checked-in lists only."""

    domain: str
    kind: SenderKind
    name: str = ""  # the broker's or company's name when kind isn't "unknown"
    count: int
    first_seen: str | None = None  # YYYY-MM-DD, from the message date


class AliasInvestigation(BaseModel):
    """Rules decide the facts and the tier; the local LLM only explains them."""

    alias: str
    company: str
    tier: Literal["proven"] | None = None  # proven when anyone outside company_domains wrote
    facts: list[str]  # plain sentences built in code, each citing its date
    senders: list[SenderFact] = []
    days_to_first_unexpected: int | None = None  # from the alias's creation date
    category: AliasCategory = "unknown"  # the local LLM's guess, checked against the enum
    explanation: str = ""  # local LLM, checked sentence by sentence; empty if nothing passed
    explained_locally: bool = False  # true when the explanation came from the local LLM
    errors: list[str] = []


class AliasHit(BaseModel):
    """Mail to a company-only alias from someone else. Always tier "proven"."""

    alias: str
    company: str
    from_address: str
    from_domain: str
    subject: str
    date: str | None = None
    tier: Literal["proven"] = "proven"


# ---------- Browser extension: privacy check for the site you're visiting ----------

# What a privacy policy says the company collects (app/site_policy.py CATEGORIES).
DataCategory = Literal[
    "contact", "identifiers", "tracking", "precise_location", "location", "activity", "purchases",
    "financial", "government_id", "health", "biometric", "sensitive_traits", "contacts",
    "media", "demographics", "inferences", "from_others",
]
# Kinds of personal data a page's form fields ask for, as content.js classifies them from what
# the page says about each field. Never what's typed in them.
FormField = Literal[
    "email", "phone", "address", "birthdate", "password", "card", "bank_account", "ssn", "government_id",
]
FORM_FIELDS: tuple[str, ...] = get_args(FormField)
TrackerCategory = Literal["session_recording", "data_broker", "advertising", "social", "analytics", "tag_manager"]
_HOSTNAME = re.compile(r"(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}")


class SitePolicyRequest(BaseModel):
    """Sent by the browser extension (extension/). Only the site's origin and what the user's own
    browser already loaded: never the full page URL, cookies or browsing history."""

    model_config = ConfigDict(str_strip_whitespace=True)

    origin: str = Field(max_length=300)  # "https://www.example.com"
    # Links from the page. An over-long one is dropped rather than failing the request, so a hostile
    # page can't make the whole check fail with one silly link.
    policy_urls: list[str] = Field(default=[], max_length=5)
    opt_out_url: str | None = None  # a "Do Not Sell or Share" link on the page
    # False for the automatic check on each visit: it then uses only what the browser already saw
    # and contacts no site. The popup sends True (opening it is the user asking).
    read_policy: bool = True
    # The text of the policy page open in the browser, sent instead of fetching it. Then
    # policy_urls[0] is that page's URL, and nothing leaves the laptop at all.
    page_text: str | None = Field(default=None, max_length=500_000)
    deep: bool = False  # also run the Gemini pass, in the background (poll until llm is "done")
    refresh: bool = False  # read the policy again instead of using the in-memory result
    # Read from the page in the browser, never from what's typed: the hostnames (only the hostnames)
    # of other sites the page loaded things from, and the kinds of personal data its form fields
    # ask for, as fixed words.
    third_party_hosts: list[str] = Field(default=[], max_length=200)
    asks_for: list[FormField] = Field(default=[], max_length=len(FORM_FIELDS))
    insecure_fields: list[FormField] = Field(default=[], max_length=len(FORM_FIELDS))  # asked for without https

    @field_validator("policy_urls")
    @classmethod
    def _drop_long_links(cls, v: list[str]) -> list[str]:
        return [u for u in v if len(u) <= 2000]

    @field_validator("opt_out_url")
    @classmethod
    def _drop_long_link(cls, v: str | None) -> str | None:
        return v if v and len(v) <= 2000 else None

    @field_validator("third_party_hosts")
    @classmethod
    def _hostnames_only(cls, v: list[str]) -> list[str]:
        # Bare hostnames only. Anything else (a URL, a path, a query, an email) is dropped, so the
        # details a tracker URL can carry, like an account id or a hashed email, go no further.
        hosts = (h.strip().lower().rstrip(".") for h in v)
        return list(dict.fromkeys(h for h in hosts if _HOSTNAME.fullmatch(h)))

    @field_validator("origin")
    @classmethod
    def _origin_only(cls, v: str) -> str:
        try:
            parts = urlsplit(v)
            parts.port  # raises ValueError for a bad port
        except ValueError:
            parts = None
        if parts is None or parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("origin must look like https://www.example.com")
        return f"{parts.scheme}://{parts.netloc.rsplit('@', 1)[-1]}"  # drop any path, query or user:password@


class DataCollected(BaseModel):
    category: DataCategory
    label: str  # "Precise location"
    sensitive: bool
    quote: str  # verbatim from the policy
    section: str = ""  # the heading or lead-in it appeared under, e.g. "Information We Collect"


class SiteRisk(BaseModel):
    level: RiskLevel
    title: str  # "It may sell your personal information"
    detail: str
    quote: str | None = None  # verbatim evidence from the policy; null when the evidence is the page itself
    evidence: list[str] = []  # what was seen on the page instead: hostnames it loaded, fields it asks for


class TrackerFound(BaseModel):
    name: str  # "Meta Pixel", from data/trackers.json
    company: str  # "Meta"
    category: TrackerCategory
    hosts: list[str]  # the hostnames this page loaded it from: the evidence


class BrokerMatch(BaseModel):
    name: str  # from data/brokers.json
    opt_out_url: str | None = None


class AdSellers(BaseModel):
    """From the site's ads.txt, which is read only when the popup opens."""

    status: Literal["running", "done", "none", "failed"]
    url: str | None = None
    count: int = 0  # ad companies it allows to sell its ad space
    companies: list[str] = []  # the ones it lists most


class SitePolicyResponse(BaseModel):
    site: str  # "example.com"
    # "not_read": the automatic check, which contacts no site, had no policy result to reuse yet.
    status: Literal["ok", "no_policy", "unreadable", "not_read"]
    policy_url: str | None = None
    # "site": this laptop fetched it from the site itself. "browser": the user's browser sent the
    # text of the policy page it had open.
    read_from: Literal["site", "browser"] | None = None
    collected: list[DataCollected] = []
    clauses: list[PolicyClause] = []  # selling and sharing, with Stage 4's checks
    no_sale_quote: str | None = None  # "We do not sell your personal information."
    risks: list[SiteRisk] = []  # strongest first
    risk: RiskLevel | None = None  # overall; null when the policy couldn't be read
    summary: str = ""
    opt_out_url: str | None = None
    llm: Literal["off", "running", "done", "failed"] = "off"
    checked_at: str  # ISO time this laptop read the policy
    errors: list[str] = []
    # What the page itself does, seen in the browser: trackers it loaded and personal data it asks for.
    trackers: list[TrackerFound] = []
    asks_for: list[FormField] = []
    insecure_fields: list[FormField] = []
    broker: BrokerMatch | None = None  # the site is a people-search site in data/brokers.json
    ad_sellers: AdSellers | None = None  # null until the popup asks for it


# ---------- Status ----------


class StatusResponse(BaseModel):
    keys: dict[str, bool]  # which API keys are set, never their values
    # The LLM is Gemini now. These keep their old names so the API contract doesn't change.
    ollama_running: bool  # GEMINI_API_KEY is set
    ollama_model: str  # GEMINI_MODEL
    model_pulled: bool  # same as ollama_running
    database: bool


# ---------- Local accounts (stored in the local Postgres only) ----------


def _account_email(v: str) -> str:
    v = v.strip().lower()
    local, _, domain = v.partition("@")
    if not local or "." not in domain or " " in v:
        raise ValueError("Enter a valid email address.")
    return v


def _new_password(v: str) -> str:
    if len(v) < 8:
        raise ValueError("Use at least 8 characters for your password.")
    return v


class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _account_email(v)

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        return _new_password(v)


# "admin": the first account made on this laptop, and anyone an admin promotes (auth.py).
Role = Literal["user", "admin"]


class User(BaseModel):
    email: str
    # The auth routes fill these in. Optional, so code that only knows the email still works.
    id: str | None = None
    role: Role = "user"
    created_at: str | None = None


class PasswordChange(BaseModel):
    """A signed-in user changing their own password."""

    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)

    @field_validator("new_password")
    @classmethod
    def _password(cls, v: str) -> str:
        return _new_password(v)


class PasswordReset(BaseModel):
    """A forgotten password: the one-time code an admin created, and the new password."""

    email: str = Field(max_length=254)
    code: str = Field(min_length=4, max_length=32)
    new_password: str = Field(max_length=256)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _account_email(v)

    @field_validator("new_password")
    @classmethod
    def _password(cls, v: str) -> str:
        return _new_password(v)


class ResetCode(BaseModel):
    """Shown to the admin once, to hand over in person. Only its hash is stored."""

    email: str
    code: str
    expires_at: str


class RoleUpdate(BaseModel):
    role: Role


# ---------- Threat monitor (app/monitor/) ----------
# Severity, confidence and involvement are separate on purpose: a serious breach can be
# "critical" while the user's involvement is still "unconfirmed". Rules in code set all three;
# Gemini only explains them.

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
    include_news: bool = False  # also search news and official notices (Tavily/Exa credits, Gemini calls)


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
    """Gemini's plain-English explanation, after evidence checks in code."""

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
    local_llm: bool  # GEMINI_API_KEY is set (named before the switch to Gemini)
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
# ---------- Digital footprint: companies you track and your data requests to them ----------
# Local Postgres only, scoped to the signed-in account. None of it is sent to Exa, Tavily or
# Gemini, and Dossier never sends a request or changes a company's settings for the user.

RequestKind = Literal["access", "deletion"]
RequestStatus = Literal["draft", "ready_to_send", "sent", "response_received", "completed", "unable_to_complete"]
LawBasis = Literal["none", "gdpr", "ccpa"]  # named in a draft only when the user picks one
ControlState = Literal["on", "off", "unknown"]


def _not_in_future(v: date | None) -> date | None:
    if v and v > date.today():
        raise ValueError("That date is in the future.")
    return v


class PrivacyControl(BaseModel):
    """A privacy or data-sharing setting the user checked on the company's own site, as they
    recorded it. Dossier can't read or change the setting."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    state: ControlState = "unknown"
    checked_on: date | None = None  # the day the user checked; null means they didn't record one
    note: str = Field(default="", max_length=500)

    @field_validator("checked_on")
    @classmethod
    def _checked_on(cls, v: date | None) -> date | None:
        return _not_in_future(v)


class TrackedCompanyInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    website: str = Field(default="", max_length=300)
    account_label: str = Field(default="", max_length=200)  # how they know the user: email, username, account number
    notes: str = Field(default="", max_length=4000)
    controls: list[PrivacyControl] = Field(default_factory=list, max_length=40)

    @field_validator("website")
    @classmethod
    def _website(cls, v: str) -> str:
        return footprint.normalize_website(v)


class RequestCreate(BaseModel):
    kind: RequestKind
    law: LawBasis = "none"


class RequestTextUpdate(BaseModel):
    """Edits to a request's text. Only allowed until the user marks it sent."""

    model_config = ConfigDict(str_strip_whitespace=True)

    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)


class RequestUpdate(BaseModel):
    """One step the user records: a new status, or the same status with a note."""

    model_config = ConfigDict(str_strip_whitespace=True)

    status: RequestStatus
    happened_on: date | None = None  # the day it happened; defaults to today
    note: str = Field(default="", max_length=2000)

    @field_validator("happened_on")
    @classmethod
    def _happened_on(cls, v: date | None) -> date | None:
        return _not_in_future(v)


class RequestEvent(BaseModel):
    status: RequestStatus
    happened_on: str  # YYYY-MM-DD, as the user recorded it
    note: str = ""
    recorded_at: str  # when Dossier saved this step


class DataRequest(BaseModel):
    id: str
    kind: RequestKind
    law: LawBasis
    subject: str
    body: str
    status: RequestStatus
    created_at: str
    updated_at: str
    history: list[RequestEvent] = Field(default_factory=list)  # oldest first
    next_statuses: list[RequestStatus] = Field(default_factory=list)  # what the user can record next
    editable: bool = True  # false once marked sent: the text stays as it was sent


class TrackedCompany(BaseModel):
    id: str
    name: str
    website: str = ""
    account_label: str = ""
    notes: str = ""
    controls: list[PrivacyControl] = Field(default_factory=list)
    created_at: str
    updated_at: str
    requests: list[DataRequest] = Field(default_factory=list)  # newest first
