"use client";

import { useEffect, useRef, useState } from "react";

// Landing-page sample of the outbound log. Fictional person and .example domains only.
const ROWS = [
  {
    service: "Tavily",
    local: false,
    method: "POST",
    url: "api.tavily.com/search",
    body: '{"query": "Jane Example Springfield IL"}',
    ms: "412 ms",
  },
  {
    service: "Exa",
    local: false,
    method: "POST",
    url: "api.exa.ai/search",
    body: '{"query": "Jane Example Springfield IL", "numResults": 10}',
    ms: "655 ms",
  },
  {
    service: "Tavily",
    local: false,
    method: "POST",
    url: "api.tavily.com/extract",
    body: '{"urls": ["https://people-finder.example/jane-example"]}',
    ms: "1.2 s",
  },
  {
    service: "Wayback",
    local: false,
    method: "GET",
    url: "web.archive.org/cdx/search/cdx",
    body: "?url=people-finder.example/jane-example&limit=1",
    ms: "380 ms",
  },
  {
    service: "Ollama",
    local: true,
    method: "POST",
    url: "localhost:11434/api/generate",
    body: "Page text and prompt. Stays on this laptop.",
    ms: "4.1 s",
  },
];

// Rows arrive one by one when the panel scrolls into view, with a live dot while they stream.
// Without JS, or with reduced motion, every row is simply there.
export default function LogDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(ROWS.length);
  const [armed, setArmed] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    setShown(0);
    setArmed(true);
    let timer: number | undefined;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        observer.disconnect();
        let n = 0;
        timer = window.setInterval(() => {
          n += 1;
          setShown(n);
          if (n >= ROWS.length) window.clearInterval(timer);
        }, 450);
      },
      { rootMargin: "0px 0px -20% 0px" },
    );
    observer.observe(el);
    return () => {
      observer.disconnect();
      window.clearInterval(timer);
    };
  }, []);

  const visible = ROWS.slice(0, shown);
  const sent = visible.filter((r) => !r.local).length;
  const kept = visible.length - sent;

  return (
    <div ref={ref} className="log" role="figure" aria-label="Sample outbound log">
      <div className="log-head">
        <span className="log-title">
          <span className="log-live" data-on={armed && shown < ROWS.length} aria-hidden />
          Outbound log
        </span>
        <span className="log-count">
          <span>{sent} left this laptop</span>
          <span className="log-count-local">{kept} stayed local</span>
        </span>
      </div>
      <ol className="log-rows">
        {ROWS.map((row, i) => (
          <li key={i} className={`log-row${row.local ? " log-local" : ""}`} data-in={i < shown}>
            <span className="log-svc">{row.service}</span>
            <span className="log-url">
              <span className="log-method">{row.method}</span> {row.url}
            </span>
            <span className="log-status">
              200 <span className="log-ms">{row.ms}</span>
            </span>
            <code className="log-body">{row.body}</code>
          </li>
        ))}
      </ol>
      <p className="log-foot">Sample scan of a fictional person. In the app, this panel lists every real request with its full body.</p>
    </div>
  );
}
