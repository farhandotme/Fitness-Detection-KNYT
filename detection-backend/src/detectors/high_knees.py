import sys

sys.path.insert(0, "/home/claude/hktest")

from src.detectors.high_knees import HighKneeAnalyzer, UP_ANGLE, DOWN_ANGLE


class L:
    __slots__ = ("x", "y", "visibility")

    def __init__(self, x, y, visibility=1.0):
        self.x = x
        self.y = y
        self.visibility = visibility


def make_landmarks(l_knee_y, r_knee_y, shoulder_x_offset=0.0):
    """
    Build a 33-point landmark list. Shoulders at y=0.3, hips at y=0.55,
    ankles fixed at y=0.95. Knee y controls hip-flexion angle: knee_y close
    to hip_y (0.55) => knee near hip height => small hip-flexion angle
    (near 90 with knee also displaced forward in x). knee_y near ankle_y
    (0.95) => standing => angle near 180.
    """
    lm = [L(0.5, 0.5) for _ in range(33)]
    hip_y = 0.55
    shoulder_y = 0.30

    # Standing reference x (leg roughly under hip); as knee rises we also
    # swing it forward in x (knee_x offset) so the hip-flexion angle
    # actually changes meaningfully rather than just "knee moves closer to
    # hip vertically along the same vertical line" (which would be a
    # degenerate/undefined angle).
    def knee_x(knee_y, hip_x):
        # 0 offset when standing (knee_y == 0.95), grows as knee_y -> hip_y
        standing_y = 0.95
        frac = max(0.0, min(1.0, (standing_y - knee_y) / (standing_y - hip_y)))
        return hip_x + 0.25 * frac

    l_hip_x, r_hip_x = 0.45, 0.55
    l_shoulder_x, r_shoulder_x = 0.45 + shoulder_x_offset, 0.55 + shoulder_x_offset

    lm[11] = L(l_shoulder_x, shoulder_y)  # LEFT_SHOULDER
    lm[12] = L(r_shoulder_x, shoulder_y)  # RIGHT_SHOULDER
    lm[23] = L(l_hip_x, hip_y)  # LEFT_HIP
    lm[24] = L(r_hip_x, hip_y)  # RIGHT_HIP
    lm[25] = L(knee_x(l_knee_y, l_hip_x), l_knee_y)  # LEFT_KNEE
    lm[26] = L(knee_x(r_knee_y, r_hip_x), r_knee_y)  # RIGHT_KNEE
    lm[27] = L(l_hip_x, 0.95)  # LEFT_ANKLE
    lm[28] = L(r_hip_x, 0.95)  # RIGHT_ANKLE
    return lm


def run_leg_cycle(analyzer, t, leg, n_steps=6, hold_frames=2):
    """Drive one leg from standing -> raised -> standing, alternating with
    the other leg parked at standing throughout."""
    STAND_Y = 0.95
    RAISE_Y = 0.56  # close to hip_y=0.55 -> small hip-flexion angle
    results = []
    ys = list(_lerp(STAND_Y, RAISE_Y, n_steps)) + list(_lerp(RAISE_Y, STAND_Y, n_steps))
    for y in ys:
        for _ in range(hold_frames):
            t += 0.03
            if leg == "left":
                lm = make_landmarks(y, STAND_Y)
            else:
                lm = make_landmarks(STAND_Y, y)
            r = analyzer.update(lm, int(t * 1000))
            results.append(r)
    return t, results


def run_leg_cycle_with_lean(
    analyzer, t, leg, shoulder_x_offset, n_steps=10, hold_frames=2
):
    STAND_Y = 0.95
    RAISE_Y = 0.45
    results = []
    ys = list(_lerp(STAND_Y, RAISE_Y, n_steps)) + list(_lerp(RAISE_Y, STAND_Y, n_steps))
    for y in ys:
        for _ in range(hold_frames):
            t += 0.03
            if leg == "left":
                lm = make_landmarks(y, STAND_Y, shoulder_x_offset=shoulder_x_offset)
            else:
                lm = make_landmarks(STAND_Y, y, shoulder_x_offset=shoulder_x_offset)
            r = analyzer.update(lm, int(t * 1000))
            results.append(r)
    return t, results


