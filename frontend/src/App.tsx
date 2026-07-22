import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

import Layout from "./conponents/Layout";
import FingerPage from "./pages/FingerPage";
import BicepPage from "./pages/BicepPage";
import SquatPage from "./pages/SquatPage";
import PushupPage from "./pages/PushupPage";
import BodyAnalysisPage from "./pages/BodyAnalysisPage";
import ExerciseLibraryPage from "./pages/ExerciseLibraryPage";
import JumpingJackPage from "./pages/JumpingJackPage";
import LungePage from "./pages/LungePage";
import HighKneesPage from "./pages/HighKneesPage";
import ShoulderPressPage from "./pages/ShoulderPressPage";
import LateralRaisePage from "./pages/LateralRaisePage";
import DeadBugPage from "./pages/DeadBugPage";
import SidePlankPage from "./pages/SidePlankPage";
import BridgeHoldPage from "./pages/BridgeHoldPage";
import MountainClimberPage from "./pages/MountainClimberPage";
import PlankHoldPage from "./pages/PlankholdPage";
import JabPage from "./pages/JabPage";
import BirdDogPage from "./pages/BirdDogPage";
import CalfRaisePage from "./pages/CalfRaisePage";
import TreePosePage from "./pages/TreePosePage";
import WarriorIIPage from "./pages/WarrioriiPage";
import CobraPosePage from "./pages/CobraPosePage";
import ChairPosePage from "./pages/ChairPosePage";
import DownwardDogPage from "./pages/DownwardDogPage";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/exercises" replace />} />
          <Route path="exercises" element={<ExerciseLibraryPage />} />
          <Route path="exercises/jumping-jacks" element={<JumpingJackPage />} />
          <Route path="exercises/lunge" element={<LungePage />} />
          <Route path="exercises/high-knees" element={<HighKneesPage />} />
          <Route
            path="exercises/shoulder-press"
            element={<ShoulderPressPage />}
          />
          <Route
            path="exercises/lateral-raise"
            element={<LateralRaisePage />}
          />
          <Route path="fingers" element={<FingerPage />} />
          <Route path="reps" element={<BicepPage />} />
          <Route path="squat" element={<SquatPage />} />
          <Route path="pushup" element={<PushupPage />} />
          <Route path="body-scan" element={<BodyAnalysisPage />} />
          <Route path="muay_thai_jab" element={<JabPage />} />
          <Route path="dead_bug" element={<DeadBugPage />} />
          <Route path="side_plank" element={<SidePlankPage />} />
          <Route path="bridge_pose" element={<BridgeHoldPage />} />
          <Route path="exercises/plank-hold" element={<PlankHoldPage />} />
          <Route path="bird_dog" element={<BirdDogPage />} />
          <Route path="calf_raise" element={<CalfRaisePage />} />
          <Route path="tree_pose" element={<TreePosePage />} />
          <Route path="warriorII" element={<WarriorIIPage />} />
          <Route path="cobra_pose" element={<CobraPosePage />} />
          <Route path="chair_pose" element={<ChairPosePage />} />
          <Route path="downward_dog" element={<DownwardDogPage />} />
          <Route
            path="/exercises/mountain-climber"
            element={<MountainClimberPage />}
          />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
