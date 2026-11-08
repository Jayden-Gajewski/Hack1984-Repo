"use client";

import { useRef, type PointerEvent, type ReactNode } from "react";

// A soft light that follows the pointer across the card (a CSS port of React Bits' SpotlightCard).
export default function SpotlightCard({ children, className = "" }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);

  function onPointerMove(e: PointerEvent<HTMLDivElement>) {
    const el = ref.current;
    if (!el) return;
    const box = el.getBoundingClientRect();
    el.style.setProperty("--mx", `${e.clientX - box.left}px`);
    el.style.setProperty("--my", `${e.clientY - box.top}px`);
  }

  return (
    <div ref={ref} className={`spotlight ${className}`} onPointerMove={onPointerMove}>
      {children}
    </div>
  );
}
