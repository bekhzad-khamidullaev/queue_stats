import { useEffect, useState } from "react";
import client from "../api/client.js";

export default function RealtimeCallsView() {
  const [data, setData] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    let timeoutId;

    async function load() {
      try {
        const response = await client.get("/realtime/calls/");
        if (!cancelled) {
          setData(response.data.entries ?? []);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err);
        }
      } finally {
        if (!cancelled) {
          timeoutId = setTimeout(load, 1500);
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
        <h2 className="card__title">Текущие звонки</h2>
        {error && <div className="error">Ошибка обновления: {error.message}</div>}
        <div className="realtime-list">
          {data.map((item, index) => (
            <div key={index} className="realtime-item">
              <div>
                <div className="realtime-item__title">{item.Channel || "Неизвестный канал"}</div>
                <div className="muted">{item.CallerIDNum}</div>
              </div>
              <div>
                <div className="muted">Состояние</div>
                <div>{item.ChannelStateDesc}</div>
              </div>
              <div>
                <div className="muted">Очередь</div>
                <div>{item.Context}</div>
              </div>
              <div>
                <div className="muted">Время</div>
                <div>{item.Duration}s</div>
              </div>
            </div>
          ))}
          {!data.length && !error && <div className="muted">Нет активных разговоров</div>}
        </div>
      </div>
    </div>
  );
}

