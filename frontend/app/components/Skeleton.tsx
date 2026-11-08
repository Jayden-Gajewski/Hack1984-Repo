// Placeholder blocks shaped like the content that's loading: list rows or lines of text.
// It only becomes visible if loading takes a moment, so fast local loads don't flash.
export default function Skeleton({
  label,
  rows = 3,
  shape = "row",
}: {
  label: string;
  rows?: number;
  shape?: "row" | "line";
}) {
  return (
    <div className="skeleton" data-shape={shape} role="status">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <span key={i} className="skeleton-item" aria-hidden />
      ))}
    </div>
  );
}
