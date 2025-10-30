import { useMemo, useState } from "react";
import { exportDataToCsv } from "../utils/export.js";
import ReportFilters from "../components/ReportFilters.jsx";
import client from "../api/client.js";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  BarChart,
  Bar,
} from "recharts";

const palette = ["#2b67f6", "#ff7f50", "#5ed5a7", "#a855f7", "#facc15", "#f97316", "#0ea5e9", "#ef4444"];

const toNumber = (value) => (value === null || value === undefined ? 0 : Number(value));

const formatDateLabel = (value) => {
  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return date.toLocaleDateString("ru-RU", { day: "2-digit", month: "short" });
  } catch {
    return value;
  }
};

export default function AnalyticsView({ queues, agents }) {
  const [volumeReport, setVolumeReport] = useState(null);
  const [volumeLoading, setVolumeLoading] = useState(false);
  const [volumeError, setVolumeError] = useState(null);

  const [agentReport, setAgentReport] = useState(null);
  const [agentLoading, setAgentLoading] = useState(false);
  const [agentError, setAgentError] = useState(null);

  const [slaReport, setSlaReport] = useState(null);
  const [slaLoading, setSlaLoading] = useState(false);
  const [slaError, setSlaError] = useState(null);

  const loadVolume = async (filters) => {
    try {
      setVolumeLoading(true);
      setVolumeError(null);
      const response = await client.post("/reports/volume/", filters);
      setVolumeReport(response.data);
    } catch (err) {
      setVolumeError(err);
    } finally {
      setVolumeLoading(false);
    }
  };

  const loadAgentPerformance = async (filters) => {
    try {
      setAgentLoading(true);
      setAgentError(null);
      const response = await client.post("/reports/agents-performance/", filters);
      setAgentReport(response.data);
    } catch (err) {
      setAgentError(err);
    } finally {
      setAgentLoading(false);
    }
  };

  const loadSla = async (filters) => {
    try {
      setSlaLoading(true);
      setSlaError(null);
      const response = await client.post("/reports/sla/", filters);
      setSlaReport(response.data);
    } catch (err) {
      setSlaError(err);
    } finally {
      setSlaLoading(false);
    }
  };

  const dailySeries = useMemo(() => {
    if (!volumeReport?.daily) {
      return [];
    }
    return volumeReport.daily.map((row) => ({
      date: row.day,
      answered: toNumber(row.answered),
      unanswered: toNumber(row.unanswered),
    }));
  }, [volumeReport]);

  const hourlySeries = useMemo(() => {
    if (!volumeReport?.hourly) {
      return [];
    }
    const accumulator = new Map();
    volumeReport.hourly.forEach((row) => {
      const hour = row.hour;
      if (!accumulator.has(hour)) {
        accumulator.set(hour, { hour, answered: 0, unanswered: 0 });
      }
      const bucket = accumulator.get(hour);
      bucket.answered += toNumber(row.answered);
      bucket.unanswered += toNumber(row.unanswered);
    });
    return Array.from(accumulator.values()).sort((a, b) => a.hour - b.hour);
  }, [volumeReport]);

  const dailyAbandonmentRate = useMemo(() => {
    if (!dailySeries) {
      return [];
    }
    return dailySeries.map((row) => ({
      date: row.date,
      rate: row.answered + row.unanswered > 0 ? (row.unanswered / (row.answered + row.unanswered)) * 100 : 0,
    }));
  }, [dailySeries]);

  const queueSeries = useMemo(() => {
    if (!volumeReport?.per_queue) {
      return [];
    }
    return volumeReport.per_queue.map((row) => ({
      queue: row.queuename,
      answered: toNumber(row.answered),
      unanswered: toNumber(row.unanswered),
    }));
  }, [volumeReport]);

  const topAgents = useMemo(() => {
    if (!agentReport?.agents) {
      return [];
    }
    return agentReport.agents.slice(0, 8);
  }, [agentReport]);

  const agentTalkSeries = useMemo(() => {
    return topAgents.map((row) => ({
      agent: row.agent,
      talkMinutes: Math.round(toNumber(row.talk_time) / 60),
      avgTalk: toNumber(row.avg_talk_time),
      avgWait: toNumber(row.avg_wait_time),
      answeredCalls: toNumber(row.answered_calls),
    }));
  }, [topAgents]);

  const agentTrendSeries = useMemo(() => {
    if (!agentReport?.trends || topAgents.length === 0) {
      return [];
    }
    const topAgentNames = new Set(topAgents.map((row) => row.agent));
    const dayMap = new Map();

    agentReport.trends.forEach((row) => {
      if (!topAgentNames.has(row.agent)) {
        return;
      }
      const day = row.day;
      if (!dayMap.has(day)) {
        dayMap.set(day, { day });
      }
      const bucket = dayMap.get(day);
      bucket[row.agent] = toNumber(row.answered_calls);
    });

    return Array.from(dayMap.entries())
      .sort(([a], [b]) => new Date(a) - new Date(b))
      .map(([, value]) => value);
  }, [agentReport, topAgents]);

  const slaSeries = useMemo(() => {
    if (!slaReport?.daily) {
      return [];
    }
    return slaReport.daily.map((row) => ({
      date: row.day,
      sla: row.total_answered > 0 ? (toNumber(row.sla_answered) / toNumber(row.total_answered)) * 100 : 0,
    }));
  }, [slaReport]);

  const overallSla = useMemo(() => {
    if (!slaReport?.daily) {
      return null;
    }
    const totalAnswered = slaReport.daily.reduce((acc, row) => acc + toNumber(row.total_answered), 0);
    const totalSlaAnswered = slaReport.daily.reduce((acc, row) => acc + toNumber(row.sla_answered), 0);
    return totalAnswered > 0 ? (totalSlaAnswered / totalAnswered) * 100 : 0;
  }, [slaReport]);

  return (
    <div className="view">
      <div className="card">
        <h2 className="card__title">Динамика звонков</h2>
        <ReportFilters
          queues={queues}
          agents={agents}
          buttonLabel="Построить"
        />
        {volumeReport && (
          <button
            className="button"
            style={{ marginTop: "1rem" }}
            onClick={() => {
              const sections = [
                { title: "Daily Volume", data: dailySeries },
                { title: "Hourly Volume", data: hourlySeries },
                { title: "Queue Volume", data: queueSeries },
              ];
              const csvContent = sections
                .map((section) => {
                  if (!section.data || section.data.length === 0) return "";
                  const headers = Object.keys(section.data[0]);
                  const rows = section.data.map((row) => headers.map((h) => JSON.stringify(row[h] ?? '')).join(","));
                  return `${section.title}\n${headers.join(",")}\n${rows.join("\n")}`;
                })
                .filter(Boolean)
                .join("\n\n");

              const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
              const link = document.createElement("a");
              const url = URL.createObjectURL(blob);
              link.setAttribute("href", url);
              link.setAttribute("download", `volume-report-${new Date().toISOString().split("T")[0]}.csv`);
              link.style.visibility = "hidden";
              document.body.appendChild(link);
              link.click();
              document.body.removeChild(link);
            }}>
            Экспорт в CSV
          </button>
        )}
        {volumeError && <div className="error">Не удалось получить отчет: {volumeError.message}</div>}
        {!volumeReport && !volumeLoading && <div className="muted">Выберите параметры и постройте график.</div>}
        {volumeReport && (
          <>
            <div className="card">
              <h3 className="card__title">По дням</h3>
              <div style={{ width: "100%", height: 320 }}>
                <ResponsiveContainer>
                  <LineChart data={dailySeries}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" tickFormatter={formatDateLabel} />
                    <YAxis allowDecimals={false} />
                    <Tooltip labelFormatter={formatDateLabel} />
                    <Legend />
                    <Line type="monotone" dataKey="answered" name="Принятые" stroke="#2b67f6" strokeWidth={2} />
                    <Line type="monotone" dataKey="unanswered" name="Потерянные" stroke="#e5484d" strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div className="card">
              <h3 className="card__title">Процент потерянных</h3>
              <div style={{ width: "100%", height: 300 }}>
                <ResponsiveContainer>
                  <LineChart data={dailyAbandonmentRate}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" tickFormatter={formatDateLabel} />
                    <YAxis unit="%" allowDecimals={false} />
                    <Tooltip formatter={(value) => `${value.toFixed(2)}%`} labelFormatter={formatDateLabel} />
                    <Legend />
                    <Line type="monotone" dataKey="rate" name="Процент потерянных" stroke="#f97316" strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div className="card">
              <div style={{ width: "100%", height: 300 }}>
                <ResponsiveContainer>
                  <BarChart data={hourlySeries}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="hour" />
                    <YAxis allowDecimals={false} />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="answered" name="Принятые" stackId="calls" fill="#2b67f6" />
                    <Bar dataKey="unanswered" name="Потерянные" stackId="calls" fill="#e5484d" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div className="card">
              <h3 className="card__title">Вызовы по очередям</h3>
              <div style={{ width: "100%", height: 320 }}>
                <ResponsiveContainer>
                  <BarChart data={queueSeries}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="queue" />
                    <YAxis allowDecimals={false} />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="answered" name="Принятые" fill="#1b46a3" />
                    <Bar dataKey="unanswered" name="Потерянные" fill="#FFB347" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </>
        )}
      </div>

      <div className="card">
        <h2 className="card__title">Эффективность агентов</h2>
        <ReportFilters
          queues={queues}
          agents={agents}
          onSubmit={loadAgentPerformance}
          requireAgents
          buttonLabel="Построить"
        />
        {agentReport && (
          <button
            className="button"
            style={{ marginTop: "1rem" }}
            onClick={() => exportDataToCsv(`agent-performance-${new Date().toISOString().split("T")[0]}.csv`, agentTalkSeries)}>
            Экспорт в CSV
          </button>
        )}
        {agentError && <div className="error">Не удалось получить отчет: {agentError.message}</div>}
        {!agentReport && !agentLoading && <div className="muted">Укажите параметры и построите график.</div>}
        {agentReport && (
          <>
            <div className="card">
              <h3 className="card__title">Топ агентов (минуты разговора)</h3>
              <div style={{ width: "100%", height: 320 }}>
                <ResponsiveContainer>
                  <BarChart data={agentTalkSeries} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" />
                    <YAxis dataKey="agent" type="category" width={120} />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="talkMinutes" name="Минуты разговора" fill="#2b67f6" />
                    <Bar dataKey="answeredCalls" name="Принятые вызовы" fill="#5ed5a7" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
            {agentTrendSeries.length > 0 && (
              <div className="card">
                <h3 className="card__title">Принятые вызовы по дням</h3>
                <div style={{ width: "100%", height: 320 }}>
                  <ResponsiveContainer>
                    <LineChart data={agentTrendSeries}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="day" tickFormatter={formatDateLabel} />
                      <YAxis allowDecimals={false} />
                      <Tooltip labelFormatter={formatDateLabel} />
                      <Legend />
                      {topAgents.map((agent, index) => (
                        <Line
                          key={agent.agent}
                          type="monotone"
                          dataKey={agent.agent}
                          name={agent.agent}
                          strokeWidth={2}
                          stroke={palette[index % palette.length]}
                        />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      <div className="card">
        <h2 className="card__title">Уровень обслуживания (SLA)</h2>
        <ReportFilters
          queues={queues}
          agents={agents}
          onSubmit={loadSla}
          loading={slaLoading}
          buttonLabel="Рассчитать"
        />
        {slaReport && (
          <button
            className="button"
            style={{ marginTop: "1rem" }}
            onClick={() => exportDataToCsv(`sla-report-${new Date().toISOString().split("T")[0]}.csv`, slaSeries)}>
            Экспорт в CSV
          </button>
        )}
        {slaError && <div className="error">Не удалось получить отчет: {slaError.message}</div>}
        {!slaReport && !slaLoading && <div className="muted">Выберите параметры и рассчитайте SLA.</div>}
        {slaReport && (
          <>
            <div className="card">
              <h3 className="card__title">Общий SLA за период: {overallSla.toFixed(2)}%</h3>
              <p className="muted">Порог SLA: {slaReport.threshold} секунд</p>
              <div style={{ width: "100%", height: 320 }}>
                <ResponsiveContainer>
                  <LineChart data={slaSeries}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" tickFormatter={formatDateLabel} />
                    <YAxis unit="%" domain={[0, 100]} />
                    <Tooltip formatter={(value) => `${value.toFixed(2)}%`} labelFormatter={formatDateLabel} />
                    <Legend />
                    <Line type="monotone" dataKey="sla" name="SLA" stroke="#a855f7" strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
