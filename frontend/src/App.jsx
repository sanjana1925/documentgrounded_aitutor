import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AppProvider } from "./store";
import DashboardPage from "./pages/DashboardPage";
import TutorPage from "./pages/TutorPage";
import QuizPage from "./pages/QuizPage";
import EvaluationPage from "./pages/EvaluationPage";

export default function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/tutor" replace />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/tutor" element={<TutorPage />} />
          <Route path="/quiz" element={<QuizPage />} />
          <Route path="/evaluation" element={<EvaluationPage />} />
          <Route path="*" element={<Navigate to="/tutor" replace />} />
        </Routes>
      </BrowserRouter>
    </AppProvider>
  );
}
