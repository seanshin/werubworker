/**
 * Thin progress bar with dynamic color thresholds for resource monitoring.
 */

export function ProgressBar({
  value,
  color,
  label,
}: {
  value: number;
  color?: string;
  label: string;
}) {
  const pct = Math.min(100, Math.max(0, value));
  const barColor =
    pct > 90
      ? "var(--danger)"
      : pct > 70
        ? "var(--warn)"
        : color || "var(--accent)";

  return (
    <div className="flex items-center gap-3">
      <span className="text-[12px] text-muted w-12 shrink-0">{label}</span>
      <div className="flex-1 h-2 rounded-full bg-paper overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, background: barColor }}
        />
      </div>
      <span className="text-[12px] text-ink w-10 text-right tabular-nums">
        {pct}%
      </span>
    </div>
  );
}
