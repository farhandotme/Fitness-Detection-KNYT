import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

import Layout from "./conponents/Layout";
import FingerPage from "./pages/FingerPage";
import RepPage from "./pages/RepPage";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/fingers" replace />} />
          <Route path="fingers" element={<FingerPage />} />
          <Route path="reps" element={<RepPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
