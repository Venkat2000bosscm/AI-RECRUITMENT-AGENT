import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { Badge } from "../components/ui.jsx";
import { fmtDate, fmtMoney } from "../util.js";

export default function Offers() {
  const [items, setItems] = useState([]);
  useEffect(() => {
    api.get("/offers").then(setItems);
  }, []);
  return (
    <div>
      <h1>Offers & onboarding</h1>
      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>Candidate</th>
              <th>Role</th>
              <th>Compensation</th>
              <th>Start</th>
              <th>Status</th>
              <th>Sent</th>
              <th>Responded</th>
            </tr>
          </thead>
          <tbody>
            {items.map((o) => (
              <tr key={o.id}>
                <td>
                  <Link to={`/candidates/${o.candidate_id}`}>{o.candidate_name}</Link>
                </td>
                <td>{o.job_title}</td>
                <td>{fmtMoney(o.salary, o.currency)}</td>
                <td>{o.start_date}</td>
                <td>
                  <Badge value={o.status} />
                </td>
                <td>{fmtDate(o.sent_at)}</td>
                <td>{fmtDate(o.responded_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {items.length === 0 && <p className="muted">No offers yet.</p>}
      </div>
    </div>
  );
}
