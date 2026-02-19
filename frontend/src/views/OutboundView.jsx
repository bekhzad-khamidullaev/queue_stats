import { useMemo, useState } from "react";
import ReportFilters from "../components/ReportFilters.jsx";
import client from "../api/client.js";
import { buildAgentNameMap, formatAgentName } from "../utils/displayNames.js";

const formatDate = (iso) => (iso ? new Date(iso).toLocaleString("ru-RU") : "");
const formatDuration = (seconds) => {
  const total = Number(seconds || 0);
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${mins}:${String(secs).padStart(2, "0")}`;
};

export default function OutboundView({ queues, agents }) {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const agentNameMap = useMemo(() => buildAgentNameMap(agents), [agents]);

  const loadReport = async (filters) => {
    try {
      setLoading(true);
      setError(null);
      const response = await client.post("/reports/outbound/", filters);
      setReport(response.data);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  const overviewRows = useMemo(() => {
    if (!report?.overview) {
      return [];
    }
    return Object.entries(report.overview).map(([agent, row]) => ({
      agent,
      answered: row.ANSWERED || 0,
      no_answer: row["NO ANSWER"] || 0,
      busy: row.BUSY || 0,
      total: row.TOTAL || 0,
    }));
  }, [report]);

  return (
    <div className="view">
      <div className="card">
        <h2 className="card__title">Исходящие вызовы</h2>
        <ReportFilters queues={queues} agents={agents} onSubmit={loadReport} requireAgents loading={loading} />
        {error && <div className="error">Ошибка загрузки: {error.message}</div>}
        {report && (
          <>
            <div className="card">
              <h3 className="card__title">Обзор по агентам</h3>
              <table className="table">
                <thead>
                  <tr>
                    <th>Агент</th>
                    <th>Отвечено</th>
                    <th>Не ответили</th>
                    <th>Занято</th>
                    <th>Всего</th>
                  </tr>
                </thead>
                <tbody>
                  {overviewRows.map((row) => (
                    <tr key={row.agent}>
                      <td>{formatAgentName(row.agent, agentNameMap)}</td>
                      <td>{row.answered}</td>
                      <td>{row.no_answer}</td>
                      <td>{row.busy}</td>
                      <td>{row.total}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="card">
              <h3 className="card__title">Детализация</h3>
              <table className="table">
                <thead>
                  <tr>
                    <th>Дата</th>
                    <th>Агент</th>
                    <th>Номер</th>
                    <th>Назначение</th>
                    <th>Разговор</th>
                    <th>Статус</th>
                  </tr>
                </thead>
                <tbody>
                  {(report.data || []).map((row) => (
                    <tr key={`${row.uniqueid}-${row.calldate}`}>
                      <td>{formatDate(row.calldate)}</td>
                      <td>{formatAgentName(row.cnum || row.cnam, agentNameMap)}</td>
                      <td>{row.src}</td>
                      <td>{row.dst}</td>
                      <td>{formatDuration(row.billsec)}</td>
                      <td>{row.disposition}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
