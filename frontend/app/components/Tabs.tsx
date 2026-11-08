"use client";

import { useLayoutEffect, useRef, useState } from "react";

export interface Tab<Id extends string> {
  id: Id;
  label: string;
}

interface Props<Id extends string> {
  tabs: Tab<Id>[];
  active: Id;
  onChange: (id: Id) => void;
  label: string;
}

// An ARIA tablist: click, or arrow keys / Home / End to move between tabs.
// Panels are rendered by the page with id `panel-<id>` and stay mounted, so their state survives a switch.
// One underline slides to the selected tab; it only animates once someone has switched tabs.
export default function Tabs<Id extends string>({ tabs, active, onChange, label }: Props<Id>) {
  const list = useRef<HTMLDivElement>(null);
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const [bar, setBar] = useState<{ x: number; w: number } | null>(null);
  const [animate, setAnimate] = useState(false);
  const activeIndex = tabs.findIndex((t) => t.id === active);

  useLayoutEffect(() => {
    const measure = () => {
      const tab = refs.current[activeIndex];
      if (tab) setBar({ x: tab.offsetLeft, w: tab.offsetWidth });
    };
    measure();
    const observer = new ResizeObserver(measure);
    if (list.current) observer.observe(list.current);
    return () => observer.disconnect();
  }, [activeIndex]);

  function select(index: number) {
    setAnimate(true);
    onChange(tabs[index].id);
  }

  function onKeyDown(e: React.KeyboardEvent, index: number) {
    const last = tabs.length - 1;
    const next =
      e.key === "ArrowRight" ? (index === last ? 0 : index + 1)
      : e.key === "ArrowLeft" ? (index === 0 ? last : index - 1)
      : e.key === "Home" ? 0
      : e.key === "End" ? last
      : null;
    if (next === null) return;
    e.preventDefault();
    select(next);
    refs.current[next]?.focus();
  }

  return (
    <div ref={list} className="tabs" role="tablist" aria-label={label}>
      {tabs.map((tab, i) => (
        <button
          key={tab.id}
          ref={(el) => {
            refs.current[i] = el;
          }}
          type="button"
          role="tab"
          id={`tab-${tab.id}`}
          aria-selected={tab.id === active}
          aria-controls={`panel-${tab.id}`}
          tabIndex={tab.id === active ? 0 : -1}
          className="tab"
          onClick={() => select(i)}
          onKeyDown={(e) => onKeyDown(e, i)}
        >
          {tab.label}
        </button>
      ))}
      {bar && (
        <span
          className="tab-indicator"
          data-animate={animate || undefined}
          aria-hidden="true"
          style={{ transform: `translateX(${bar.x}px) scaleX(${bar.w})` }}
        />
      )}
    </div>
  );
}
