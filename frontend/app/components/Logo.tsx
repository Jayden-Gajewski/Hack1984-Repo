// Wordmark: a file folder with a keyhole, the dossier you get to lock.
export default function Logo() {
  return (
    <span className="logo">
      <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden>
        <path
          d="M3 8a2.5 2.5 0 0 1 2.5-2.5h4.6l2.2 2.5h8.2A2.5 2.5 0 0 1 23 10.5v8A2.5 2.5 0 0 1 20.5 21h-15A2.5 2.5 0 0 1 3 18.5Z"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinejoin="round"
        />
        <circle cx="13" cy="13.4" r="1.9" fill="currentColor" />
        <path d="M12.2 14.6h1.6l.5 2.8h-2.6Z" fill="currentColor" />
      </svg>
      Dossier
    </span>
  );
}
