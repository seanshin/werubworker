/**
 * Simple SVG sparkline/bar chart for monitoring dashboards.
 * No external dependencies — pure SVG.
 */

interface MiniChartProps {
  data: number[];
  height?: number;
  width?: number;
  color?: string;
  type?: "bar" | "line";
  label?: string;
}

export function MiniChart({
  data,
  height = 40,
  width = 200,
  color = "var(--accent)",
  type = "bar",
  label,
}: MiniChartProps) {
  if (data.length === 0) return null;

  const max = Math.max(...data, 1);
  const padding = 2;
  const usableH = height - padding * 2;
  const usableW = width - padding * 2;

  if (type === "line") {
    const step = usableW / Math.max(data.length - 1, 1);
    const points = data
      .map((v, i) => {
        const x = padding + i * step;
        const y = padding + usableH - (v / max) * usableH;
        return `${x},${y}`;
      })
      .join(" ");

    return (
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className="shrink-0"
        aria-label={label}
      >
        <polyline
          points={points}
          fill="none"
          stroke={color}
          strokeWidth={1.5}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      </svg>
    );
  }

  // Bar chart
  const gap = 1;
  const barW = Math.max(1, (usableW - gap * (data.length - 1)) / data.length);

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="shrink-0"
      aria-label={label}
    >
      {data.map((v, i) => {
        const barH = Math.max(1, (v / max) * usableH);
        const x = padding + i * (barW + gap);
        const y = padding + usableH - barH;
        return (
          <rect
            key={i}
            x={x}
            y={y}
            width={barW}
            height={barH}
            rx={barW > 3 ? 1 : 0}
            fill={color}
            opacity={0.8}
          />
        );
      })}
    </svg>
  );
}
