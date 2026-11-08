// A company's initials on a neutral tile. Never a remote logo: loading one would tell that
// company's servers which breaches you're looking at (frontend/CLAUDE.md, "No remote images").
// Neutral on purpose too: an invented brand colour would pass for a real logo.
export default function CompanyMark({ name }: { name: string }) {
  const words = name.replace(/[^\p{L}\p{N}\s&]/gu, " ").split(/\s+/).filter(Boolean);
  const initials =
    words.length >= 2 && !/^\(/.test(words[1])
      ? (words[0][0] + words[1][0]).toUpperCase()
      : (words[0] ?? "?").slice(0, 2).replace(/^./, (c) => c.toUpperCase());
  return (
    <span className="company-mark" aria-hidden="true">
      {initials}
    </span>
  );
}
