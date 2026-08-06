export interface AngleTelemetry {
  value: number;
  label: string;
}

type TelemetryRecord = Record<string, unknown>;

function finiteNumber(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return value;
}

function firstNumber(data: TelemetryRecord, keys: string[]): number | null {
  for (const key of keys) {
    const value = finiteNumber(data[key]);
    if (value !== null) return value;
  }
  return null;
}

function averagePair(
  data: TelemetryRecord,
  leftKey: string,
  rightKey: string,
): number | null {
  const left = finiteNumber(data[leftKey]);
  const right = finiteNumber(data[rightKey]);
  if (left !== null && right !== null) return (left + right) / 2;
  return left ?? right;
}

/**
 * The uploaded FastAPI detectors do not all use one angle key:
 * push-ups/squats use angle, holds use knee/alignment angles, and several
 * exercises return left/right joint angles. Keep the backend response intact
 * and resolve the best authoritative value only for presentation.
 */
export function getPrimaryAngle(data: unknown): AngleTelemetry | null {
  if (!data || typeof data !== "object") return null;
  const telemetry = data as TelemetryRecord;

  const directFields: Array<[string[], string]> = [
    [["smoothed_angle", "angle"], "Movement angle"],
    [["smoothed_tuck_angle", "tuck_angle"], "Tuck angle"],
    [["elbow_angle"], "Elbow angle"],
    [["knee_angle"], "Knee angle"],
    [["hip_angle"], "Hip angle"],
    [["alignment_angle"], "Alignment angle"],
    [["lean_angle"], "Lean angle"],
    [["torso_angle"], "Torso angle"],
  ];

  for (const [keys, label] of directFields) {
    const value = firstNumber(telemetry, keys);
    if (value !== null) return { value, label };
  }

  const pairedFields: Array<[string, string, string]> = [
    ["left_elbow_angle", "right_elbow_angle", "Elbow angle"],
    ["left_knee_angle", "right_knee_angle", "Knee angle"],
    ["left_hip_angle", "right_hip_angle", "Hip angle"],
    ["left_angle", "right_angle", "Movement angle"],
    ["left_thigh_angle", "right_thigh_angle", "Thigh angle"],
    ["left_arm_reach_angle", "right_arm_reach_angle", "Arm reach angle"],
    ["left_leg_reach_angle", "right_leg_reach_angle", "Leg reach angle"],
  ];

  for (const [leftKey, rightKey, label] of pairedFields) {
    const value = averagePair(telemetry, leftKey, rightKey);
    if (value !== null) return { value, label };
  }

  return null;
}

export function clampAngle(value: number): number {
  return Math.min(180, Math.max(0, value));
}
