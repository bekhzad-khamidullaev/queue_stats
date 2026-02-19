import { useMemo, useState } from "react";
import ReportFilters from "../components/ReportFilters.jsx";
import client from "../api/client.js";
import { buildAgentNameMap, buildQueueNameMap, formatAgentName, formatQueueName } from "../utils/displayNames.js";

export default function RawEventsView({ queues, agents }) {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const queueNameMap = useMemo(() => buildQueueNameMap(queues), [queues]);
  const agentNameMap = useMemo(() => buildAgentNameMap(agents), [agents]);

  const loadEvents = async (filters) => {
    try {
      setLoading(true);
      setError(null);
      const payload = { ...filters, agents: undefined };
      const response = await client.post("/reports/raw/", payload);
      setEvents(response.data.events ?? []);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="view">
      <div className="card">
        <h2 className="card__title">Сырые события очередей</h2>
        <ReportFilters queues={queues} agents={[]} onSubmit={loadEvents} loading={loading} />
        {error && <div className="error">Ошибка загрузки: {error.message}</div>}
        <div className="card">
          <h3 className="card__title">Последние записи</h3>
          <table className="table">
            <thead>
              <tr>
                <th>Время</th>
                <th>Вызов</th>
                <th>Очередь</th>
                <th>Агент</th>
                <th>Событие</th>
                <th>Data1</th>
                <th>Data2</th>
                <th>Data3</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event, index) => (
                <tr key={`${event.callid}-${index}`}>
                  <td>{event.time}</td>
                  <td>{event.callid}</td>
                  <td>{formatQueueName(event.queuename, queueNameMap)}</td>
                  <td>{formatAgentName(event.agent, agentNameMap)}</td>
                  <td>{event.event}</td>
                  <td>{event.data1}</td>
                  <td>{event.data2}</td>
                  <td>{event.data3}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
