import { useState } from "react";
import ReportFilters from "../components/ReportFilters.jsx";
import client from "../api/client.js";

const HOURS = Array.from({ length: 24 }, (_, i) => i);

export default function QueueHourlyView({ queues, agents }) {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const loadReport = async (filters) => {
    try {
      setLoading(true);
      setError(null);
      const response = await client.post("/reports/qreport/", { ...filters, agents: undefined });
      setReport(response.data);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="view">
      <div className="card">
        <h2 className="card__title">Распределение по очередям (по часам)</h2>
        <ReportFilters queues={queues} agents={agents} onSubmit={loadReport} loading={loading} />
        {error && <div className="error">Ошибка загрузки: {error.message}</div>}
        {report && (
          <table className="table" style={{ marginTop: "1rem" }}>
            <thead>
              <tr>
                <th>Дата</th>
                <th>Показатель</th>
                {HOURS.map((h) => (
                  <th key={h}>{String(h).padStart(2, "0")}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(report.rows || []).flatMap((row) => [
                <tr key={`${row.day}-dep`}>
                  <td rowSpan={2}>{row.day}</td>
                  <td>Макс. кол-во абонентов в очереди</td>
                  {HOURS.map((h) => (
                    <td key={`dep-${row.day}-${h}`}>{row.dep?.[String(h)] ?? 0}</td>
                  ))}
                </tr>,
                <tr key={`${row.day}-agents`}>
                  <td>Кол-во свободных операторов</td>
                  {HOURS.map((h) => (
                    <td key={`ag-${row.day}-${h}`}>{row.agents?.[String(h)] ?? 0}</td>
                  ))}
                </tr>,
              ])}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
