import { useEffect, useState } from "react";
import { api } from "../api.js";
import ApprovalCard from "../components/ApprovalCard.jsx";
import { LoadError, Tabs } from "../components/ui.jsx";

export default function Approvals({ onChange }) {
  const [status, setStatus] = useState("pending");
  const [items, setItems] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = async () => {
    setLoading(true);
    try {
      setItems(await api.get(`/approvals?status=${status}`));
      setError("");
      onChange?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, [status]);
  return (
    <div>
      <h1>Human approvals</h1>
      <p className="muted">
        High-impact actions — publishing JDs, shortlists, interview invitations, hiring decisions, offers and onboarding — only execute after a human
        approves them here. Hiring decisions and offers require a hiring manager or admin.
      </p>
      <Tabs
        active={status}
        onChange={setStatus}
        tabs={["pending", "approved", "rejected", "all"].map((s) => ({ id: s, label: s[0].toUpperCase() + s.slice(1) }))}
      />
      {error && <LoadError error={`Couldn’t load approvals: ${error}`} onRetry={load} />}
      {loading && <p role="status">Loading approvals…</p>}
      {!loading && !error && items.length === 0 && <p className="muted">Nothing here.</p>}
      {!loading && !error && items.map((a) => (
        <ApprovalCard key={a.id} approval={a} onDone={load} />
      ))}
    </div>
  );
}
