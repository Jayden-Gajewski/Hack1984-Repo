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
