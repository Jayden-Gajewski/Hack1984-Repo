"""Pydantic models: the API contract with the frontend (frontend/lib/api.ts mirrors them).

Shared file. Keep changes additive (new optional fields are safe), call them out in the
commit message, and tell the UI owner before renaming or removing anything.

Every date carries a source label. A missing date is null with source "unknown", never a guess.
"""

import re
from typing import Annotated, Literal, get_args
from urllib.parse import urlsplit

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
    policy_urls: list[Annotated[str, Field(max_length=2000)]] = Field(default=[], max_length=5)
    opt_out_url: str | None = Field(default=None, max_length=2000)  # a "Do Not Sell or Share" link on the page
    # The text of the policy page open in the browser, sent instead of fetching it. Then
    # policy_urls[0] is that page's URL, and nothing leaves the laptop at all.
    page_text: str | None = Field(default=None, max_length=500_000)
    deep: bool = False  # also run the local LLM pass, in the background (poll until llm is "done")
    refresh: bool = False  # read the policy again instead of using the in-memory result
    # Read from the page in the browser, never from what's typed: the hostnames (only the hostnames)
    # of other sites the page loaded things from, and the kinds of personal data its form fields
    # ask for, as fixed words.
    third_party_hosts: list[Annotated[str, Field(max_length=253)]] = Field(default=[], max_length=200)
    asks_for: list[FormField] = Field(default=[], max_length=len(FORM_FIELDS))
    insecure_fields: list[FormField] = Field(default=[], max_length=len(FORM_FIELDS))  # asked for without https

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
    status: Literal["ok", "no_policy", "unreadable"]
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
