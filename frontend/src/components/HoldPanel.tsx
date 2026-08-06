import React from "react";
import { HoldData } from "@/hooks/useExerciseSocket";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { formatTime } from "@/utils/formatTime";

interface HoldPanelProps {
  data: HoldData;
  exerciseName: string;
}

function DataCell({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: React.ReactNode;
  highlight?: boolean;
}) {
  return (
    <div className="bg-[#0d1117] border border-[#1e2530] rounded-lg p-3 flex flex-col gap-1.5">
      <span className="text-[10px] font-bold tracking-widest uppercase text-[#4a5568]">
        {label}
      </span>
      <span
        className={cn(
          "text-sm font-bold font-mono leading-none",
          highlight ? "text-[#00ff87]" : "text-[#e2e8f0]",
        )}
      >
        {value ?? "—"}
      </span>
    </div>
  );
}

function holdStateBadge(state: string) {
  if (state === "holding")
    return "bg-[#00ff87]/20 text-[#00ff87] border-[#00ff87]/30";
  if (state === "broken") return "bg-red-500/20 text-red-400 border-red-500/30";
  return "bg-[#1e2530] text-[#94a3b8] border-[#1e2530]";
}

export function HoldPanel({ data, exerciseName }: HoldPanelProps) {
  const target = data.target_seconds || 1;
  const progress = Math.min((data.hold_seconds / target) * 100, 100);
  const isHolding = data.hold_state === "holding";

  return (
    <div className="flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-bold tracking-widest uppercase text-[#4a5568]">
          {exerciseName}
        </span>
        <span
          className={cn(
            "text-[10px] font-black tracking-widest uppercase px-2.5 py-1 rounded border",
            holdStateBadge(data.hold_state),
          )}
        >
          {data.hold_state.replace(/_/g, " ")}
        </span>
      </div>

      {/* Big Timer */}
      <div
        className={cn(
          "border rounded-xl p-4 relative overflow-hidden transition-colors duration-500",
          isHolding
            ? "bg-[#00ff87]/5 border-[#00ff87]/20"
            : "bg-[#0d1117] border-[#1e2530]",
        )}
      >
        <div
          className={cn(
            "absolute bottom-0 left-0 transition-all duration-1000 ease-linear",
            isHolding ? "bg-[#00ff87]/10" : "bg-[#1e2530]/40",
          )}
          style={{ width: `${progress}%`, height: "100%" }}
        />
        <div className="relative z-10 flex items-end gap-3">
          <motion.span
            animate={{ scale: isHolding ? [1, 1.01, 1] : 1 }}
            transition={{ repeat: isHolding ? Infinity : 0, duration: 1 }}
            className="text-7xl font-black font-mono text-white leading-none tabular-nums"
          >
            {formatTime(data.hold_seconds)}
          </motion.span>
          <div className="pb-1 flex flex-col">
            {data.target_seconds && (
              <span className="text-2xl font-bold font-mono text-[#4a5568]">
                / {formatTime(data.target_seconds)}
              </span>
            )}
            <span className="text-[10px] text-[#4a5568] uppercase tracking-widest">
              hold time
            </span>
          </div>
          {data.form_score !== null && (
            <div className="ml-auto pb-1 text-right">
              <div className="text-2xl font-bold font-mono text-[#00ff87]">
                {Math.round(data.form_score)}
              </div>
              <div className="text-[10px] text-[#4a5568] uppercase tracking-widest">
                form score
              </div>
            </div>
          )}
        </div>

        {/* Progress bar */}
        <div className="mt-3">
          <div className="h-1.5 bg-[#1e2530] rounded-full overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all duration-1000",
                isHolding ? "bg-[#00ff87]" : "bg-[#2d3748]",
              )}
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      </div>

      {/* Data Grid */}
      <div className="grid grid-cols-2 gap-2">
        <DataCell
          label="Best Streak"
          value={formatTime(data.best_streak_seconds)}
          highlight
        />
        <DataCell label="Breaks" value={data.break_count} />
        <DataCell label="Good Seconds" value={formatTime(data.good_seconds)} />
        <DataCell
          label="Flawed Seconds"
          value={formatTime(data.flawed_seconds)}
        />
        <DataCell
          label="Current Streak"
          value={formatTime(data.current_streak_seconds)}
        />
        <DataCell
          label="Avg Form Score"
          value={
            data.avg_form_score !== null
              ? `${Math.round(data.avg_form_score)}/100`
              : "—"
          }
        />
        <DataCell
          label="Calibrated"
          value={data.calibrated ? "YES" : "NO"}
          highlight={data.calibrated}
        />
        <DataCell label="Elapsed" value={`${Math.round(data.elapsed_time)}s`} />
        {data.alignment_angle !== undefined &&
          data.alignment_angle !== null && (
            <DataCell
              label="Alignment Angle"
              value={`${Math.round(data.alignment_angle)}°`}
            />
          )}
        {data.knee_angle !== undefined && data.knee_angle !== null && (
          <DataCell
            label="Knee Angle"
            value={`${Math.round(data.knee_angle)}°`}
          />
        )}
      </div>

      {/* Posture Messages */}
      {data.posture_messages && data.posture_messages.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <span className="text-[10px] font-bold tracking-widest uppercase text-[#4a5568]">
            Posture Checks
          </span>
          <div className="flex flex-col gap-1">
            {data.posture_messages.map((msg, i) => (
              <div
                key={i}
                className={cn(
                  "rounded-lg px-3 py-2 text-xs border",
                  data.posture_ok
                    ? "bg-[#00ff87]/10 border-[#00ff87]/20 text-[#00ff87]"
                    : "bg-amber-500/10 border-amber-500/20 text-amber-300",
                )}
              >
                {msg}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Framing feedback */}
      {data.framing_message && (
        <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg px-3 py-2 text-xs text-blue-300">
          {data.framing_message}
        </div>
      )}

      {/* Coach Feedback */}
      <div className="bg-[#0d1117] border border-[#1e2530] rounded-xl p-3">
        <span className="text-[10px] font-bold tracking-widest uppercase text-[#4a5568] block mb-2">
          Coach Feedback
        </span>
        <p className="text-sm text-[#94a3b8] leading-relaxed">
          {!data.pose_detected
            ? "No person detected — step into frame."
            : data.feedback
              ? data.feedback
              : !data.calibrated
                ? "Calibrating your form baseline…"
                : isHolding
                  ? "Great — keep holding strong."
                  : "Hold the position to begin tracking."}
        </p>
      </div>
    </div>
  );
}
