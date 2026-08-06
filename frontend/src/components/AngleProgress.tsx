import { clampAngle } from "@/utils/angleTelemetry";

interface AngleProgressProps {
  value: number;
  label?: string;
}

export function AngleProgress({
  value,
  label = "Movement angle",
}: AngleProgressProps) {
  const angle = clampAngle(value);

  return (
    <div className="mt-3" aria-label={`${label}: ${Math.round(angle)} degrees`}>
      <div className="mb-1 flex items-center justify-between gap-2 text-[10px] text-slate-500">
        <span>0° contracted</span>
        <span className="font-mono font-bold text-primary">
          {Math.round(angle)}°
        </span>
        <span>180° extended</span>
      </div>
      <div
        className="h-1.5 overflow-hidden rounded-full bg-white/10"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={180}
        aria-valuenow={Math.round(angle)}
        aria-label={label}
      >
        <div
          className="h-full rounded-full bg-primary transition-[width] duration-150"
          style={{ width: `${(angle / 180) * 100}%` }}
        />
      </div>
    </div>
  );
}
