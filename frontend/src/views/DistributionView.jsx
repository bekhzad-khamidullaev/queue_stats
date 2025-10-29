import { useState } from "react";
import ReportFilters from "../components/ReportFilters.jsx";
import client from "../api/client.js";

export default function DistributionView({ queues, agents }) {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const loadReport = async (filters) => {
    try {
      setLoading(true);
      setError(null);
      const response = await client.post("/reports/distribution/", filters);
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
        <h2 className="card__title">Распределение вызовов</h2>
        <ReportFilters queues={queues} agents={agents} onSubmit={loadReport} requireAgents loading={loading} />
        {error && <div className="error">Ошибка загрузки: {error.message}</div>}
        {report && (
          <>
            <div className="card">
              <h3 className="card__title">По часам</h3>
              <table className="table">
                <thead>
                  <tr>
                    <th>Очередь</th>
                    <th>Час</th>
                    <th>Вызовы</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(report.timeline).map(([queue, items]) =>
                    items.map((item) => (
                      <tr key={`${queue}-${item.hour}`}>
                        <td>{queue}</td>
                        <td>{item.hour}</td>
                        <td>{item.calls}</td>
                      </tr>
                    )),
                  )}
                </tbody>
              </table>
            </div>
            <div className="card">
              <h3 className="card__title">Вызовы по агентам</h3>
              <table className="table">
                <thead>
                  <tr>
                    <th>Агент</th>
                    <th>Вызовы</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(report.agent_calls).map(([agent, count]) => (
                    <tr key={agent}>
                      <td>{agent}</td>
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

