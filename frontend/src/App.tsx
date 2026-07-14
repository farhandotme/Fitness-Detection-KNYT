import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

import Layout from "./conponents/Layout";
import FingerPage from "./pages/FingerPage";
import BicepPage from "./pages/BicepPage";
import SquatPage from "./pages/SquatPage";
import PushupPage from "./pages/PushupPage";
import BodyAnalysisPage from "./pages/BodyAnalysisPage";
import ExerciseLibraryPage from "./pages/ExerciseLibraryPage";
import JumpingJackPage from "./pages/JumpingJackPage";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/exercises" replace />} />
          <Route path="exercises" element={<ExerciseLibraryPage />} />
          <Route path="exercises/jumping-jacks" element={<JumpingJackPage />} />
          <Route path="fingers" element={<FingerPage />} />
          <Route path="reps" element={<BicepPage />} />
          <Route path="squat" element={<SquatPage />} />
          <Route path="pushup" element={<PushupPage />} />
          <Route path="body-scan" element={<BodyAnalysisPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
