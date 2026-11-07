"""Pydantic models: the API contract with the frontend (frontend/lib/api.ts mirrors them).

Shared file. Keep changes additive (new optional fields are safe), call them out in the
commit message, and tell the UI owner before renaming or removing anything.

Every date carries a source label. A missing date is null with source "unknown", never a guess.
"""

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


class ScanResponse(BaseModel):
    scan_id: str
    exposures: list[Exposure]
    errors: list[str]
    saved_at: str | None = None  # ISO timestamp when this came from a saved scan; null for a fresh one


# ---------- Stages 3 and 4: accounts ----------


class AccountsRequest(BaseModel):
    companies: list[str]  # ids from data/companies.json


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
    company: str | None = None  # company id from data/companies.json

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
    company: str  # company id from data/companies.json, or a name for a demo company


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
