import { useEffect, useState } from "react";
import client from "../api/client.js";

export default function RealtimeQueuesView() {
  const [summary, setSummary] = useState([]);
  const [status, setStatus] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    let timeoutId;

    async function load() {
      try {
        const [summaryRes, statusRes] = await Promise.all([
          client.get("/realtime/queue-summary/"),
          client.get("/realtime/queue-status/"),
        ]);
        if (!cancelled) {
          setSummary(summaryRes.data.entries ?? []);
          setStatus(statusRes.data.entries ?? []);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err);
        }
      } finally {
        if (!cancelled) {
          timeoutId = setTimeout(load, 2000);
        }
      }
    }
    load();
    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
    };
  }, []);

  return (
    <div className="view">
      <div className="card">
        <h2 className="card__title">Статус очередей</h2>
        {error && <div className="error">Ошибка обновления: {error.message}</div>}
        <div className="card">
          <h3 className="card__title">Сводка</h3>
          <table className="table">
            <thead>
              <tr>
                <th>Очередь</th>
                <th>Ожидание</th>
                <th>Разговоры</th>
                <th>Свободны</th>
                <th>Всего</th>
              </tr>
            </thead>
            <tbody>
              {summary.map((item, index) => (
                <tr key={index}>
                  <td>{item.Queue}</td>
                  <td>{item.NumWaiting}</td>
                  <td>{item.CallsTaken}</td>
                  <td>{item.AgentsFree}</td>
                  <td>{item.Members}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h3 className="card__title">Агенты</h3>
          <table className="table">
            <thead>
              <tr>
                <th>Очередь</th>
                <th>Агент</th>
                <th>Статус</th>
                <th>Пауза</th>
                <th>Разговоры</th>
                <th>Общий</th>
              </tr>
            </thead>
            <tbody>
              {status.map((item, index) => (
                <tr key={index}>
                  <td>{item.Queue}</td>
                  <td>{item.Interface}</td>
                  <td>{item.Status}</td>
                  <td>{item.Paused}</td>
                  <td>{item.Completed}</td>
                  <td>{item.TalkTime}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

