// Pure presentational, no hooks/browser APIs - stays a plain Server
// Component so it can be rendered directly from app/dashboard/page.tsx.
// `href` (when given) makes the whole tile a Link instead of a div - still
// no client JS needed for that.

import Link from "next/link";

const SPARK_WIDTH = 74;
const SPARK_HEIGHT = 30;

function buildSparkline(values: number[]): { line: string; area: string; endX: number; endY: number } {
  if (values.length < 2) {
    return { line: "", area: "", endX: SPARK_WIDTH, endY: SPARK_HEIGHT / 2 };
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const n = values.length;

  const points = values.map((value, i) => ({
    x: (i / (n - 1)) * SPARK_WIDTH,
    y: SPARK_HEIGHT - ((value - min) / range) * SPARK_HEIGHT,
  }));

  const line = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const area = `${line} L${points[n - 1].x.toFixed(1)},${SPARK_HEIGHT} L${points[0].x.toFixed(1)},${SPARK_HEIGHT} Z`;
  const last = points[n - 1];

  return { line, area, endX: last.x, endY: last.y };
}

export function StatTile({
  label,
  value,
  deltaPct,
  sparkline,
  href,
  badge,
}: {
  label: string;
  /** Pre-formatted - the caller decides currency/count formatting. */
  value: string;
  /** null = no previous-period baseline to compare against (hides the badge
   * instead of showing a misleading 0%/∞). */
  deltaPct: number | null;
  sparkline: number[];
  /** Makes the tile clickable, e.g. the revenue tile linking to the
   * work-orders list filtered to exactly the orders that make up this
   * figure - so the number is always one click away from being checkable,
   * not just asserted. */
  href?: string;
  /** Small secondary pill under the value, e.g. "Оплачено 3 200 000 ₽" on
   * the revenue tile - a related figure that doesn't deserve its own tile
   * but is worth surfacing without a click-through. */
  badge?: string;
}) {
  const { line, area, endX, endY } = buildSparkline(sparkline);
  const isUp = deltaPct !== null && deltaPct >= 0;

  const inner = (
    <>
      <div className="stat-top">
        <span className="stat-label">{label}</span>
        {deltaPct !== null && (
          <span className={isUp ? "stat-delta stat-delta-up" : "stat-delta stat-delta-down"}>
            {isUp ? "▲" : "▼"} {Math.abs(deltaPct).toFixed(0)}%
          </span>
        )}
      </div>
      <div className="stat-bottom">
        <span className="stat-value">{value}</span>
        {line && (
          <svg className="sparkline" viewBox={`0 0 ${SPARK_WIDTH} ${SPARK_HEIGHT}`} preserveAspectRatio="none">
            <path d={area} className="sparkline-area" />
            <path d={line} className="sparkline-line" />
            <circle cx={endX} cy={endY} r={2.6} className="sparkline-dot" />
          </svg>
        )}
      </div>
      {badge && <span className="stat-badge">{badge}</span>}
    </>
  );

  if (href) {
    return (
      <Link href={href} className="stat-tile stat-tile-clickable">
        {inner}
      </Link>
    );
  }

  return <div className="stat-tile">{inner}</div>;
}
