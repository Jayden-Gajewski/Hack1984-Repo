import type { ReactNode } from "react";

// A button label with two states stacked in one grid cell, so the button keeps the width of the
// wider label and never jumps when it switches. The "on" state leads with a spinner by default
// (busy), or with the icon you pass (e.g. a check for "Copied"). Screen readers hear only the
// visible label.
export default function SwapLabel({
  on,
  idle,
  active,
  icon,
}: {
  on: boolean;
  idle: ReactNode;
  active: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <span className="swap-label" data-on={on ? "" : undefined}>
      <span className="swap-off" aria-hidden={on || undefined}>
        {idle}
      </span>
      <span className="swap-on" aria-hidden={!on || undefined}>
        {icon ?? <span className="spinner" aria-hidden />}
        {active}
      </span>
    </span>
  );
}
