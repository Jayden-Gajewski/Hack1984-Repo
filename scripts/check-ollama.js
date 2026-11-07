// Quick check that the local LLM is running and returns JSON.
import 'dotenv/config';
import { ollamaHealth, askJSON } from '../server/lib/ollama.js';

const health = await ollamaHealth();
console.log(health);
if (!health.running) {
  console.error('Ollama is not running. Install from https://ollama.com and start it.');
  process.exit(1);
}
if (!health.pulled) {
  console.error(`Model not pulled. Run: ollama pull ${health.model}`);
  process.exit(1);
}
const t = Date.now();
const out = await askJSON('Return ONLY JSON: {"ok": true, "color": string}', 'Pick a color.');
console.log(out, `${Date.now() - t}ms`);
