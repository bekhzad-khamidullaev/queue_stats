import { useMemo, useState } from "react";
import ReportFilters from "../components/ReportFilters.jsx";
import client from "../api/client.js";
import { buildAgentNameMap, buildQueueNameMap, formatAgentName, formatQueueName } from "../utils/displayNames.js";

export default function AnsweredView({ queues, agents }) {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const queueNameMap = useMemo(() => buildQueueNameMap(queues), [queues]);
  const agentNameMap = useMemo(() => buildAgentNameMap(agents), [agents]);

  const loadReport = async (filters) => {
    try {
      setLoading(true);
      setError(null);
      const response = await client.post("/reports/answered/", filters);
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
        <h2 className="card__title">Принятые вызовы</h2>
        <ReportFilters queues={queues} agents={agents} onSubmit={loadReport} requireAgents loading={loading} />
        {error && <div className="error">Не удалось загрузить данные: {error.message}</div>}
        {report && (
          <>
            <div className="stats-grid">
              <div className="stats-card">
                <div className="stats-card__label">Всего вызовов</div>
                <div className="stats-card__value">{report.summary.total_calls}</div>
              </div>
              <div className="stats-card">
                <div className="stats-card__label">Среднее время разговора, сек</div>
                <div className="stats-card__value">{report.summary.avg_talk_time}</div>
              </div>
              <div className="stats-card">
                <div className="stats-card__label">Среднее ожидание, сек</div>
                <div className="stats-card__value">{report.summary.avg_hold_time}</div>
              </div>
              <div className="stats-card">
                <div className="stats-card__label">Всего минут разговора</div>
                <div className="stats-card__value">{report.summary.total_talk_minutes}</div>
              </div>
            </div>
            <div className="card">
              <h3 className="card__title">Агенты</h3>
              <table className="table">
                <thead>
                  <tr>
                    <th>Агент</th>
                    <th>Вызовы</th>
                    <th>% вызовов</th>
                    <th>Минуты разговора</th>
                    <th>% времени</th>
                    <th>Средний разговор, сек</th>
                    <th>Ожидание, сек</th>
                    <th>Среднее ожидание, сек</th>
                  </tr>
                </thead>
                <tbody>
                  {report.agents.map((agent) => (
                    <tr key={agent.agent}>
                      <td>{formatAgentName(agent.agent, agentNameMap)}</td>
                      <td>{agent.calls}</td>
                      <td>{agent.calls_percent}</td>
                      <td>{Math.round(agent.talk_time_total / 60)}</td>
                      <td>{agent.talk_time_percent}</td>
                      <td>{agent.talk_time_avg}</td>
                      <td>{agent.hold_time_total}</td>
                      <td>{agent.hold_time_avg}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="card">
              <h3 className="card__title">Распределение ожидания</h3>
              <table className="table">
                <thead>
                  <tr>
                    <th>Очередь</th>
                    <th>0-5 сек</th>
                    <th>6-10 сек</th>
                    <th>11-15 сек</th>
                    <th>16-20 сек</th>
                    <th>21-25 сек</th>
                    <th>26-30 сек</th>
                    <th>31+ сек</th>
                    <th>Всего</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(report.response_distribution).map(([queue, stats]) => (
                    <tr key={queue}>
                      <td>{formatQueueName(queue, queueNameMap)}</td>
                      <td>{stats["0-5"]}</td>
                      <td>{stats["6-10"]}</td>
                      <td>{stats["11-15"]}</td>
                      <td>{stats["16-20"]}</td>
                      <td>{stats["21-25"]}</td>
                      <td>{stats["26-30"]}</td>
                      <td>{stats["31+"]}</td>
                      <td>{stats.total}</td>
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
