"use client";

import { useId, useRef, useState } from "react";
import type { Company } from "@/lib/api";

interface Props {
  companies: Company[];
  selected: string[]; // company ids, in the order they were added
  onAdd: (id: string) => void;
  onRemove: (id: string) => void;
  onCreate: (name: string) => Promise<Company>; // any other company: the backend finds its website
}

type Option = { kind: "company"; company: Company } | { kind: "create"; name: string };

const WEBSITE = /^(https?:\/\/)?(www\.)?([a-z0-9-]+\.)+[a-z]{2,}([/:?#].*)?$/i;

// Type to find a company; Enter or click adds it as a tag. Anything not in the list can be added
// too: the backend matches a name to its website with one logged search, or uses a typed website.
// Keyboard: ↑/↓ move, Enter adds, Escape closes or clears, Backspace on an empty field removes the last tag.
export default function CompanyPicker({ companies, selected, onAdd, onRemove, onCreate }: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [pending, setPending] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const uid = useId();
  const listId = `${uid}-list`;

  const typed = query.trim();
  const q = typed.toLowerCase();
  const byId = new Map(companies.map((c) => [c.id, c]));
  const matches = companies
    .filter((c) => !selected.includes(c.id))
    .filter((c) => !q || c.name.toLowerCase().includes(q) || c.domains.some((d) => d.includes(q)))
    .sort((a, b) => Number(b.name.toLowerCase().startsWith(q)) - Number(a.name.toLowerCase().startsWith(q)));
  const known = companies.some((c) => c.name.toLowerCase() === q || c.id === q || c.domains.includes(q));
  const options: Option[] = [
    ...matches.map((company) => ({ kind: "company" as const, company })),
    ...(typed.length >= 2 && !known && !pending ? [{ kind: "create" as const, name: typed }] : []),
  ];
  const activeIndex = Math.min(active, Math.max(options.length - 1, 0));
  const showList = open && options.length > 0;
  const optionId = (o: Option) => `${uid}-opt-${o.kind === "company" ? o.company.id : "new"}`;

  function add(company: Company) {
    onAdd(company.id);
    setQuery("");
    setActive(0);
    setAnnouncement(`${company.name} added. ${selected.length + 1} selected.`);
    input.current?.focus();
  }

  async function create(name: string) {
    setPending(name);
    setCreateError(null);
    try {
      const company = await onCreate(name);
      setQuery("");
      setActive(0);
      setAnnouncement(`${company.name} added, website ${company.domains[0] ?? "unknown"}.`);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : `Couldn't add ${name}.`);
    } finally {
      setPending(null);
      input.current?.focus();
    }
  }

  function choose(option: Option) {
    if (option.kind === "company") add(option.company);
    else void create(option.name);
  }

  function remove(id: string) {
    onRemove(id);
    setAnnouncement(`${byId.get(id)?.name ?? id} removed.`);
    input.current?.focus();
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) return setOpen(true);
      if (options.length === 0) return;
      const step = e.key === "ArrowDown" ? 1 : -1;
      setActive((activeIndex + step + options.length) % options.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (showList && options[activeIndex]) choose(options[activeIndex]);
    } else if (e.key === "Escape") {
      if (open) setOpen(false);
      else setQuery("");
    } else if (e.key === "Backspace" && query === "" && selected.length > 0) {
      remove(selected[selected.length - 1]);
    }
  }

  // Bold the part of the name that matches what was typed.
  function label(name: string) {
    const at = q ? name.toLowerCase().indexOf(q) : -1;
    if (at < 0) return name;
    return (
      <>
        {name.slice(0, at)}
        <mark>{name.slice(at, at + q.length)}</mark>
        {name.slice(at + q.length)}
      </>
    );
  }

  return (
    <div className="picker">
      <label htmlFor={`${uid}-input`}>Companies</label>
      {/* Clicking anywhere in the field focuses the text input, like a normal input. */}
      <div className="picker-field" onMouseDown={(e) => {
        if (e.target === e.currentTarget) {
          e.preventDefault();
          input.current?.focus();
        }
      }}>
        {selected.length > 0 && (
          <ul className="tokens" aria-label="Selected companies">
            {selected.map((id) => {
              const company = byId.get(id);
              const name = company?.name ?? id;
              const site = company?.custom ? company.domains[0] : null;
              const guessed = company?.domain_source === "guessed";
              return (
                <li
                  key={id}
                  className="token"
                  title={guessed ? "Website guessed from the name because the lookup failed. Remove it and type the website to fix it." : undefined}
                >
                  {name}
                  {site && site !== name && (
                    <span className="token-domain">
                      {site}
                      {guessed && " (guess)"}
                    </span>
                  )}
                  <button type="button" className="token-remove" aria-label={`Remove ${name}`} onClick={() => remove(id)}>
                    <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
                      <path d="M1.5 1.5l7 7M8.5 1.5l-7 7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                    </svg>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        <input
          ref={input}
          id={`${uid}-input`}
          type="text"
          className="picker-input"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={showList}
          aria-controls={listId}
          aria-activedescendant={showList && options[activeIndex] ? optionId(options[activeIndex]) : undefined}
          autoComplete="off"
          spellCheck={false}
          placeholder={selected.length === 0 ? "Type any company, like Tinder" : "Add another company"}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
            setOpen(true);
            setCreateError(null);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={onKeyDown}
        />
      </div>

      {showList && (
        <ul id={listId} className="picker-list" role="listbox" aria-label="Companies">
          {options.map((option, i) => (
            <li
              key={optionId(option)}
              id={optionId(option)}
              role="option"
              aria-selected={i === activeIndex}
              className={option.kind === "create" ? "picker-option picker-create" : "picker-option"}
              onMouseDown={(e) => e.preventDefault()} // keep focus in the input
              onMouseMove={() => i !== activeIndex && setActive(i)}
              onClick={() => choose(option)}
            >
              {option.kind === "company" ? (
                <>
                  <span>{label(option.company.name)}</span>
                  {option.company.domains[0] && <span className="picker-domain">{option.company.domains[0]}</span>}
                </>
              ) : (
                <>
                  <span>
                    Add <strong>&ldquo;{option.name}&rdquo;</strong>
                  </span>
                  <span className="picker-domain">
                    {WEBSITE.test(option.name) ? "uses this website" : "looks up its website"}
                  </span>
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      {pending && (
        <p className="picker-status muted small">Finding {pending}&rsquo;s website&hellip;</p>
      )}
      {createError && (
        <p className="error" role="alert">
          {createError}
        </p>
      )}
      <p className="sr-only" role="status">
        {pending ? `Finding ${pending}'s website.` : announcement}
      </p>
    </div>
  );
}
