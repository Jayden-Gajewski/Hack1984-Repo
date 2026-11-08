"use client";

import { useState } from "react";
import SpotlightCard from "./SpotlightCard";

// Hero sample: one fictional person on three fictional broker sites, one per evidence tier.
// The progress bar's CSS animation advances the card; hovering pauses it, and with reduced
// motion it only changes when clicked.
const TIER_LABEL = { proven: "Proven", likely: "Likely", possible: "Possible" } as const;

const LISTINGS = [
  {
    site: "people-finder.example",
    person: "Jane Example, 34",
    risk: "high",
    fields: ["Home address", "Phone", "Relatives", "Age"],
    date: "Mar 14, 2021",
    dateSource: "Wayback Machine",
    source: "ExampleShop",
    tier: "likely",
    why: "An ExampleShop breach disclosed in February 2021 included name, address and phone, a month before this listing went public.",
  },
  {
    site: "lookup-anyone.example",
    person: "Jane M. Example",
    risk: "medium",
    fields: ["Email", "Phone", "Past addresses"],
    date: "Aug 2, 2022",
    dateSource: "Wayback Machine",
    source: "ExampleFitness",
    tier: "proven",
    why: "Mail to the alias you gave only to ExampleFitness arrived from lookup-anyone.example.",
  },
  {
    site: "whos-nearby.example",
    person: "Jane Example",
    risk: "low",
    fields: ["Name", "Age range", "Relatives"],
    date: "Unknown",
    dateSource: "no snapshot found",
    source: "ExampleCredit",
    tier: "possible",
    why: "ExampleCredit's privacy policy allows sharing customer data with marketing partners.",
  },
] as const;

export default function ListingCycler() {
  const [index, setIndex] = useState(0);
  const advance = () => setIndex((i) => (i + 1) % LISTINGS.length);

  return (
    <SpotlightCard className="mock">
      <div className="mock-tabs">
        {LISTINGS.map((l, i) => (
          <button
            key={l.site}
            type="button"
            className="mock-tab"
            aria-label={`Show sample listing ${i + 1} of ${LISTINGS.length}`}
            aria-pressed={i === index}
            onClick={() => setIndex(i)}
          >
            <span className="mock-tab-track">
              <span
                className="mock-tab-fill"
                data-active={i === index}
                data-done={i < index}
                onAnimationEnd={i === index ? advance : undefined}
              />
            </span>
          </button>
        ))}
      </div>

      <div className="mock-stack">
        {LISTINGS.map((l, i) => (
          <div key={l.site} className="mock-body" data-active={i === index} aria-hidden={i !== index}>
            <div className="mock-head">
              <div>
                <p className="mock-site">{l.site}</p>
                <p className="mock-name">{l.person}</p>
                <p className="mock-place">Springfield, IL</p>
              </div>
              <span className={`mock-risk mock-risk-${l.risk}`}>
                {l.risk[0].toUpperCase() + l.risk.slice(1)} risk
              </span>
            </div>
            <ul className="mock-fields" aria-label="What this listing shows">
              {l.fields.map((field) => (
                <li key={field}>{field}</li>
              ))}
            </ul>
            <dl className="mock-facts">
              <div>
                <dt>Public since</dt>
                <dd>
                  {l.date} <span className="mock-src">{l.dateSource}</span>
                </dd>
              </div>
              <div>
                <dt>Likely source</dt>
                <dd>
                  {l.source} <span className={`tier tier-${l.tier}`}>{TIER_LABEL[l.tier]}</span>
                </dd>
              </div>
            </dl>
            <p className="mock-why">{l.why}</p>
          </div>
        ))}
      </div>

      <div className="mock-foot">
        <span className="mock-btn">Draft opt-out</span>
        <span className="mock-note">Sample listings, fictional person</span>
      </div>
    </SpotlightCard>
  );
}
