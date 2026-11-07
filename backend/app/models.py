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
    "employer", "ssn", "password", "financial", "health",
]
FIELD_TYPES: tuple[str, ...] = get_args(FieldType)

Tier = Literal["proven", "likely", "possible"]
TIERS: tuple[str, ...] = get_args(Tier)  # strongest first

DateSource = Literal["wayback", "published_date", "unknown"]
TextSource = Literal["extract", "snippet"]
PolicyCategory = Literal["sale", "sharing", "advertising", "affiliates", "data_broker"]
RemovalStatus = Literal["removed", "still_listed", "unconfirmed"]


# ---------- Stages 1 and 2: scan ----------


class ScanRequest(BaseModel):
    """The only personal data the app takes: name and city/state. Nothing else."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=100)
    city: str = Field(min_length=2, max_length=100)
    state: str = Field(min_length=2, max_length=2)
    consent: bool = False

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
    broker: str
    broker_id: str | None = None
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
    kind: Literal["broker", "company"]
    recipient: str  # broker or company name
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
