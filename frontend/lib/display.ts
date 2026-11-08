// Display helpers: the wording rules from frontend/CLAUDE.md in one place, plus safe links.
// Say "likely source", never "who leaked it". Every date shows its source.

import type { Confidence, DateSource, Involvement, MonitorEvent, Severity, SourceKind, Tier } from "./api";

export const TIER_LABEL: Record<Tier, string> = {
  proven: "Proven",
  likely: "Likely",
  possible: "Possible",
};

// Shown on hover over a tier badge.
export const TIER_HELP: Record<Tier, string> = {
  proven: "An alias you gave only to this company got mail from someone else.",
  likely: "A breach at this company lines up in time and exposed a field this listing shows.",
  possible: "This company's privacy policy allows selling or sharing your data.",
};

export const DATE_SOURCE_LABEL: Record<DateSource, string> = {
  wayback: "Wayback Machine, earliest snapshot",
  published_date: "published date",
  unknown: "unknown",
};

// How each kind of exposure is described on its card. Saved scans from before public
// profiles existed have no source_kind; treat those as brokers.
export const EXPOSURE_KIND = {
  broker: { label: "Data broker", view: "View listing", draft: "Draft opt-out", page: "Opt-out page" },
  public_profile: {
    label: "Public profile",
    view: "View profile",
    draft: "Draft removal request",
    page: "Removal page",
  },
} as const satisfies Record<SourceKind, { label: string; view: string; draft: string; page: string }>;

export function exposureKind(kind: SourceKind | null | undefined) {
  return EXPOSURE_KIND[kind ?? "broker"] ?? EXPOSURE_KIND.broker;
}

/** Links from scraped data only become clickable if they're plain http(s) URLs. */
export function safeHref(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : undefined;
  } catch {
    return undefined;
  }
}

// ---------- Stages 3, 4 and 6 ----------

export const SOURCE_KIND_LABEL = {
  ag_notice: "State attorney general notice",
  news: "News report",
  web: "Web page",
} as const;

export const DATE_KIND_LABEL = {
  occurred: "happened",
  disclosed: "disclosed",
  unknown: "date unknown",
} as const;

export const POLICY_CATEGORY_LABEL = {
  sale: "Sells personal information",
  data_broker: "Shares with data brokers",
  sharing: "Shares with other companies",
  advertising: "Targeted advertising",
  affiliates: "Shares with affiliates",
} as const;

// Flags that go under "This wasn't a hack, they sold it." The rest are listed as "also allows".
export const SELL_OR_SHARE = new Set(["sale", "data_broker", "sharing"]);

export const REMOVAL_LABEL = {
  removed: "Removed",
  still_listed: "Still listed",
  unconfirmed: "Couldn't check",
} as const;

/** A mailto: link for an address we parsed ourselves; anything odd gets no link. */
export function safeMailto(email: string | null | undefined): string | undefined {
  return email && /^[^\s@<>"']+@[^\s@<>"']+\.[a-z]{2,}$/i.test(email) ? `mailto:${email}` : undefined;
}

export const RISK_LABEL = { high: "High risk", medium: "Medium risk", low: "Low risk" } as const;

// ---------- Threat monitor ----------
// Severity (how bad the breach is) and involvement (whether you're in it) are separate answers.
// Never word a company breach as if it confirmed the user was affected.

export const SEVERITY_LABEL: Record<Severity, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

export const INVOLVEMENT_LABEL: Record<Involvement, string> = {
  confirmed: "Your email is in it",
  not_found: "Not found for your email",
  unconfirmed: "Not confirmed for you",
};

// The short form for a threat row.
export const INVOLVEMENT_SHORT: Record<Involvement, string> = {
  confirmed: "Your email is in it",
  not_found: "Email not found",
  unconfirmed: "Not confirmed",
};

export const CONFIDENCE_LABEL: Record<Confidence, string> = {
  high: "Well evidenced",
  medium: "Partly evidenced",
  low: "Thinly evidenced",
};

export const INCIDENT_DATE_LABEL = {
  occurred: "Happened",
  disclosed: "Disclosed",
  added_to_hibp: "Added to Have I Been Pwned",
} as const;

export const EVENT_LABEL: Record<MonitorEvent["kind"], string> = {
  refresh: "Check",
  new_incident: "New",
  confirmed: "Confirmed",
  company: "Company",
  email: "Email",
  error: "Problem",
  schedule: "Schedule",
};

export const SCHEDULE_LABEL = { 6: "every 6 hours", 12: "every 12 hours", 24: "every day", 168: "every week" } as const;

export const HIBP_ATTRIBUTION_URL = "https://haveibeenpwned.com";

/** "4 minutes ago" for a past ISO time; "never" for null. The exact time goes in a title. */
export function timeAgo(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "unknown";
  const seconds = Math.round((now - then) / 1000);
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

/** A local date and time, for title attributes and the history list. */
export function localTime(iso: string | null | undefined): string {
  if (!iso) return "unknown";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}
