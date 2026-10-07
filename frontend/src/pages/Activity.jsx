import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Badge, LoadError, Tabs } from "../components/ui.jsx";
import { fmtDate } from "../util.js";

export default function Activity() {
  const [tab, setTab] = useState("audit");
  const [audit, setAudit] = useState([]);
  const [emails, setEmails] = useState([]);
  const [actor, setActor] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = async () => {
    setLoading(true);
    try {
      const [auditRows, emailRows] = await Promise.all([
        api.get(`/audit?limit=300${actor ? `&actor=${encodeURIComponent(actor)}` : ""}`),
        api.get("/emails"),
      ]);
      setAudit(auditRows);
      setEmails(emailRows);
      setError("");
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, [actor]);
  return (
    <div>
      <h1>Audit log & outbox</h1>
      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "audit", label: "Audit log", count: audit.length },
          { id: "emails", label: "Email outbox", count: emails.length },
        ]}
      />
      {error && <LoadError error={`Couldn’t load activity: ${error}`} onRetry={load} />}
      {loading && <p role="status">Loading activity…</p>}
      {!loading && !error && <>
      {tab === "audit" && (
        <div className="card">
          <div className="row">
            <select value={actor} onChange={(e) => setActor(e.target.value)}>
              <option value="">All actors</option>
              <option value="agent">AI agent only</option>
            </select>
          </div>
          <table className="table compact">
            <thead>
              <tr>
                <th>Time</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Entity</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {audit.map((a) => (
                <tr key={a.id}>
                  <td className="nowrap">{fmtDate(a.ts)}</td>
                  <td>{a.actor}</td>
                  <td>
                    <code>{a.action}</code>
                  </td>
                  <td>
                    {a.entity_type} {a.entity_id ? `#${a.entity_id}` : ""}
                  </td>
                  <td className="small mono">{JSON.stringify(a.details)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {tab === "emails" && (
        <div className="card">
          {emails.map((e) => (
            <details key={e.id}>
              <summary>
                {fmtDate(e.created_at)} · to <strong>{e.to}</strong> · {e.subject} <Badge value={e.kind} /> <Badge value={e.status} />
              </summary>
              <pre className="resume">{e.body}</pre>
            </details>
          ))}
          {emails.length === 0 && <p className="muted">No emails yet.</p>}
        </div>
      )}
      </>}
    </div>
  );
}
