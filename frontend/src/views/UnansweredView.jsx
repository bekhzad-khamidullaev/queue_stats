import { useState } from "react";
import ReportFilters from "../components/ReportFilters.jsx";
import client from "../api/client.js";

export default function UnansweredView({ queues }) {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const loadReport = async (filters) => {
    try {
      setLoading(true);
      setError(null);
      const response = await client.post("/reports/unanswered/", { ...filters, agents: undefined });
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
        <h2 className="card__title">Непринятые вызовы</h2>
        <ReportFilters queues={queues} agents={[]} onSubmit={loadReport} loading={loading} />
        {error && <div className="error">Ошибка загрузки: {error.message}</div>}
        {report && (
          <>
            <div className="stats-grid">
              <div className="stats-card">
                <div className="stats-card__label">Всего непринятых</div>
                <div className="stats-card__value">{report.summary.total_unanswered}</div>
              </div>
              <div className="stats-card">
                <div className="stats-card__label">Среднее ожидание, сек</div>
                <div className="stats-card__value">{report.summary.avg_wait_before_disconnect}</div>
              </div>
              <div className="stats-card">
                <div className="stats-card__label">Позиция при старте</div>
                <div className="stats-card__value">{report.summary.avg_queue_position_start}</div>
              </div>
              <div className="stats-card">
                <div className="stats-card__label">Позиция при прерывании</div>
                <div className="stats-card__value">{report.summary.avg_queue_position_disconnect}</div>
              </div>
            </div>
            <div className="card">
              <h3 className="card__title">Причины</h3>
              <div className="stats-grid">
                <div className="stats-card">
                  <div className="stats-card__label">Отбой клиента</div>
                  <div className="stats-card__value">{report.reasons.abandon_calls}</div>
                  <div className="muted">{report.summary.abandon_percent}%</div>
                </div>
                <div className="stats-card">
                  <div className="stats-card__label">Таймаут</div>
                  <div className="stats-card__value">{report.reasons.timeout_calls}</div>
                  <div className="muted">{report.summary.timeout_percent}%</div>
                </div>
              </div>
            </div>
            <div className="card">
              <h3 className="card__title">Распределение ожидания</h3>
              <table className="table">
                <thead>
                  <tr>
                    <th>Очередь</th>
                    <th>0-10 сек</th>
                    <th>11-20 сек</th>
                    <th>21-30 сек</th>
                    <th>31-40 сек</th>
                    <th>41-50 сек</th>
                    <th>51-60 сек</th>
                    <th>61+ сек</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(report.distribution).map(([queue, stats]) => (
                    <tr key={queue}>
                      <td>{queue}</td>
                      <td>{stats["0-10"]}</td>
                      <td>{stats["11-20"]}</td>
                      <td>{stats["21-30"]}</td>
                      <td>{stats["31-40"]}</td>
                      <td>{stats["41-50"]}</td>
                      <td>{stats["51-60"]}</td>
                      <td>{stats["61+"]}</td>
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

