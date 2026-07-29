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
import PikePushupPage from "./pages/PikePushupPage";
import TuckJumpPage from "./pages/TuckJumpPage";
import SumoSquatPage from "./pages/SumoSquatPage";
import TrianglePosePage from "./pages/TrianglePosePage";
import StandingForwardFoldPage from "./pages/StandingForwardFoldPage";
import ReverseWarriorPage from "./pages/ReverseWarriorPage";
import ArmCirclesPage from "./pages/ArmCirclesPage";
import StandingCrossCrunchPage from "./pages/StandingCrossCrunchPage";
import PeacockPosePage from "./pages/PeacockPosePage";
import WindmillPage from "./pages/windMillRotationStretchPage";
import HollowHoldPage from "./pages/HollowHoldPage";
import FlutterKicksPage from "./pages/FlutterKicksPage";
import ButtKicksPage from "./pages/ButtKicksPage";
import WallSitPage from "./pages/WallSitPage";
import LegRaisePage from "./pages/LegRaisePage";
import RussianTwistPage from "./pages/RussianTwistPage";
import SingleLegSquatPage from "./pages/SingleLegSquatPage";
import HalfMoonPage from "./pages/HalfMoonPage";
import BicycleCrunchPage from "./pages/BicycleCrunchPage";
import HinduPushupPage from "./pages/HinduPushupPage";
import ArnoldPressPage from "./pages/ArnoldPressPage";
import DancerPosePage from "./pages/DancerPosePage";
import SupermanPage from "./pages/SupermanPage";

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
          <Route path="pike_pushup" element={<PikePushupPage />} />
          <Route path="tuck_jump" element={<TuckJumpPage />} />
          <Route path="sumo_squat" element={<SumoSquatPage />} />
          <Route path="triangle_pose" element={<TrianglePosePage />} />
          <Route path="reverse_warrior" element={<ReverseWarriorPage />} />
          <Route path="arm_circles" element={<ArmCirclesPage />} />
          <Route path="peacock_pose" element={<PeacockPosePage />} />
          <Route path="wind_mill_rotation" element={<WindmillPage />} />
          <Route path="hollow_hold" element={<HollowHoldPage />} />
          <Route path="flutter_kicks" element={<FlutterKicksPage />} />
          <Route path="butt_kicks" element={<ButtKicksPage />} />
          <Route path="wall_sit" element={<WallSitPage />} />
          <Route path="leg_raise" element={<LegRaisePage />} />
          <Route path="russian_twist" element={<RussianTwistPage />} />
          <Route path="single_leg_squat" element={<SingleLegSquatPage />} />
          <Route path="half_moon_pose" element={<HalfMoonPage />} />
          <Route path="bicycle_crunch" element={<BicycleCrunchPage />} />
          <Route path="hindu_pushup" element={<HinduPushupPage />} />
          <Route path="arnold_press" element={<ArnoldPressPage />} />
          <Route path="dancer_pose" element={<DancerPosePage />} />
          <Route path="supermen_pose" element={<SupermanPage />} />
          <Route
            path="standing_cross_crunch"
            element={<StandingCrossCrunchPage />}
          />
          <Route
            path="standing_forward_fold"
            element={<StandingForwardFoldPage />}
          />
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
