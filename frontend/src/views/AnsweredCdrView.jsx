import { useState, useMemo } from "react";
import ReportFilters from "../components/ReportFilters.jsx";
import { exportDataToCsv } from "../utils/export.js";
import client from "../api/client.js";

const formatDate = (iso) => (iso ? new Date(iso).toLocaleString("ru-RU") : "");
const formatDuration = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
};

export default function AnsweredCdrView({ queues, agents }) {
    const [report, setReport] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [searchTerm, setSearchTerm] = useState("");
    const [currentPage, setCurrentPage] = useState(1);
    const [itemsPerPage] = useState(50);

    const loadReport = async (filters) => {
        try {
            setLoading(true);
            setError(null);
            setCurrentPage(1);
            const response = await client.post("/reports/answered-cdr/", filters);
            setReport(response.data);
        } catch (err) {
            setError(err);
        } finally {
            setLoading(false);
        }
    };

    const filteredData = useMemo(() => {
        if (!report?.data) return [];
        if (!searchTerm) return report.data;
        const search = searchTerm.toLowerCase();
        return report.data.filter(row => 
            row.src?.toLowerCase().includes(search) ||
            row.dst?.toLowerCase().includes(search) ||
            row.uniqueid?.toLowerCase().includes(search)
        );
    }, [report, searchTerm]);

    const totalPages = Math.ceil(filteredData.length / itemsPerPage);
    const startIndex = (currentPage - 1) * itemsPerPage;
    const paginatedData = filteredData.slice(startIndex, startIndex + itemsPerPage);

    const exportCDR = () => {
        const exportData = filteredData.map(row => ({
            "Дата и время": formatDate(row.calldate),
            "Кто звонил": row.src,
            "Куда звонил": row.dst,
            "Длительность (сек)": row.duration,
            "Разговор (сек)": row.billsec,
            "UniqueID": row.uniqueid,
            "Есть запись": row.recordingfile ? "Да" : "Нет"
        }));
        exportDataToCsv(`cdr-report-${new Date().toISOString().split('T')[0]}.csv`, exportData);
    };

    return (
        <div className="view">
            <div className="card">
                <h2 className="card__title">Принятые звонки (CDR)</h2>
                <ReportFilters queues={queues} agents={agents} onSubmit={loadReport} loading={loading} />
                
                {report && (
                    <div style={{ marginTop: "1rem", display: "flex", gap: "1rem", alignItems: "center" }}>
                        <input
                            type="text"
                            placeholder="Поиск по номеру телефона..."
                            value={searchTerm}
                            onChange={(e) => {
                                setSearchTerm(e.target.value);
                                setCurrentPage(1);
                            }}
                            style={{ flex: 1, padding: "0.5rem" }}
                        />
                        <button className="button" onClick={exportCDR}>
                            Экспорт в CSV ({filteredData.length} записей)
                        </button>
                    </div>
                )}
                
                {error && <div className="error">Не удалось получить отчет: {error.message}</div>}
                {!report && !loading && <div className="muted">Выберите параметры и сформируйте отчет.</div>}
                
                {report && filteredData.length === 0 && (
                    <div className="muted" style={{ marginTop: "1rem" }}>Нет записей, соответствующих критериям поиска.</div>
                )}
                
                {report && filteredData.length > 0 && (
                    <>
                        <div style={{ marginTop: "1rem", marginBottom: "0.5rem", color: "#666" }}>
                            Показано {startIndex + 1}-{Math.min(startIndex + itemsPerPage, filteredData.length)} из {filteredData.length} записей
                        </div>
                        <table className="table">
                            <thead>
                                <tr>
                                    <th>Дата и время</th>
                                    <th>Кто звонил</th>
                                    <th>Куда звонил</th>
                                    <th>Длительность</th>
                                    <th>Разговор</th>
                                    <th>Запись</th>
                                </tr>
                            </thead>
                            <tbody>
                                {paginatedData.map((row) => (
                                    <tr key={row.uniqueid}>
                                        <td>{formatDate(row.calldate)}</td>
                                        <td>{row.src}</td>
                                        <td>{row.dst}</td>
                                        <td>{formatDuration(row.duration)}</td>
                                        <td>{formatDuration(row.billsec)}</td>
                                        <td>
                                            {row.recordingfile ? (
                                                <audio controls preload="none" style={{ height: "30px" }}>
                                                    <source src={`/api/recordings/${row.uniqueid}/`} type="audio/wav" />
                                                    Ваш браузер не поддерживает аудио.
                                                </audio>
                                            ) : (
                                                <span className="muted">Нет</span>
                                            )}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                        
                        {totalPages > 1 && (
                            <div style={{ marginTop: "1rem", display: "flex", gap: "0.5rem", justifyContent: "center", alignItems: "center" }}>
                                <button
                                    className="button"
                                    onClick={() => setCurrentPage(1)}
                                    disabled={currentPage === 1}
                                >
                                    «
                                </button>
                                <button
                                    className="button"
                                    onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                                    disabled={currentPage === 1}
                                >
                                    ‹
                                </button>
                                <span style={{ padding: "0 1rem" }}>
                                    Страница {currentPage} из {totalPages}
                                </span>
                                <button
                                    className="button"
                                    onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                                    disabled={currentPage === totalPages}
                                >
                                    ›
                                </button>
                                <button
                                    className="button"
                                    onClick={() => setCurrentPage(totalPages)}
                                    disabled={currentPage === totalPages}
                                >
                                    »
                                </button>
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    );
}
