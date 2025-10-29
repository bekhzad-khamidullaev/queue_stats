import { useState } from "react";
import ReportFilters from "../components/ReportFilters.jsx";
import client from "../api/client.js";

const formatDate = (iso) => (iso ? new Date(iso).toLocaleString("ru-RU") : "");

export default function AnsweredCdrView({ queues, agents }) {
    const [report, setReport] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const loadReport = async (filters) => {
        try {
            setLoading(true);
            setError(null);
            const response = await client.post("/reports/answered-cdr/", filters);
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
                <h2 className="card__title">Принятые звонки (CDR)</h2>
                <ReportFilters queues={queues} agents={agents} onSubmit={loadReport} loading={loading} />
                {error && <div className="error">Не удалось получить отчет: {error.message}</div>}
                {!report && !loading && <div className="muted">Выберите параметры и сформируйте отчет.</div>}
                {report && (
                    <table className="table">
                        <thead>
                            <tr>
                                <th>Дата и время</th>
                                <th>Кто звонил</th>
                                <th>Куда звонил</th>
                                <th>Длительность</th>
                                <th>Запись</th>
                            </tr>
                        </thead>
                        <tbody>
                            {report.data.map((row) => (
                                <tr key={row.uniqueid}>
                                    <td>{formatDate(row.calldate)}</td>
                                    <td>{row.src}</td>
                                    <td>{row.dst}</td>
                                    <td>{row.duration} c.</td>
                                    <td>
                                        {row.recordingfile && (
                                            <audio controls preload="none">
                                                <source src={`/api/recordings/${row.uniqueid}/`} type="audio/wav" />
                                                Ваш браузер не поддерживает аудио.
                                            </audio>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
    );
}
