import { useMemo, useState } from "react";
import client from "../api/client.js";
import { buildAgentNameMap, buildQueueNameMap, formatAgentName, formatQueueName } from "../utils/displayNames.js";

const today = new Date();
const formatDate = (date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;

export default function SearchView({ queues, agents }) {
  const [start, setStart] = useState(`${formatDate(today)} 00:00:00`);
  const [end, setEnd] = useState(`${formatDate(today)} 23:59:59`);
  const [uniqueid, setUniqueid] = useState("");
  const [callerid, setCallerid] = useState("");
  const [alltime, setAlltime] = useState(false);
  const [includeRingNoAnswer, setIncludeRingNoAnswer] = useState(true);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const queueNameMap = useMemo(() => buildQueueNameMap(queues), [queues]);
  const agentNameMap = useMemo(() => buildAgentNameMap(agents), [agents]);

  const submit = async (e) => {
    e.preventDefault();
    try {
      setLoading(true);
      setError(null);
      const response = await client.post("/reports/search/", {
        start,
        end,
        uniqueid: uniqueid || undefined,
        callerid: callerid || undefined,
        alltime,
        include_ringnoanswer: includeRingNoAnswer,
      });
      setEvents(response.data.events || []);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="view">
      <div className="card">
        <h2 className="card__title">Поиск по событиям очереди</h2>
        <form className="filters" onSubmit={submit}>
          <div className="filters__column">
            <label htmlFor="start">Начало</label>
            <input id="start" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="filters__column">
            <label htmlFor="end">Конец</label>
            <input id="end" value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>
          <div className="filters__column">
            <label htmlFor="uniqueid">UniqueID</label>
            <input id="uniqueid" value={uniqueid} onChange={(e) => setUniqueid(e.target.value)} />
          </div>
          <div className="filters__column">
            <label htmlFor="callerid">CallerID</label>
            <input id="callerid" value={callerid} onChange={(e) => setCallerid(e.target.value)} />
          </div>
          <div className="filters__column">
            <label>
              <input type="checkbox" checked={alltime} onChange={(e) => setAlltime(e.target.checked)} /> Все время
            </label>
            <label>
              <input
                type="checkbox"
                checked={includeRingNoAnswer}
                onChange={(e) => setIncludeRingNoAnswer(e.target.checked)}
              />
              Показать RINGNOANSWER
            </label>
          </div>
          <div className="filters__column">
            <label>&nbsp;</label>
            <button type="submit" disabled={loading}>{loading ? "Поиск..." : "Найти"}</button>
          </div>
        </form>
        {error && <div className="error">Ошибка: {error.message}</div>}
        <div className="card" style={{ marginTop: "1rem" }}>
          <h3 className="card__title">Результат ({events.length})</h3>
          <table className="table">
            <thead>
              <tr>
                <th>Время</th>
                <th>CallID</th>
                <th>Очередь</th>
                <th>Агент</th>
                <th>Событие</th>
                <th>Data1</th>
                <th>Data2</th>
                <th>Data3</th>
                <th>Data4</th>
                <th>Data5</th>
              </tr>
            </thead>
            <tbody>
              {events.map((row, idx) => (
                <tr key={`${row.callid}-${idx}`}>
                  <td>{row.time}</td>
                  <td>{row.callid}</td>
                  <td>{formatQueueName(row.queuename, queueNameMap)}</td>
                  <td>{formatAgentName(row.agent, agentNameMap)}</td>
                  <td>{row.event}</td>
                  <td>{row.data1}</td>
                  <td>{row.data2}</td>
                  <td>{row.data3}</td>
                  <td>{row.data4}</td>
                  <td>{row.data5}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
