import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

import Layout from "./conponents/Layout";
import FingerPage from "./pages/FingerPage";
import BicepPage from "./pages/BicepPage";
import SquatPage from "./pages/SquatPage";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/fingers" replace />} />
          <Route path="fingers" element={<FingerPage />} />
          <Route path="reps" element={<BicepPage />} />
          <Route path="squat" element={<SquatPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
