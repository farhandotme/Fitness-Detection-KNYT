import React from "react";
import { RepData } from "@/hooks/useExerciseSocket";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import { AngleProgress } from "@/components/AngleProgress";
import { getPrimaryAngle } from "@/utils/angleTelemetry";

interface RepPanelProps {
  data: RepData;
  lastRep: {
    rep_form_quality: string | null;
    rep_classification: string | null;
    rep_duration: number | null;
    feedback: string | null;
  } | null;
  exerciseName: string;
}

function DataCell({
  label,
  value,
  highlight = false,
  dim = false,
}: {
  label: string;
  value: React.ReactNode;
  highlight?: boolean;
  dim?: boolean;
}) {
  return (
    <div className="bg-[#101d26] border border-white/10 rounded-xl p-3 flex flex-col gap-1.5">
      <span className="text-[10px] font-bold tracking-widest uppercase text-slate-500">
        {label}
      </span>
      <span
        className={cn(
          "text-sm font-bold font-mono leading-none",
          highlight
            ? "text-primary"
            : dim
              ? "text-slate-500"
              : "text-slate-200",
        )}
      >
        {value ?? "—"}
      </span>
    </div>
  );
}

function qualityColor(q: string | null) {
  if (!q) return "text-slate-500";
  if (q.toLowerCase().includes("good") || q.toLowerCase().includes("perfect"))
    return "text-primary";
  if (q.toLowerCase().includes("needs") || q.toLowerCase().includes("poor"))
    return "text-amber-400";
  return "text-[#e2e8f0]";
}

function stageBadgeStyle(stage: string) {
  const s = stage.toUpperCase();
  if (s === "UP" || s === "EXTENDED" || s === "OPEN")
    return "bg-primary/10 text-primary border-primary/25";
  if (s === "DOWN" || s === "CONTRACTED" || s === "CLOSED")
    return "bg-accent/10 text-accent border-accent/25";
  return "bg-white/5 text-slate-500 border-white/10";
}

export function RepPanel({ data, lastRep, exerciseName }: RepPanelProps) {
  const target = data.target_reps || 1;
  const progress = Math.min((data.rep_count / target) * 100, 100);
  const goodPct =
    data.rep_count > 0
      ? Math.round((data.good_reps / data.rep_count) * 100)
      : 0;
  const angleTelemetry = getPrimaryAngle(data);

  return (
    <div className="flex flex-col gap-3">
      {/* Header Row: exercise label + stage */}
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-bold tracking-widest uppercase text-[#4a5568]">
          {exerciseName}
        </span>
        {data.stage && (
          <span
            className={cn(
              "text-[10px] font-black tracking-widest uppercase px-2.5 py-1 rounded border",
              stageBadgeStyle(data.stage),
            )}
          >
            {data.stage}
          </span>
        )}
      </div>

      {/* Big Rep Counter */}
      <div className="bg-[#101d26] border border-white/10 rounded-xl p-4 relative overflow-hidden">
        {/* Progress fill */}
        <div
          className="absolute bottom-0 left-0 bg-primary/8 transition-all duration-500 ease-out"
          style={{ width: `${progress}%`, height: "100%" }}
        />
        <div className="relative z-10 flex items-end gap-3">
          <AnimatePresence mode="wait">
            <motion.span
              key={data.rep_count}
              initial={{ y: -12, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              exit={{ y: 12, opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="text-7xl font-black font-mono text-slate-100 leading-none tabular-nums"
            >
              {data.rep_count}
            </motion.span>
          </AnimatePresence>
          <div className="pb-1 flex flex-col">
            {data.target_reps && (
              <span className="text-2xl font-bold font-mono text-slate-500">
                / {data.target_reps}
              </span>
            )}
            <span className="text-[10px] text-slate-500 uppercase tracking-widest">
              reps
            </span>
          </div>
          {data.rep_count > 0 && (
            <div className="ml-auto pb-1 text-right">
              <div className="text-2xl font-bold font-mono text-primary">
                {goodPct}%
              </div>
              <div className="text-[10px] text-slate-500 uppercase tracking-widest">
                good form
              </div>
            </div>
          )}
        </div>
        {/* Every uploaded detector uses its own authoritative angle key. */}
        {angleTelemetry && (
          <AngleProgress
            value={angleTelemetry.value}
            label={angleTelemetry.label}
          />
        )}
      </div>

      {/* Data Grid */}
      <div className="grid grid-cols-2 gap-2">
        <DataCell
          label="Good / Flawed"
          value={`${data.good_reps} / ${data.flawed_reps}`}
          highlight
        />
        <DataCell
          label="Last Rep"
          value={
            lastRep
              ? lastRep.rep_form_quality?.replace(/_/g, " ").toUpperCase()
              : "—"
          }
        />
        {data.left_elbow_angle !== null && (
          <DataCell
            label="Left Angle"
            value={`${Math.round(data.left_elbow_angle ?? 0)}°`}
          />
        )}
        {data.right_elbow_angle !== null && (
          <DataCell
            label="Right Angle"
            value={`${Math.round(data.right_elbow_angle ?? 0)}°`}
          />
        )}
        <DataCell
          label="Speed"
          value={
            lastRep?.rep_classification?.replace(/_/g, " ").toUpperCase() ?? "—"
          }
        />
        <DataCell
          label="Rep Duration"
          value={
            lastRep?.rep_duration != null
              ? `${lastRep.rep_duration.toFixed(1)}s`
              : "—"
          }
        />
        <DataCell label="Elapsed" value={`${Math.round(data.elapsed_time)}s`} />
        <DataCell
          label="Alignment"
          value={
            data.alignment_ok
              ? "OK"
              : (data.alignment_issue?.toUpperCase() ?? "—")
          }
          highlight={data.alignment_ok}
        />
      </div>

      {/* Feedback chips */}
      {(data.framing_message ||
        data.alignment_issue ||
        (!data.position_ok && data.position_message)) && (
        <div className="flex flex-col gap-1.5">
          <span className="text-[10px] font-bold tracking-widest uppercase text-slate-500">
            Form Cues
          </span>
          <div className="flex flex-col gap-1">
            {data.framing_message && (
              <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg px-3 py-2 text-xs text-blue-300">
                {data.framing_message}
              </div>
            )}
            {data.alignment_issue && (
              <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2 text-xs text-amber-300">
                {data.alignment_issue}
              </div>
            )}
            {!data.position_ok && data.position_message && (
              <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2 text-xs text-amber-300">
                {data.position_message}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Coach Feedback */}
      <div className="bg-[#101d26] border border-white/10 rounded-xl p-3">
        <span className="text-[10px] font-bold tracking-widest uppercase text-slate-500 block mb-2">
          Coach Feedback
        </span>
        <p className="text-sm text-slate-300 leading-relaxed">
          {!data.pose_detected
            ? "No person detected — step into frame."
            : data.feedback
              ? data.feedback
              : data.ready === false
                ? "Getting a steady lock on your position…"
                : "Tracking active — begin your reps."}
        </p>
      </div>
    </div>
  );
}
