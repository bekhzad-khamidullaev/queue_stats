import { useMemo, useState } from "react";
import ReportFilters from "../components/ReportFilters.jsx";
import client from "../api/client.js";
import { buildQueueNameMap, formatQueueName } from "../utils/displayNames.js";

const formatDate = (iso) => (iso ? new Date(iso).toLocaleString("ru-RU") : "");

export default function UnansweredCdrView({ queues, agents }) {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [calleridSearch, setCalleridSearch] = useState("");
  const queueNameMap = useMemo(() => buildQueueNameMap(queues), [queues]);

  const loadReport = async (filters) => {
    try {
      setLoading(true);
      setError(null);
      const response = await client.post("/reports/unanswered-cdr/", {
        ...filters,
        agents: undefined,
        callerid_search: calleridSearch || undefined,
      });
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
        <h2 className="card__title">Непринятые вызовы (CDR)</h2>
        <ReportFilters queues={queues} agents={agents} onSubmit={loadReport} loading={loading} />
        <div style={{ marginTop: "0.75rem" }}>
          <label htmlFor="callerid_search">CallerID фильтр</label>
          <input
            id="callerid_search"
            value={calleridSearch}
            onChange={(e) => setCalleridSearch(e.target.value)}
            placeholder="например 7903"
          />
        </div>
        {error && <div className="error">Ошибка загрузки: {error.message}</div>}
        {report && (
          <>
            <div className="muted" style={{ marginTop: "1rem" }}>Всего записей: {report.count || 0}</div>
            <table className="table">
              <thead>
                <tr>
                  <th>Время</th>
                  <th>CallerID</th>
                  <th>Очередь</th>
                  <th>Событие</th>
                  <th>Ожидание (сек)</th>
                  <th>Позиция входа</th>
                  <th>Позиция выхода</th>
                  <th>CallID</th>
                </tr>
              </thead>
              <tbody>
                {(report.data || []).map((row, idx) => (
                  <tr key={`${row.callid}-${idx}`}>
                    <td>{formatDate(row.time)}</td>
                    <td>{row.callerid || row.data2}</td>
                    <td>{formatQueueName(row.queuename, queueNameMap)}</td>
                    <td>{row.event}</td>
                    <td>{row.data3}</td>
                    <td>{row.data2}</td>
                    <td>{row.data1}</td>
                    <td>{row.callid}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
    </div>
  );
}
