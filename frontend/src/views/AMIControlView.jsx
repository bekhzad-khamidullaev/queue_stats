import { useEffect, useState, useCallback, useMemo } from "react";
import client from "../api/client.js";
import { buildAgentNameMap, buildQueueNameMap, formatAgentName, formatQueueName } from "../utils/displayNames.js";

const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const WEBSOCKET_URL = `${protocol}//${window.location.host}/ws/realtime/`;

export default function AMIControlView({ queues: metaQueues, agents }) {
  const [activeTab, setActiveTab] = useState("queues");
  const [queueStatus, setQueueStatus] = useState([]);
  const [channels, setChannels] = useState([]);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [ws, setWs] = useState(null);
  const [wsConnected, setWsConnected] = useState(false);
  const queueNameMap = useMemo(() => buildQueueNameMap(metaQueues), [metaQueues]);
  const agentNameMap = useMemo(() => buildAgentNameMap(agents), [agents]);

  // Call origination state
  const [originateForm, setOriginateForm] = useState({
    channel: "",
    exten: "",
    context: "from-internal",
    callerid: ""
  });

  // WebSocket connection with auto-reconnect
  useEffect(() => {
    let reconnectTimeout;
    
    const connectWebSocket = () => {
      const websocket = new WebSocket(WEBSOCKET_URL);
    
    websocket.onopen = () => {
      console.log("WebSocket connected");
      setWsConnected(true);
      websocket.send(JSON.stringify({ command: "subscribe", events: ["all"] }));
    };
    
    websocket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "ami_event" || data.event) {
          setEvents(prev => [{
            timestamp: new Date().toLocaleTimeString(),
            type: data.event || data.type,
            data: data.data || data
          }, ...prev].slice(0, 50));
          
          // Refresh data on relevant events
          if (["QueueMemberAdded", "QueueMemberRemoved", "QueueMemberPause", "QueueMemberStatus"].includes(data.event)) {
            loadQueues();
          }
          if (["Newchannel", "Hangup", "NewState"].includes(data.event)) {
            loadChannels();
          }
        }
      } catch (err) {
        console.error("WebSocket message error:", err);
      }
    };
    
    websocket.onerror = (err) => {
      console.error("WebSocket error:", err);
      setWsConnected(false);
    };
    
      websocket.onclose = () => {
        console.log("WebSocket closed");
        setWsConnected(false);
        // Auto-reconnect after 5 seconds
        reconnectTimeout = setTimeout(connectWebSocket, 5000);
      };
      
      setWs(websocket);
    };
    
    connectWebSocket();
    
    return () => {
      clearTimeout(reconnectTimeout);
      if (ws) {
        ws.close();
      }
    };
  }, []);

  const loadQueues = useCallback(async () => {
    try {
      setLoading(true);
      const response = await client.get("/ami/queue/status/");
      setQueueStatus(response.data.queues || []);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadChannels = useCallback(async () => {
    try {
      setLoading(true);
      const response = await client.get("/ami/channels/");
      setChannels(response.data.channels || []);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === "queues") {
      loadQueues();
    } else if (activeTab === "channels") {
      loadChannels();
    }
  }, [activeTab, loadQueues, loadChannels]);

  const handlePauseMember = async (queue, iface, paused) => {
    try {
      await client.post("/ami/queue/pause/", {
        queue,
        interface: iface,
        paused
      });
      loadQueues();
    } catch (err) {
      alert(`Ошибка: ${err.message}`);
    }
  };

  const handleRemoveMember = async (queue, iface) => {
    if (!confirm(`Удалить агента ${iface} из очереди ${queue}?`)) return;
    try {
      await client.post("/ami/queue/remove/", { queue, interface: iface });
      loadQueues();
    } catch (err) {
      alert(`Ошибка: ${err.message}`);
    }
  };

  const handleHangup = async (channel) => {
    if (!confirm(`Завершить канал ${channel}?`)) return;
    try {
      await client.post("/ami/hangup/", { channel });
      loadChannels();
    } catch (err) {
      alert(`Ошибка: ${err.message}`);
    }
  };

  const handleOriginate = async (e) => {
    e.preventDefault();
    try {
      await client.post("/ami/originate/", originateForm);
      alert("Вызов инициирован");
      setOriginateForm({ channel: "", exten: "", context: "from-internal", callerid: "" });
    } catch (err) {
      alert(`Ошибка: ${err.message}`);
    }
  };

  return (
    <div className="view">
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
          <h2 className="card__title">Управление Asterisk (AMI)</h2>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <span style={{ 
              width: "10px", 
              height: "10px", 
              borderRadius: "50%", 
              backgroundColor: wsConnected ? "#5ed5a7" : "#e5484d",
              display: "inline-block"
            }} />
            <span className="muted">{wsConnected ? "WebSocket подключен" : "WebSocket отключен"}</span>
          </div>
        </div>

        <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem", borderBottom: "1px solid #ddd" }}>
          <button
            className="button"
            style={{
              borderRadius: "0",
              borderBottom: activeTab === "queues" ? "2px solid #2b67f6" : "none",
              background: activeTab === "queues" ? "#f0f0f0" : "transparent"
            }}
            onClick={() => setActiveTab("queues")}
          >
            Очереди
          </button>
          <button
            className="button"
            style={{
              borderRadius: "0",
              borderBottom: activeTab === "channels" ? "2px solid #2b67f6" : "none",
              background: activeTab === "channels" ? "#f0f0f0" : "transparent"
            }}
            onClick={() => setActiveTab("channels")}
          >
            Каналы
          </button>
          <button
            className="button"
            style={{
              borderRadius: "0",
              borderBottom: activeTab === "events" ? "2px solid #2b67f6" : "none",
              background: activeTab === "events" ? "#f0f0f0" : "transparent"
            }}
            onClick={() => setActiveTab("events")}
          >
            События ({events.length})
          </button>
          <button
            className="button"
            style={{
              borderRadius: "0",
              borderBottom: activeTab === "actions" ? "2px solid #2b67f6" : "none",
              background: activeTab === "actions" ? "#f0f0f0" : "transparent"
            }}
            onClick={() => setActiveTab("actions")}
          >
            Действия
          </button>
        </div>

        {error && <div className="error">{error}</div>}

        {activeTab === "queues" && (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
              <h3>Статус очередей</h3>
              <button className="button" onClick={loadQueues} disabled={loading}>
                {loading ? "Загрузка..." : "Обновить"}
              </button>
            </div>
            
            {queueStatus.length === 0 ? (
              <div className="muted">Нет данных об очередях</div>
            ) : (
              queueStatus.map((queue, idx) => (
                <div key={idx} className="card" style={{ marginBottom: "1rem" }}>
                  <h4>{formatQueueName(queue.Queue, queueNameMap) || "Неизвестная очередь"}</h4>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "1rem", marginBottom: "1rem" }}>
                    <div>
                      <div className="muted">Макс. ожидание</div>
                      <div>{queue.Max || 0}</div>
                    </div>
                    <div>
                      <div className="muted">Стратегия</div>
                      <div>{queue.Strategy || "N/A"}</div>
                    </div>
                    <div>
                      <div className="muted">Звонки</div>
                      <div>{queue.Calls || 0}</div>
                    </div>
                    <div>
                      <div className="muted">Принято</div>
                      <div>{queue.Completed || 0}</div>
                    </div>
                    <div>
                      <div className="muted">Брошено</div>
                      <div>{queue.Abandoned || 0}</div>
                    </div>
                  </div>
                  
                  {queue.members && queue.members.length > 0 && (
                    <>
                      <h5 style={{ marginTop: "1rem" }}>Агенты ({queue.members.length})</h5>
                      <table className="table">
                        <thead>
                          <tr>
                            <th>Интерфейс</th>
                            <th>Имя</th>
                            <th>Статус</th>
                            <th>Пауза</th>
                            <th>Принято</th>
                            <th>Действия</th>
                          </tr>
                        </thead>
                        <tbody>
                          {queue.members.map((member, midx) => (
                            <tr key={midx}>
                              <td>{formatAgentName(member.Location || member.Interface, agentNameMap)}</td>
                              <td>{member.MemberName || member.Name || formatAgentName(member.Interface, agentNameMap) || "N/A"}</td>
                              <td>
                                <span style={{
                                  padding: "0.25rem 0.5rem",
                                  borderRadius: "4px",
                                  background: member.Status === "1" || member.Status === "Not in use" ? "#5ed5a7" : "#e5484d",
                                  color: "white",
                                  fontSize: "0.85rem"
                                }}>
                                  {member.StateInterface || member.Status}
                                </span>
                              </td>
                              <td>{member.Paused === "1" || member.Paused === "true" ? "Да" : "Нет"}</td>
                              <td>{member.CallsTaken || 0}</td>
                              <td>
                                <div style={{ display: "flex", gap: "0.5rem" }}>
                                  <button
                                    className="button"
                                    style={{ fontSize: "0.85rem", padding: "0.25rem 0.5rem" }}
                                    onClick={() =>
                                      handlePauseMember(
                                        queue.Queue,
                                        member.Location || member.Interface,
                                        member.Paused !== "1",
                                      )
                                    }
                                  >
                                    {member.Paused === "1" ? "Активировать" : "Пауза"}
                                  </button>
                                  <button
                                    className="button"
                                    style={{ fontSize: "0.85rem", padding: "0.25rem 0.5rem", background: "#e5484d" }}
                                    onClick={() =>
                                      handleRemoveMember(queue.Queue, member.Location || member.Interface)
                                    }
                                  >
                                    Удалить
                                  </button>
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </>
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === "channels" && (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
              <h3>Активные каналы</h3>
              <button className="button" onClick={loadChannels} disabled={loading}>
                {loading ? "Загрузка..." : "Обновить"}
              </button>
            </div>
            
            {channels.length === 0 ? (
              <div className="muted">Нет активных каналов</div>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Канал</th>
                    <th>Caller ID</th>
                    <th>Состояние</th>
                    <th>Контекст</th>
                    <th>Длительность</th>
                    <th>Действия</th>
                  </tr>
                </thead>
                <tbody>
                  {channels.map((channel, idx) => (
                    <tr key={idx}>
                      <td>{channel.Channel}</td>
                      <td>{channel.CallerIDNum || "N/A"}</td>
                      <td>{channel.ChannelStateDesc || channel.State}</td>
                      <td>{formatQueueName(channel.Context, queueNameMap)}</td>
                      <td>{channel.Duration || 0}s</td>
                      <td>
                        <button
                          className="button"
                          style={{ fontSize: "0.85rem", padding: "0.25rem 0.5rem", background: "#e5484d" }}
                          onClick={() => handleHangup(channel.Channel)}
                        >
                          Завершить
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {activeTab === "events" && (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
              <h3>Реальное время события</h3>
              <button className="button" onClick={() => setEvents([])}>
                Очистить
              </button>
            </div>
            
            {events.length === 0 ? (
              <div className="muted">Нет событий</div>
            ) : (
              <div style={{ maxHeight: "600px", overflowY: "auto" }}>
                {events.map((event, idx) => (
                  <div key={idx} style={{ 
                    padding: "0.75rem", 
                    marginBottom: "0.5rem", 
                    background: "#f5f5f5",
                    borderRadius: "4px",
                    borderLeft: "3px solid #2b67f6"
                  }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.5rem" }}>
                      <strong>{event.type}</strong>
                      <span className="muted">{event.timestamp}</span>
                    </div>
                    <pre style={{ 
                      fontSize: "0.85rem", 
                      background: "white", 
                      padding: "0.5rem",
                      borderRadius: "4px",
                      overflow: "auto",
                      margin: 0
                    }}>
                      {JSON.stringify(event.data, null, 2)}
                    </pre>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === "actions" && (
          <div>
            <h3>Действия</h3>
            
            <div className="card">
              <h4>Инициировать вызов</h4>
              <form onSubmit={handleOriginate}>
                <div style={{ display: "grid", gap: "1rem", marginBottom: "1rem" }}>
                  <div>
                    <label>Канал (например, SIP/100)</label>
                    <input
                      type="text"
                      value={originateForm.channel}
                      onChange={(e) => setOriginateForm({...originateForm, channel: e.target.value})}
                      required
                      placeholder="SIP/100"
                    />
                  </div>
                  <div>
                    <label>Номер назначения</label>
                    <input
                      type="text"
                      value={originateForm.exten}
                      onChange={(e) => setOriginateForm({...originateForm, exten: e.target.value})}
                      required
                      placeholder="200"
                    />
                  </div>
                  <div>
                    <label>Контекст</label>
                    <input
                      type="text"
                      value={originateForm.context}
                      onChange={(e) => setOriginateForm({...originateForm, context: e.target.value})}
                      required
                    />
                  </div>
                  <div>
                    <label>Caller ID (опционально)</label>
                    <input
                      type="text"
                      value={originateForm.callerid}
                      onChange={(e) => setOriginateForm({...originateForm, callerid: e.target.value})}
                      placeholder="Test Call"
                    />
                  </div>
                </div>
                <button type="submit" className="button">Инициировать вызов</button>
              </form>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
