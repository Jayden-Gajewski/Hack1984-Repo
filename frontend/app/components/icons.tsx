// Small drawn icons in one stroke weight. Decorative: the surrounding text carries the meaning.

// The sliding arrow on call-to-action buttons: its shaft appears on hover.
export function Arrow() {
  return (
    <svg className="arrow" width="10" height="10" viewBox="0 0 10 10" aria-hidden>
      <path className="arrow-line" d="M1 5h6.5" />
      <path className="arrow-tip" d="M2 1.5 5.5 5 2 8.5" />
    </svg>
  );
}

export function Check() {
  return (
    <svg className="icon" width="16" height="16" viewBox="0 0 16 16" aria-hidden>
      <path d="m3 8.5 3.2 3L13 4.5" />
    </svg>
  );
}

// A small chevron for "open" (right) and "back" (left) affordances.
export function Chevron({ direction = "right" }: { direction?: "left" | "right" }) {
  return (
    <svg className="icon" width="16" height="16" viewBox="0 0 16 16" aria-hidden>
      <path d={direction === "right" ? "m6 3.5 4.5 4.5L6 12.5" : "m10 3.5L5.5 8l4.5 4.5"} />
    </svg>
  );
}

export function Lock() {
  return (
    <svg className="icon" width="16" height="16" viewBox="0 0 16 16" aria-hidden>
      <rect x="3" y="7" width="10" height="7" rx="1.5" />
      <path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" />
    </svg>
  );
}
