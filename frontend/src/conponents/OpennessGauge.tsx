interface OpennessGaugeProps {
  value: number | null;
  openThreshold: number;
  closedThreshold: number;
  stage: string;
  compact?: boolean;
}

/**
 * Same visual language as AngleGauge (reuses its CSS classes), but scaled
 * 0-100 for the jumping jack's combined arm+leg "openness" signal instead
 * of a single 0-180 joint angle.
 */
function OpennessGauge({
  value,
  openThreshold,
  closedThreshold,
  stage,
  compact,
}: OpennessGaugeProps) {
  const clamped = value == null ? 0 : Math.min(100, Math.max(0, value));

  const pct = clamped;
  const openPct = openThreshold;
  const closedPct = closedThreshold;

  return (
    <div className={`angle-gauge ${compact ? "compact" : ""}`}>
      <div className="angle-gauge-track">
        <div
          className="angle-gauge-zone down-zone"
          style={{ left: 0, width: `${closedPct}%` }}
        />
        <div
          className="angle-gauge-zone up-zone"
          style={{ left: `${openPct}%`, width: `${100 - openPct}%` }}
        />
        <div className="angle-gauge-marker" style={{ left: `${pct}%` }} />
      </div>

      {!compact && (
        <div className="angle-gauge-labels">
          <span>0 closed</span>
          <span className={`angle-gauge-stage ${stage}`}>{stage}</span>
          <span>100 open</span>
        </div>
      )}
    </div>
  );
}

export default OpennessGauge;
