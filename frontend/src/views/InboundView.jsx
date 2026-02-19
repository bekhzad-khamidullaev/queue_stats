import { useState } from "react";
import ReportFilters from "../components/ReportFilters.jsx";
import client from "../api/client.js";

export default function InboundView({ queues, agents }) {
  const [mode, setMode] = useState("dids");
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = async (filters) => {
    try {
      setLoading(true);
      setError(null);
      const path = mode === "dids" ? "/reports/dids/" : "/reports/trunks/";
      const response = await client.post(path, { ...filters, agents: undefined });
      setData(response.data.data || []);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="view">
      <div className="card">
        <h2 className="card__title">Входящие вызовы</h2>
        <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
          <button className="button" onClick={() => setMode("dids")}>По номерам (DID)</button>
          <button className="button" onClick={() => setMode("trunks")}>По транкам</button>
        </div>
        <ReportFilters queues={queues} agents={agents} onSubmit={load} loading={loading} />
        {error && <div className="error">Ошибка: {error.message}</div>}
        <table className="table" style={{ marginTop: "1rem" }}>
          <thead>
            <tr>
              <th>{mode === "dids" ? "Номер (DID)" : "Транк"}</th>
              <th>Пропущено</th>
              <th>Отвечено</th>
              <th>Всего</th>
            </tr>
          </thead>
          <tbody>
            {data.map((row) => (
              <tr key={row.did || row.trunk}>
                <td>{row.did || row.trunk}</td>
                <td>{row.ABN || 0}</td>
                <td>{row.ANS || 0}</td>
                <td>{row.ALL || 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
