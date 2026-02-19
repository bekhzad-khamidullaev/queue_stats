import { useState, useMemo } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import ReportFilters from "../components/ReportFilters.jsx";
import { exportDataToCsv } from "../utils/export.js";
import { buildAgentNameMap, buildQueueNameMap, formatAgentName, formatQueueName } from "../utils/displayNames.js";
import client from "../api/client.js";

const CHART_COLORS = ["#2b67f6", "#ff7f50", "#5ed5a7", "#a855f7", "#facc15", "#f97316", "#0ea5e9"];

export default function DistributionView({ queues, agents }) {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const queueNameMap = useMemo(() => buildQueueNameMap(queues), [queues]);
  const agentNameMap = useMemo(() => buildAgentNameMap(agents), [agents]);

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

  const hourlyChartData = useMemo(() => {
    if (!report?.timeline) return [];
    const hourMap = new Map();
    
    Object.entries(report.timeline).forEach(([queue, items]) => {
      items.forEach(item => {
        const hour = item.hour;
        if (!hourMap.has(hour)) {
          hourMap.set(hour, { hour });
        }
        const bucket = hourMap.get(hour);
        bucket[queue] = (bucket[queue] || 0) + item.calls;
      });
    });
    
    return Array.from(hourMap.values()).sort((a, b) => a.hour - b.hour);
  }, [report]);

  const agentChartData = useMemo(() => {
    if (!report?.agent_calls) return [];
    return Object.entries(report.agent_calls)
      .map(([agent, calls]) => ({ agent: formatAgentName(agent, agentNameMap), calls }))
      .sort((a, b) => b.calls - a.calls)
      .slice(0, 15);
  }, [report, agentNameMap]);

  const exportData = () => {
    if (!report) return;
    
    const hourlyData = [];
    Object.entries(report.timeline).forEach(([queue, items]) => {
      items.forEach(item => {
        hourlyData.push({
          "Очередь": formatQueueName(queue, queueNameMap),
          "Час": item.hour,
          "Вызовы": item.calls
        });
      });
    });
    
    exportDataToCsv(`distribution-hourly-${new Date().toISOString().split('T')[0]}.csv`, hourlyData);
  };

  const queueNames = report?.timeline ? Object.keys(report.timeline) : [];
  const queueLabelByName = useMemo(
    () =>
      Object.fromEntries(
        queueNames.map((queueName) => [queueName, formatQueueName(queueName, queueNameMap)]),
      ),
    [queueNames, queueNameMap],
  );

  return (
    <div className="view">
      <div className="card">
        <h2 className="card__title">Распределение вызовов</h2>
        <ReportFilters queues={queues} agents={agents} onSubmit={loadReport} requireAgents loading={loading} />
        
        {report && (
          <button className="button" style={{ marginTop: "1rem" }} onClick={exportData}>
            Экспорт в CSV
          </button>
        )}
        
        {error && <div className="error">Ошибка загрузки: {error.message}</div>}
        
        {report && (
          <>
            <div className="card">
              <h3 className="card__title">Распределение по часам</h3>
              {hourlyChartData.length > 0 ? (
                <div style={{ width: "100%", height: 400 }}>
                  <ResponsiveContainer>
                    <BarChart data={hourlyChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="hour" label={{ value: "Час", position: "insideBottom", offset: -5 }} />
                      <YAxis label={{ value: "Количество вызовов", angle: -90, position: "insideLeft" }} />
                      <Tooltip />
                      <Legend />
                      {queueNames.map((queue, index) => (
                        <Bar 
                          key={queue} 
                          dataKey={queue} 
                          name={queueLabelByName[queue] || queue}
                          fill={CHART_COLORS[index % CHART_COLORS.length]} 
                          stackId="a"
                        />
                      ))}
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="muted">Нет данных для отображения</div>
              )}
            </div>
            
            <div className="card">
              <h3 className="card__title">Топ агентов по вызовам</h3>
              {agentChartData.length > 0 ? (
                <div style={{ width: "100%", height: 400 }}>
                  <ResponsiveContainer>
                    <BarChart data={agentChartData} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis type="number" />
                      <YAxis dataKey="agent" type="category" width={150} />
                      <Tooltip />
                      <Legend />
                      <Bar dataKey="calls" name="Вызовы" fill="#2b67f6" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="muted">Нет данных для отображения</div>
              )}
            </div>
            
            <div className="card">
              <h3 className="card__title">Детализация по часам</h3>
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
                        <td>{formatQueueName(queue, queueNameMap)}</td>
                        <td>{item.hour}:00</td>
                        <td>{item.calls}</td>
                      </tr>
                    )),
                  )}
                </tbody>
              </table>
            </div>
            
            <div className="card">
              <h3 className="card__title">Все агенты</h3>
              <table className="table">
                <thead>
                  <tr>
                    <th>Агент</th>
                    <th>Вызовы</th>
                    <th>Процент</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(report.agent_calls)
                    .sort(([, a], [, b]) => b - a)
                    .map(([agent, count]) => {
                      const total = Object.values(report.agent_calls).reduce((sum, c) => sum + c, 0);
                      const percentage = total > 0 ? ((count / total) * 100).toFixed(1) : 0;
                      return (
                        <tr key={agent}>
                          <td>{formatAgentName(agent, agentNameMap)}</td>
                          <td>{count}</td>
                          <td>{percentage}%</td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
