// OWNER: Local LLM & ranking
// Page text and analysis go ONLY here (localhost), never to a cloud API.
import { outboundFetch } from './outbound.js';

const OLLAMA_URL = process.env.OLLAMA_URL || 'http://localhost:11434';
const MODEL = process.env.OLLAMA_MODEL || 'llama3.1:8b';

/**
 * Ask the local model for a JSON answer.
 * Returns the parsed object, or `fallback` if the model's output isn't valid JSON.
 */
export async function askJSON(system, user, fallback = null) {
  const res = await outboundFetch(
    'ollama',
    `${OLLAMA_URL}/api/chat`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: MODEL,
        stream: false,
        format: 'json',
        options: { temperature: 0 },
        messages: [
          { role: 'system', content: system },
          { role: 'user', content: user },
        ],
      }),
    },
    { local: true },
  );
  if (!res.ok) throw new Error(`Ollama ${res.status}: is it running? (ollama serve)`);
  const data = await res.json();
  try {
    return JSON.parse(data.message?.content ?? '');
  } catch {
    console.warn('[ollama] non-JSON output:', data.message?.content?.slice(0, 200));
    return fallback;
  }
}

export async function ollamaHealth() {
  try {
    const res = await fetch(`${OLLAMA_URL}/api/tags`);
    const { models = [] } = await res.json();
    return { running: true, model: MODEL, pulled: models.some((m) => m.name.startsWith(MODEL)) };
  } catch {
    return { running: false, model: MODEL, pulled: false };
  }
}
