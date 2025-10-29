import { useState } from "react";
import ReportFilters from "../components/ReportFilters.jsx";
import client from "../api/client.js";

export default function SummaryView({ queues }) {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const loadReport = async (filters) => {
    try {
      setLoading(true);
      setError(null);
      const response = await client.post("/reports/summary/", { ...filters, agents: undefined });
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
        <h2 className="card__title">Общий отчет</h2>
        <ReportFilters queues={queues} agents={[]} onSubmit={loadReport} loading={loading} />
        {error && <div className="error">Ошибка загрузки: {error.message}</div>}
        {report && (
          <>
            <div className="stats-grid">
              <div className="stats-card">
                <div className="stats-card__label">Всего вызовов</div>
                <div className="stats-card__value">{report.total_calls}</div>
              </div>
              <div className="stats-card">
                <div className="stats-card__label">Принято</div>
                <div className="stats-card__value">
                  {report.answered_calls} <span className="muted">({report.service_level}% SLA)</span>
                </div>
              </div>
              <div className="stats-card">
                <div className="stats-card__label">Отбои</div>
                <div className="stats-card__value">{report.abandoned_calls}</div>
              </div>
              <div className="stats-card">
                <div className="stats-card__label">Таймауты</div>
                <div className="stats-card__value">{report.timeout_calls}</div>
              </div>
              <div className="stats-card">
                <div className="stats-card__label">Среднее ожидание, сек</div>
                <div className="stats-card__value">{report.avg_wait_time}</div>
              </div>
              <div className="stats-card">
                <div className="stats-card__label">Средний разговор, сек</div>
                <div className="stats-card__value">{report.avg_talk_time}</div>
              </div>
            </div>
            <div className="card">
              <h3 className="card__title">Вызовы по очередям</h3>
              <table className="table">
                <thead>
                  <tr>
                    <th>Очередь</th>
                    <th>Вызовы</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(report.calls_per_queue).map(([queue, count]) => (
                    <tr key={queue}>
                      <td>{queue}</td>
                      <td>{count}</td>
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

