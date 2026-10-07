import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api, getUserId, setUserId } from "./api.js";
import Dashboard from "./pages/Dashboard.jsx";
import Jobs from "./pages/Jobs.jsx";
import JobDetail from "./pages/JobDetail.jsx";
import CandidateDetail from "./pages/CandidateDetail.jsx";
import Approvals from "./pages/Approvals.jsx";
import Interviews from "./pages/Interviews.jsx";
import Offers from "./pages/Offers.jsx";
import Activity from "./pages/Activity.jsx";
import Pipeline from "./pages/Pipeline.jsx";

const NAV = [
  ["/", "Dashboard"],
  ["/jobs", "Requisitions"],
  ["/pipeline", "Candidate pipeline"],
  ["/approvals", "Approvals"],
  ["/interviews", "Interviews"],
  ["/offers", "Offers & Onboarding"],
  ["/activity", "Audit & Outbox"],
];

export default function App() {
  const [users, setUsers] = useState([]);
  const [userId, setUid] = useState(getUserId());
  const [config, setConfig] = useState(null);
  const [pending, setPending] = useState(0);

  const refreshMeta = () => {
    api.get("/config").then(setConfig);
    api.get("/approvals?status=pending").then((a) => setPending(a.length));
  };

  useEffect(() => {
    api.get("/users").then(setUsers);
    refreshMeta();
    const t = setInterval(refreshMeta, 5000);
    return () => clearInterval(t);
  }, []);

  const switchUser = (id) => {
    setUserId(id);
    setUid(id);
    window.location.reload();
  };

  const togglePause = async () => {
    await api.post("/agent/pause", { paused: !config.agent_paused });
    refreshMeta();
  };

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <span className="logo">AI</span>
          <div>
            <div className="brand-title">Recruitment Assistant</div>
            <div className="brand-sub">Human-in-the-loop agent</div>
          </div>
        </div>
        <nav>
          {NAV.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => (isActive ? "nav active" : "nav")}>
              {label}
              {to === "/approvals" && pending > 0 && <span className="nav-count">{pending}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <label className="small">
            Signed in as
            <select value={userId} onChange={(e) => switchUser(e.target.value)}>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name} — {u.role}
                </option>
              ))}
            </select>
          </label>
          {config && (
            <>
              <div className="small muted">
                AI mode:{" "}
                <span className={`badge ${config.llm_mode === "llm" ? "b-strong_match" : "b-partial_match"}`}>
                  {config.llm_mode === "llm" ? `LLM (${config.llm_model})` : "Offline templates"}
                </span>
              </div>
              <button className={`btn ${config.agent_paused ? "primary" : "danger"} full`} onClick={togglePause}>
                {config.agent_paused ? "Resume agent" : "Pause agent (all jobs)"}
              </button>
            </>
          )}
        </div>
      </aside>
      <main className="content">
        {config?.agent_paused && <div className="banner">Agent is paused. No automated actions will run until HR resumes it.</div>}
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/pipeline" element={<Pipeline />} />
          <Route path="/jobs/:id" element={<JobDetail onChange={refreshMeta} />} />
          <Route path="/candidates/:id" element={<CandidateDetail onChange={refreshMeta} />} />
          <Route path="/approvals" element={<Approvals onChange={refreshMeta} />} />
          <Route path="/interviews" element={<Interviews />} />
          <Route path="/offers" element={<Offers />} />
          <Route path="/activity" element={<Activity />} />
          <Route path="*" element={<div><h1>Page not found</h1><p className="muted">This page doesn’t exist or may have moved.</p><NavLink to="/">Return to dashboard</NavLink></div>} />
        </Routes>
      </main>
    </div>
  );
}
