import { useState } from "react";
import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from "recharts";
import ReportFilters from "../components/ReportFilters.jsx";
import client from "../api/client.js";

const COLORS = ["#0088FE", "#00C49F", "#FFBB28", "#FF8042", "#a855f7", "#f97316"];

const exportToCsv = (filename, data) => {
    const headers = Object.keys(data.summary);
    const csvRows = [headers.join(",")];
    const values = headers.map(header => data.summary[header]);
    csvRows.push(values.join(","));

    csvRows.push("");
    csvRows.push("Calls Per Queue");
    const queueHeaders = ["Queue", "Calls"];
    csvRows.push(queueHeaders.join(","));
    for (const [queue, calls] of Object.entries(data.calls_per_queue)) {
        csvRows.push([queue, calls].join(","));
    }

    const blob = new Blob([csvRows.join("\n")], { type: "text/csv;charset=utf-8;" });
    const link = document.createElement("a");
    const url = URL.createObjectURL(blob);
    link.setAttribute("href", url);
    link.setAttribute("download", filename);
    link.style.visibility = "hidden";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
};


export default function SummaryView({ queues, agents }) {
    const [report, setReport] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const loadReport = async (filters) => {
        try {
            setLoading(true);
            setError(null);
            const response = await client.post("/reports/summary/", filters);
            setReport(response.data);
        } catch (err) {
            setError(err);
        } finally {
            setLoading(false);
        }
    };

    const queueData = Object.entries(report?.calls_per_queue || {}).map(([name, value]) => ({ name, value }));

    return (
        <div className="view">
            <div className="card">
                <h2 className="card__title">Сводный отчет</h2>
                <ReportFilters queues={queues} agents={agents} onSubmit={loadReport} loading={loading} buttonLabel="Сформировать" />
                {report && (
                    <button 
                        className="button" 
                        style={{marginTop: "1rem"}}
                        onClick={() => exportToCsv(`summary-report-${new Date().toISOString().split('T')[0]}.csv`, report)}>
                        Экспорт в CSV
                    </button>
                )}
                {error && <div className="error">Не удалось получить отчет: {error.message}</div>}
                {!report && !loading && <div className="muted">Выберите параметры и сформируйте отчет.</div>}
            </div>

            {report && (
                <div className="stats-grid">
                    <div className="card stat-card">
                        <h3>Всего звонков</h3>
                        <p>{report.summary.total_calls}</p>
                    </div>
                    <div className="card stat-card">
                        <h3>Принятые</h3>
                        <p>{report.summary.answered_calls}</p>
                    </div>
                    <div className="card stat-card">
                        <h3>Потерянные (Abandon)</h3>
                        <p>{report.summary.abandoned_calls}</p>
                    </div>
                    <div className="card stat-card">
                        <h3>Потерянные (Timeout)</h3>
                        <p>{report.summary.timeout_calls}</p>
                    </div>
                    <div className="card stat-card">
                        <h3>Уровень обслуживания</h3>
                        <p>{report.summary.service_level}%</p>
                    </div>
                    <div className="card stat-card">
                        <h3>Среднее время ожидания</h3>
                        <p>{report.summary.avg_wait_time} сек.</p>
                    </div>
                    <div className="card stat-card">
                        <h3>Среднее время разговора</h3>
                        <p>{report.summary.avg_talk_time} сек.</p>
                    </div>
                </div>
            )}

            {report && queueData.length > 0 && (
                <div className="card">
                    <h3 className="card__title">Распределение по очередям</h3>
                    <div style={{ width: "100%", height: 300 }}>
                        <ResponsiveContainer>
                            <PieChart>
                                <Pie data={queueData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={100} fill="#8884d8" label>
                                    {queueData.map((entry, index) => (
                                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                                    ))}
                                </Pie>
                                <Tooltip />
                                <Legend />
                            </PieChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            )}
        </div>
    );
}