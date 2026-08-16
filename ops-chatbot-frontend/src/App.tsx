import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Home from "./pages/Home";
import AppLayout from "./components/AppLayout";
import Register from "./pages/Register";
import Analytics from "./pages/Analytics";
import Cohorts from "./pages/Cohorts";
import Guide from "./pages/Guide";
import KnowledgeBase from "./pages/Knowledgebase";
import Reminders from "./pages/Reminders";
import Settings from "./pages/Settings";
import Escalations from "./pages/Escalations";
import Users from "./pages/Users";
import Dashboard from "./pages/Dashboard";
import Chat from "./pages/Chat";





function ProtectedRoute({ children }: { children: JSX.Element }) {
  const { user, loading } = useAuth();
  if (loading) return <div>Loading...</div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          {<Route path="/register" element={<Register />} />}

          <Route
            path="/app"
            element={
              <ProtectedRoute>
                <AppLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<Home />} />
            {<Route path="analytics" element={<Analytics />} />}
            {<Route path="cohorts" element={<Cohorts />} />}
            {<Route path="guide" element={<Guide />} />}
            {<Route path="kb" element={<KnowledgeBase />} />}
            {<Route path="reminders" element={<Reminders />} />}
            {<Route path="settings" element={<Settings />} />}
            {<Route path="escalations" element={<Escalations />} />}
            {<Route path="users" element={<Users />} />}
            {<Route path="dashboard" element={<Dashboard />} />}
            {<Route path="chat" element={<Chat />} />}
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}