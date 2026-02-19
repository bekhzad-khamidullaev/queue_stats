import { useMemo, useState } from "react";
import ReportFilters from "../components/ReportFilters.jsx";
import client from "../api/client.js";
import { buildAgentNameMap, formatAgentName } from "../utils/displayNames.js";

export default function AgentDailyView({ queues, agents }) {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const agentNameMap = useMemo(() => buildAgentNameMap(agents), [agents]);

  const loadReport = async (filters) => {
    try {
      setLoading(true);
      setError(null);
      const response = await client.post("/reports/areport/", filters);
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
        <h2 className="card__title">Распределение по агентам (по датам)</h2>
        <ReportFilters queues={queues} agents={agents} onSubmit={loadReport} requireAgents loading={loading} />
        {error && <div className="error">Ошибка загрузки: {error.message}</div>}
        {report && (
          <table className="table" style={{ marginTop: "1rem" }}>
            <thead>
              <tr>
                <th>Дата</th>
                <th>Оператор</th>
                <th>Разговаривает, мин</th>
                <th>Пауза, мин</th>
                <th>Свободен, мин</th>
                <th>На удержании, мин</th>
                <th>Вызовы, шт</th>
                <th>Средний разговор, сек</th>
                <th>RNA, шт</th>
              </tr>
            </thead>
            <tbody>
              {(report.rows || []).map((row) => (
                <tr key={`${row.day}-${row.agent}`}>
                  <td>{row.day}</td>
                  <td>{formatAgentName(row.agent, agentNameMap)}</td>
                  <td>{row.incall_min}</td>
                  <td>{row.pause_min}</td>
                  <td>{row.free_min}</td>
                  <td>{row.transfer_hold_min}</td>
                  <td>{row.calls}</td>
                  <td>{row.avg_talk_sec}</td>
                  <td>{row.rna}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
