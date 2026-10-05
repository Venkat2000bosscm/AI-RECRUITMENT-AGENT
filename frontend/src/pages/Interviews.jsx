import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { Badge } from "../components/ui.jsx";
import { fmtDate } from "../util.js";

export default function Interviews() {
  const [items, setItems] = useState([]);
  useEffect(() => {
    api.get("/interviews").then(setItems);
  }, []);
  return (
    <div>
      <h1>Interviews</h1>
      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>When</th>
              <th>Candidate</th>
              <th>Role</th>
              <th>Round</th>
              <th>Interviewer</th>
              <th>Status</th>
              <th>Feedback</th>
            </tr>
          </thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.id}>
                <td>{fmtDate(i.start_time)}</td>
                <td>
                  <Link to={`/candidates/${i.candidate_id}`}>{i.candidate_name}</Link>
                </td>
                <td>{i.job_title}</td>
                <td>{i.round_name}</td>
                <td>{i.interviewer_name}</td>
                <td>
                  <Badge value={i.status} />
                </td>
                <td className="small">{i.feedback_summary || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {items.length === 0 && <p className="muted">No interviews yet. Approve a shortlist and the agent will propose interview slots.</p>}
      </div>
    </div>
  );
}
