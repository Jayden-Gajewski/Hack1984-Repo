---
name: local-llm-prompt
description: Write or tune a local Ollama prompt in server/prompts/ that returns strict JSON via askJSON, with schema validation and a safe fallback. Enforces the "likely source, never who leaked it" wording rule. Use when adding or fixing an LLM step (exposed-field extraction, policy clause flagging, evidence-tier ranking, opt-out drafting), or when the model returns malformed JSON, hallucinated fields, or accusatory wording.
---

# local-llm-prompt

All analysis runs on local Ollama through `askJSON(system, user)` in `server/lib/ollama.js` (`/api/chat` with `format: "json"`). Small local models drift, so every prompt needs a tight schema, validation, and a fallback.

## Prompt module pattern (`server/prompts/<name>.js`)

Export the system prompt, a user-prompt builder, a validator and a fallback together, so callers can't skip validation:

```js
export const SYSTEM = `You extract exposed personal-data fields from a people-search page.
Return ONLY a JSON object matching exactly:
{"fields": [{"type": "address"|"phone"|"relatives"|"email"|"age"|"other", "evidence": string}], "matchesSubject": boolean}
Rules:
- Use only facts present in the text. If unsure, omit the field.
- "evidence" is a short quote (max 80 chars) copied from the text.
- No prose, no markdown, no extra keys.`;

export const buildUser = ({ name, city, text }) =>
  `Subject: ${name}, ${city}\n\nPAGE TEXT:\n${text.slice(0, 8000)}`;

export function validate(out) { /* return cleaned object or null */ }
export const FALLBACK = { fields: [], matchesSubject: false, _fallback: true };
```

## Writing rules

1. **Schema in the system prompt**, written out literally with enums. Put one short example only if the model keeps getting the shape wrong.
2. **Truncate inputs** (about 8k chars of page text). Small models lose the instructions on long inputs. Put the instructions in the system message and the data in the user message.
3. **Closed vocabularies:** enums for types and tiers (`"Proven"|"Likely"|"Possible"`), booleans over free text.
4. **Ground every claim:** ask for an `evidence` quote so the UI can show it and you can verify it with `text.includes(evidence)`.
5. **Wording rule (non-negotiable):** any output naming a company must say **"likely source"**. Never "leaked", "who leaked it", "responsible", or "guilty". Put this in the system prompt for ranking and drafting prompts, *and* enforce it in `validate` (reject or rewrite the banned phrases). Evidence tiers mean: Proven = alias match; Likely = timing and breach scope line up; Possible = the policy allows sharing.
6. For the policy check, ask for the clause quote plus `kind: "sells"|"shares"|"affiliates"|"none"`. This supports the "this wasn't a hack, they sold it" claim, so it needs the quote.

## Validation and fallback (in the caller)

```js
let out;
try { out = validate(await askJSON(SYSTEM, buildUser(input))); } catch { out = null; }
if (!out) {               // one retry with a stricter nudge
  try { out = validate(await askJSON(SYSTEM + "\nReturn valid JSON only.", buildUser(input))); } catch {}
}
return out ?? FALLBACK;   // never crash a stage on a bad LLM reply
```
`validate` should: check the types, drop unknown keys, filter enum values, drop `evidence` not found in the source text, and apply the wording rule.

## Tuning loop

1. Save 2–3 real inputs (from a consenting teammate, kept local and uncommitted) and run the prompt against each.
2. Check: valid JSON? Is every field grounded? No banned wording? Is latency acceptable (check `OLLAMA_MODEL`; smaller models are faster for the demo)?
3. Change one thing at a time: tighten the schema, add the example, shorten the input.

## Never

- Never send prompts or page text to a cloud LLM. If Ollama is down, use `FALLBACK` and show "analysis unavailable".
- Don't let free-text LLM output reach the UI without going through `validate`.
