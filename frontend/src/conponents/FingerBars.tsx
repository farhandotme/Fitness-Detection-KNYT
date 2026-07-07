type Fingers = {
  thumb: boolean;
  index: boolean;
  middle: boolean;
  ring: boolean;
  pinky: boolean;
};

interface FingerBarsProps {
  handLabel: string;
  count: number;
  fingers: Fingers;
}

const ORDER: (keyof Fingers)[] = ["thumb", "index", "middle", "ring", "pinky"];

const LABELS: Record<keyof Fingers, string> = {
  thumb: "T",
  index: "I",
  middle: "M",
  ring: "R",
  pinky: "P",
};

function FingerBars({ handLabel, count, fingers }: FingerBarsProps) {
  return (
    <div className="hand-card">
      <div className="hand-card-head">
        <span className="hand-label">{handLabel} hand</span>
        <span className="hand-count">{count}</span>
      </div>

      <div className="finger-bars">
        {ORDER.map((key) => (
          <div key={key} className={`finger-bar ${fingers[key] ? "up" : ""}`}>
            <div className="finger-bar-track">
              <div className="finger-bar-fill" />
            </div>
            <span className="finger-bar-label">{LABELS[key]}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default FingerBars;
