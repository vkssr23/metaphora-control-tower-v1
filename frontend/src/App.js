import React, { useState, useEffect } from "react";
import "./App.css";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./lib/auth";
import { ThemeProvider } from "./lib/theme";
import Shell from "./components/Shell";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import OperationsBoard from "./pages/OperationsBoard";
import Loads from "./pages/Loads";
import LoadExecution from "./pages/LoadExecution";
import Trucks from "./pages/Trucks";
import Drivers from "./pages/Drivers";
import Dispatch from "./pages/Dispatch";
import InTransit from "./pages/InTransit";
import WeatherRoad from "./pages/WeatherRoad";
import FuelPlanner from "./pages/FuelPlanner";
import Telematics from "./pages/Telematics";
import Documents from "./pages/Documents";
import Invoices from "./pages/Invoices";
import TripPnL from "./pages/TripPnL";
import { DriverScorecard, TruckScorecard } from "./pages/Scorecards";
import Reports from "./pages/Reports";
import AIAssistant from "./pages/AIAssistant";
import Settings from "./pages/Settings";
import LoadAnalysis from "./pages/LoadAnalysis";
import Compliance from "./pages/Compliance";
import ActionCenter from "./pages/ActionCenter";

function Protected({ children }) {
  const { user } = useAuth();
  const loc = useLocation();
  if (!user) return <Navigate to="/login" state={{ from: loc }} replace />;
  return children;
}

// Metaphora Secure SSO handoff: a ?metaphora_sso_code= in the URL means the
// user just clicked "Metaphora TMS" from Metaphora Secure and needs to be
// exchanged into a real session before the router renders anything. Without
// this gate, <Protected>'s synchronous (localStorage-only) user check would
// redirect to /login before the async exchange below ever resolves.
function MetaphoraSsoGate({ children }) {
  const { exchangeMetaphoraCode } = useAuth();
  const [ready, setReady] = useState(
    () => !new URLSearchParams(window.location.search).has("metaphora_sso_code")
  );

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("metaphora_sso_code");
    if (!code) return;
    (async () => {
      try {
        await exchangeMetaphoraCode(code);
      } catch {
        // Invalid/expired code — fall through to the normal /login redirect.
      } finally {
        params.delete("metaphora_sso_code");
        const q = params.toString();
        window.history.replaceState({}, "", window.location.pathname + (q ? `?${q}` : ""));
        setReady(true);
      }
    })();
  }, [exchangeMetaphoraCode]);

  if (!ready) return null;
  return children;
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <MetaphoraSsoGate>
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route path="/" element={<Protected><Shell /></Protected>}>
                <Route index element={<Dashboard />} />
                <Route path="analyze" element={<LoadAnalysis />} />
                <Route path="board" element={<OperationsBoard />} />
                <Route path="loads" element={<Loads />} />
                <Route path="loads/:id" element={<LoadExecution />} />
                <Route path="trucks" element={<Trucks />} />
                <Route path="drivers" element={<Drivers />} />
                <Route path="compliance" element={<Compliance />} />
                <Route path="action-center" element={<ActionCenter />} />
                <Route path="dispatch" element={<Dispatch />} />
                <Route path="in-transit" element={<InTransit />} />
                <Route path="weather" element={<WeatherRoad />} />
                <Route path="fuel" element={<FuelPlanner />} />
                <Route path="telematics" element={<Telematics />} />
                <Route path="documents" element={<Documents />} />
                <Route path="invoices" element={<Invoices />} />
                <Route path="pnl" element={<TripPnL />} />
                <Route path="driver-scorecard" element={<DriverScorecard />} />
                <Route path="truck-scorecard" element={<TruckScorecard />} />
                <Route path="reports" element={<Reports />} />
                <Route path="ai" element={<AIAssistant />} />
                <Route path="settings" element={<Settings />} />
              </Route>
            </Routes>
          </MetaphoraSsoGate>
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
}
