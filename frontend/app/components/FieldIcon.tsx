import type { FieldType } from "@/lib/api";

// One small drawn icon per kind of personal data, in a single 1.5px stroke. Decorative: the box's
// heading always names the field, so these are aria-hidden.
const PATHS: Record<FieldType, React.ReactNode> = {
  name: (
    <>
      <rect x="1.75" y="3.5" width="12.5" height="9" rx="1.5" />
      <circle cx="5.75" cy="7.25" r="1.5" />
      <path d="M3.75 10.75a2 2 0 0 1 4 0M9.5 6.75h3M9.5 9.25h2.25" />
    </>
  ),
  address: <path d="M2.5 7.5 8 3l5.5 4.5M4 6.5V13h8V6.5M6.75 13v-3h2.5v3" />,
  phone: (
    <>
      <rect x="4.5" y="1.75" width="7" height="12.5" rx="1.5" />
      <path d="M7 11.75h2" />
    </>
  ),
  email: (
    <>
      <rect x="2" y="3.5" width="12" height="9" rx="1.5" />
      <path d="m2.5 4.5 5.5 4 5.5-4" />
    </>
  ),
  relatives: (
    <>
      <circle cx="6" cy="5.5" r="2" />
      <path d="M2.5 13a3.5 3.5 0 0 1 7 0" />
      <circle cx="11.25" cy="6.25" r="1.6" />
      <path d="M10.25 9.75a2.9 2.9 0 0 1 3.5 3.25" />
    </>
  ),
  age: (
    <>
      <rect x="2.5" y="3.5" width="11" height="10" rx="1.5" />
      <path d="M2.5 6.75h11M5.5 2v3M10.5 2v3" />
    </>
  ),
  birthdate: <path d="M3 13.5h10M3.5 13.5V9h9v4.5M8 9V6.5M8 4.75c.8-.6.8-1.4 0-2.25-.8.85-.8 1.65 0 2.25Z" />,
  employer: (
    <>
      <rect x="2" y="5" width="12" height="8.5" rx="1.5" />
      <path d="M5.75 5V3.5h4.5V5M2 9h12" />
    </>
  ),
  ssn: <path d="M8 1.75 13 3.5v4c0 3-2.2 5.3-5 6.75C5.2 12.8 3 10.5 3 7.5v-4Z" />,
  password: (
    <>
      <circle cx="5.5" cy="10.5" r="2.75" />
      <path d="M7.5 8.5 13 3M11 5l1.5 1.5" />
    </>
  ),
  financial: (
    <>
      <rect x="1.75" y="3.5" width="12.5" height="9" rx="1.5" />
      <path d="M1.75 6.5h12.5M4 10h3" />
    </>
  ),
  health: <path d="M8 13.5S2.5 10.2 2.5 6.4A2.9 2.9 0 0 1 8 5a2.9 2.9 0 0 1 5.5 1.4c0 3.8-5.5 7.1-5.5 7.1Z" />,
  school: <path d="M1.5 6 8 3l6.5 3L8 9ZM4 7.3v3.2c0 .9 1.8 2 4 2s4-1.1 4-2V7.3" />,
};

export default function FieldIcon({ field }: { field: FieldType }) {
  return (
    <svg className="field-icon" width="18" height="18" viewBox="0 0 16 16" aria-hidden="true">
      {PATHS[field] ?? PATHS.name}
    </svg>
  );
}
