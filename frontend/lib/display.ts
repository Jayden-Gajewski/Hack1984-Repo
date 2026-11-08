// Display helpers: the wording rules from frontend/CLAUDE.md in one place, plus safe links.
// Say "likely source", never "who leaked it". Every date shows its source.

import type { DateSource, SourceKind, Tier } from "./api";

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

// ---------- Digital footprint ----------
// Footprint dates are the ones the user entered, so they read "(you recorded)". Dates Dossier
// set itself read "saved". A missing date reads "unknown".

export const REQUEST_KIND_LABEL = {
  access: "Copy of my data",
  deletion: "Delete my account and data",
} as const;

export const REQUEST_STATUS_LABEL = {
  draft: "Draft",
  ready_to_send: "Ready to send",
  sent: "Sent",
  response_received: "Response received",
  completed: "Completed",
  unable_to_complete: "Unable to complete",
} as const;

// Draft and Ready to send mean the user hasn't sent it yet.
export const UNSENT_STATUSES = new Set(["draft", "ready_to_send"]);
// Requests still waiting on someone: the user or the company.
export const OPEN_STATUSES = new Set(["draft", "ready_to_send", "sent", "response_received"]);

export const LAW_LABEL = {
  none: "Don't name a law",
  gdpr: "GDPR (EU and UK)",
  ccpa: "CCPA (California)",
} as const;

export const CONTROL_STATE_LABEL = { on: "On", off: "Off", unknown: "Not sure" } as const;

/** "Nov 2, 2026" for a YYYY-MM-DD day, read as a local date so it never shifts a day. */
export function formatDay(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** The local calendar day of a saved timestamp, formatted like formatDay. */
export function formatSavedDay(timestamp: string): string {
  return new Date(timestamp).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** A date as YYYY-MM-DD in local time. Today by default, for date inputs. */
export function localDayISO(when: Date | string = new Date()): string {
  const t = new Date(when);
  return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`;
}

export const todayISO = () => localDayISO();

/** "shop.example" for display, from a stored website. */
export function websiteHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}
