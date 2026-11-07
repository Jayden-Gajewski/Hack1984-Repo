import type { Tier } from "@/lib/api";
import { TIER_HELP, TIER_LABEL } from "@/lib/display";

// The card's main claim: a tier pill, the likely source, and what the tier means in plain words.
// Wording comes from lib/display.ts. Always "likely source", never "who leaked it".
export default function TierClaim({ tier, company }: { tier: Tier; company: string }) {
  return (
    <div className="lead">
      <p className="lead-line">
        <span className={`pill ${tier}`} title={TIER_HELP[tier]}>
          {TIER_LABEL[tier]}
        </span>
        <span className="lead-source">Likely source: {company}</span>
      </p>
      <p className="lead-help">{TIER_HELP[tier]}</p>
    </div>
  );
}
