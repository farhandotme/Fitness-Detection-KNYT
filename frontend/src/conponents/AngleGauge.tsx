interface AngleGaugeProps {
  angle: number | null;
  upThreshold: number;
  downThreshold: number;
  stage: string;
}

function AngleGauge({ angle, upThreshold, downThreshold, stage }: AngleGaugeProps) {
  const clamped = angle == null ? 0 : Math.min(180, Math.max(0, angle));

  const pct = (clamped / 180) * 100;
  const upPct = (upThreshold / 180) * 100;
  const downPct = (downThreshold / 180) * 100;

  return (
    <div className="angle-gauge">
      <div className="angle-gauge-track">
        <div className="angle-gauge-zone up-zone" style={{ width: `${upPct}%` }} />

        <div
          className="angle-gauge-zone down-zone"
          style={{ left: `${downPct}%`, width: `${100 - downPct}%` }}
        />

        <div className="angle-gauge-marker" style={{ left: `${pct}%` }} />
      </div>

      <div className="angle-gauge-labels">
        <span>0° contracted</span>
        <span className={`angle-gauge-stage ${stage}`}>{stage}</span>
        <span>180° extended</span>
      </div>
    </div>
  );
}

export default AngleGauge;
