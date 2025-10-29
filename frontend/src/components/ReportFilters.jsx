import { useState } from "react";

const today = new Date();
const formatDate = (date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(
    2,
    "0",
  )}`;

export default function ReportFilters({
  queues,
  agents,
  onSubmit,
  requireAgents = false,
  loading,
  buttonLabel = "Обновить",
}) {
  const [selectedQueues, setSelectedQueues] = useState([]);
  const [selectedAgents, setSelectedAgents] = useState([]);
  const [start, setStart] = useState(`${formatDate(today)} 00:00:00`);
  const [end, setEnd] = useState(`${formatDate(today)} 23:59:59`);

  const submit = (event) => {
    event.preventDefault();
    onSubmit({
      queues: selectedQueues,
      agents: selectedAgents,
      start,
      end,
    });
  };

  return (
    <form className="filters" onSubmit={submit}>
      <div className="filters__column">
        <label htmlFor="queues">Очереди</label>
        <select
          id="queues"
          multiple
          size={Math.min(queues.length, 6) || 3}
          value={selectedQueues}
          onChange={(event) => {
            setSelectedQueues(Array.from(event.target.selectedOptions, (option) => option.value));
          }}
        >
          {queues.map((queue) => (
            <option key={queue.queuename} value={queue.queuename}>
              {queue.descr || queue.queuename}
            </option>
          ))}
        </select>
      </div>
      {requireAgents && (
        <div className="filters__column">
          <label htmlFor="agents">Агенты</label>
          <select
            id="agents"
            multiple
            size={Math.min(agents.length, 6) || 3}
            value={selectedAgents}
            onChange={(event) => {
              setSelectedAgents(Array.from(event.target.selectedOptions, (option) => option.value));
            }}
          >
            {agents.map((agent) => (
              <option key={agent.agent} value={agent.agent}>
                {agent.name || agent.agent}
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="filters__column">
        <label htmlFor="start">Начало</label>
        <input id="start" type="text" value={start} onChange={(event) => setStart(event.target.value)} />
      </div>
      <div className="filters__column">
        <label htmlFor="end">Конец</label>
        <input id="end" type="text" value={end} onChange={(event) => setEnd(event.target.value)} />
      </div>
      <div className="filters__column">
        <label>&nbsp;</label>
        <button type="submit" disabled={loading}>
          {loading ? "Загрузка…" : buttonLabel}
        </button>
      </div>
    </form>
  );
}
