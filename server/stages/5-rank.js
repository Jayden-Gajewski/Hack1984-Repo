// OWNER: Local LLM & ranking
// Stage 5: rank LIKELY sources for each exposure. Pure logic, no network.
//   Proven   = alias match (stage 7)
//   Likely   = a breach before the exposure's public-by date whose data types overlap the exposed fields
//   Possible = the company's policy allows selling/sharing
// Wording rule: always "likely source", never "who leaked it".

const TIER_ORDER = { Proven: 0, Likely: 1, Possible: 2 };

const FIELD_TO_BREACH_TYPES = {
  address: ['address'],
  phone: ['phone'],
  email: ['email'],
  relatives: ['relatives'],
  age: ['dob'],
};

function exposedTypes(exposure) {
  return Object.entries(exposure.fields ?? {})
    .filter(([, on]) => on)
    .flatMap(([f]) => FIELD_TO_BREACH_TYPES[f] ?? []);
}

export function rankSources({ exposures = [], breaches = [], policies = [], aliasMatches = [] }) {
  return exposures.map((exposure) => {
    const leads = [];
    const types = exposedTypes(exposure);
    const publicBy = exposure.publicBy?.date;

    for (const m of aliasMatches) {
      leads.push({
        tier: 'Proven',
        company: m.company,
        reason: `Mail sent to your ${m.company}-only alias came from ${m.fromDomain}.`,
      });
    }

    for (const b of breaches) {
      for (const incident of b.breaches ?? []) {
        const overlap = (incident.dataTypes ?? []).filter((t) => types.includes(t));
        const timingFits = !publicBy || !incident.date || incident.date <= publicBy;
        if (overlap.length && timingFits) {
          leads.push({
            tier: 'Likely',
            company: b.company,
            reason: `${b.company} breach (${incident.date ?? 'date unknown'}) exposed ${overlap.join(', ')}` +
              (publicBy ? `, before this listing was public (${publicBy}).` : '.'),
            sourceUrl: incident.sourceUrl,
          });
        }
      }
    }

    for (const p of policies) {
      if (p.sells || p.sharesWithBrokersOrPartners || p.sharesForAds) {
        leads.push({
          tier: 'Possible',
          company: p.company,
          reason: `${p.company}'s privacy policy allows ${p.sells ? 'selling' : 'sharing'} your data.`,
          sourceUrl: p.policyUrl,
        });
      }
    }

    leads.sort((a, b) => TIER_ORDER[a.tier] - TIER_ORDER[b.tier]);
    return { exposureId: exposure.id, likelySources: leads };
  });
}
