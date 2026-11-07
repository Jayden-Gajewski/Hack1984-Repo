// Display helpers: the wording rules from frontend/CLAUDE.md in one place, plus safe links.
// Say "likely source", never "who leaked it". Every date shows its source.

import type { DateSource, Tier } from "./api";

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
