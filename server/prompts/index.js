// OWNER: Local LLM & ranking
// All prompts for the local Ollama model live here so they're easy to tune.
// Small models: keep instructions short, always show the exact JSON shape, temperature 0.

export const EXPOSED_FIELDS = {
  system: `You read text from a people-search / data-broker web page and report what personal data it shows about ONE specific person.
Return ONLY JSON with this exact shape:
{"matchesPerson": boolean, "fields": {"address": boolean, "phone": boolean, "email": boolean, "relatives": boolean, "age": boolean, "employer": boolean}, "evidence": {"address": string|null, "phone": string|null, "email": string|null, "relatives": string|null}}
- matchesPerson: true only if the page is about the named person in or near the given city.
- evidence: a SHORT masked example, e.g. "12** Main St", "(617) ***-**12". Never copy full values.`,
  user: ({ name, city, state, text }) =>
    `Person: ${name}, ${city}${state ? ', ' + state : ''}\n\nPage text:\n${text.slice(0, 8000)}`,
};

export const POLICY_CLAUSES = {
  system: `You read excerpts from a company's privacy policy and flag clauses where the company SELLS or SHARES personal data with third parties.
Return ONLY JSON:
{"sells": boolean, "sharesForAds": boolean, "sharesWithBrokersOrPartners": boolean, "flags": [{"quote": string, "kind": "sell"|"share-ads"|"share-partners"|"other", "plain": string}]}
- quote: copy the exact sentence (max 300 chars).
- plain: one plain-English sentence for a normal person.
- At most 5 flags. If nothing qualifies, return empty flags and false values.`,
  user: ({ company, text }) => `Company: ${company}\n\nPolicy excerpts:\n${text}`,
};

export const BREACH_TIMELINE = {
  system: `You read search results about data breaches at a company and build a timeline.
Return ONLY JSON:
{"breaches": [{"date": "YYYY-MM-DD" | "YYYY-MM" | "YYYY", "dataTypes": string[], "summary": string, "sourceUrl": string}]}
- dataTypes use these words when they apply: name, email, phone, address, dob, ssn, password, payment, health, relatives.
- Only include incidents at THIS company. Merge duplicates. Use the sourceUrl from the result you got it from.
- If no breaches are described, return {"breaches": []}.`,
  user: ({ company, results }) =>
    `Company: ${company}\n\nResults:\n` +
    results.map((r, i) => `[${i + 1}] ${r.url} (${r.date || 'no date'})\n${r.title}\n${r.snippet}`).join('\n\n'),
};