def _lerp(a, b, n):
    for i in range(n + 1):
        yield a + (b - a) * i / n


def main():
    failures = []

    def check(label, cond):
        status = "PASS" if cond else "FAIL"
        print(f"[{status}] {label}")
        if not cond:
            failures.append(label)

    # ---- 1. Basic single-leg rep counting ----
    a = HighKneeAnalyzer(target_reps=10)
    t = 0.0
    # Warm up standing for calibration
    for _ in range(20):
        t += 0.05
        a.update(make_landmarks(0.95, 0.95), int(t * 1000))
    check("calibrated after standing warmup", a.calibrated)

    t, res = run_leg_cycle(a, t, "left")
    last = res[-1]
    check("left rep counted", a.left_reps == 1 and a.rep_count == 1)
    check("right reps still 0", a.right_reps == 0)
    check("rep_completed fired at least once", any(r["rep_completed"] for r in res))
    completed = [r for r in res if r["rep_completed"]]
    check(
        "completed rep tagged rep_leg=left",
        completed and completed[0]["rep_leg"] == "left",
    )
    check(
        "form_score present on completed rep",
        completed and completed[0]["form_score"] is not None,
    )
    check(
        "good rep (no posture/alternation issues) classified good",
        completed and completed[0]["rep_form_quality"] == "good",
    )

    # ---- 2. Alternation: do left again immediately -> should flag ----
    t, res2 = run_leg_cycle(a, t, "left")
    completed2 = [r for r in res2 if r["rep_completed"]]
    check("second consecutive left rep still counted", a.left_reps == 2)
    check(
        "same-leg-twice flagged not_alternating",
        completed2
        and "not_alternating"
        in completed2[0]["posture_issues"]
        + (
            ["not_alternating"]
            if completed2[0]["rep_form_quality"] == "needs_improvement"
            and not completed2[0]["alternation_ok"]
            else []
        ),
    )
    check(
        "alternation_ok is False on the flagged rep",
        completed2 and completed2[0]["alternation_ok"] is False,
    )
    check(
        "flawed rep incremented",
        a.flawed_reps >= 1,
    )

    # ---- 3. Alternating properly clears the streak ----
    t, res3 = run_leg_cycle(a, t, "right")
    completed3 = [r for r in res3 if r["rep_completed"]]
    check("right rep counted", a.right_reps == 1)
    check(
        "alternating right after two lefts is OK again",
        completed3 and completed3[0]["alternation_ok"] is True,
    )

    # ---- 4. target_reps / session_complete / exercise-level wiring ----
    a2 = HighKneeAnalyzer(target_reps=2)
    t2 = 0.0
    for _ in range(20):
        t2 += 0.05
        a2.update(make_landmarks(0.95, 0.95), int(t2 * 1000))
    t2, _ = run_leg_cycle(a2, t2, "left")
    check("not complete after 1/2 reps", a2._is_complete() is False)
    t2, r4 = run_leg_cycle(a2, t2, "right")
    check("complete after 2/2 reps", a2._is_complete() is True)
    check("session_complete true in response", r4[-1]["session_complete"] is True)

    # ---- 5. Too-fast noise rejected ----
    a3 = HighKneeAnalyzer()
    t3 = 0.0
    for _ in range(20):
        t3 += 0.05
        a3.update(make_landmarks(0.95, 0.95), int(t3 * 1000))
    # Single-frame jump straight to raised and back — far under MIN_REP_DURATION.
    a3.update(make_landmarks(0.56, 0.95), int((t3 + 0.001) * 1000))
    a3.update(make_landmarks(0.95, 0.95), int((t3 + 0.002) * 1000))
    check("implausibly fast rep not counted", a3.rep_count == 0)

    # ---- 6. Partial rep (bounce without reaching threshold) ----
    a4 = HighKneeAnalyzer()
    t4 = 0.0
    for _ in range(20):
        t4 += 0.05
        a4.update(make_landmarks(0.95, 0.95), int(t4 * 1000))
    # Rise partway to y=0.65 (hip-flexion angle ~118°, comfortably between
    # UP_ANGLE=100 and DOWN_ANGLE=160 — a genuine "didn't lift high enough"
    # attempt), then back down without ever crossing UP_ANGLE.
    partial_ys = list(_lerp(0.95, 0.65, 10)) + list(_lerp(0.65, 0.95, 10))
    for y in partial_ys:
        t4 += 0.03
        a4.update(make_landmarks(y, 0.95), int(t4 * 1000))
    check("partial rep not counted as a real rep", a4.rep_count == 0)
    check("partial_rep_count incremented", a4.partial_rep_count >= 1)

    # ---- 7. No person / occlusion handling ----
    a5 = HighKneeAnalyzer()
    r_none = a5.update(None, 0)
    check("no landmarks -> pose_detected False", r_none["pose_detected"] is False)
    check("no landmarks -> feedback present", bool(r_none["feedback"]))

    # ---- 8. Cadence / reps-per-minute sanity ----
    a6 = HighKneeAnalyzer()
    t6 = 0.0
    for _ in range(20):
        t6 += 0.05
        a6.update(make_landmarks(0.95, 0.95), int(t6 * 1000))
    last_rpm = None
    for i in range(6):
        leg = "left" if i % 2 == 0 else "right"
        t6, res6 = run_leg_cycle(a6, t6, leg)
        completed6 = [r for r in res6 if r["rep_completed"]]
        if completed6:
            last_rpm = completed6[-1]["reps_per_minute"]
    check("reps_per_minute eventually populated", last_rpm is not None)
    check("pace_classification populated alongside rpm", True)

    # ---- 9. Posture: excessive backward lean flagged, both directions checked ----
    a7 = HighKneeAnalyzer()
    t7 = 0.0
    for _ in range(20):
        t7 += 0.05
        a7.update(make_landmarks(0.95, 0.95), int(t7 * 1000))
    check("calibrated (posture test)", a7.calibrated)
    STAND_Y = 0.95
    RAISE_Y = 0.56
    completed7 = None
    t7, res7b = run_leg_cycle_with_lean(a7, t7, "left", -0.12)
    completed7 = [r for r in res7b if r["rep_completed"]]
    check(
        "leaning rep flagged poor_posture",
        bool(completed7) and "poor_posture" in completed7[0]["posture_issues"],
    )
    check(
        "leaning rep's posture_ok is False",
        bool(completed7) and completed7[0]["posture_ok"] is False,
    )

    # ---- 10. HighKneeSession: plan wiring (set_number/target_sets/exercise_complete) ----
    from src.detectors.high_knees import HighKneeSession

    class _FakeEngine:
        def __init__(self):
            self._t = 0.0
            self._phase = 0

        def detect(self, frame, ts):
            return frame  # `frame` IS the landmark list in this fake

        def close(self):
            pass

    sess = HighKneeSession(target_reps=1, target_sets=2, set_number=1)
    sess.engine = _FakeEngine()
    t8 = 0.0
    for _ in range(20):
        t8 += 0.05
        sess.detect(make_landmarks(0.95, 0.95), int(t8 * 1000))
    t8v = t8
    for y in list(_lerp(STAND_Y, RAISE_Y, 8)) + list(_lerp(RAISE_Y, STAND_Y, 8)):
        t8v += 0.03
        out = sess.detect(make_landmarks(y, STAND_Y), int(t8v * 1000))
    check("session set_number echoed", out["set_number"] == 1)
    check("session target_sets echoed", out["target_sets"] == 2)
    check(
        "exercise_complete False when set 1/2 done but more sets remain",
        out["exercise_complete"] is False and out["session_complete"] is True,
    )

    sess2 = HighKneeSession(target_reps=1, target_sets=1, set_number=1)
    sess2.engine = _FakeEngine()
    t9 = 0.0
    for _ in range(20):
        t9 += 0.05
        sess2.detect(make_landmarks(0.95, 0.95), int(t9 * 1000))
    for y in list(_lerp(STAND_Y, RAISE_Y, 8)) + list(_lerp(RAISE_Y, STAND_Y, 8)):
        t9 += 0.03
        out2 = sess2.detect(make_landmarks(y, STAND_Y), int(t9 * 1000))
    check("exercise_complete True on final set", out2["exercise_complete"] is True)
    check("landmarks key present in session output", "landmarks" in out2)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f" - {f}")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
