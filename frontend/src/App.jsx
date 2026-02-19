import { useEffect, useMemo, useState } from "react";
import useMetaData from "./hooks/useMetaData.js";
import { useAuth } from "./context/AuthContext.jsx";
import AnsweredView from "./views/AnsweredView.jsx";
import UnansweredView from "./views/UnansweredView.jsx";
import SummaryView from "./views/SummaryView.jsx";
import DistributionView from "./views/DistributionView.jsx";
import AnalyticsView from "./views/AnalyticsView.jsx";
import RealtimeCallsView from "./views/RealtimeCallsView.jsx";
import RealtimeQueuesView from "./views/RealtimeQueuesView.jsx";
import RawEventsView from "./views/RawEventsView.jsx";
import AnsweredCdrView from "./views/AnsweredCdrView.jsx";
import UnansweredCdrView from "./views/UnansweredCdrView.jsx";
import OutboundView from "./views/OutboundView.jsx";
import SearchView from "./views/SearchView.jsx";
import InboundView from "./views/InboundView.jsx";
import AgentDailyView from "./views/AgentDailyView.jsx";
import QueueHourlyView from "./views/QueueHourlyView.jsx";
import UserAdminView from "./views/UserAdminView.jsx";
import LoginView from "./views/LoginView.jsx";
import AMIControlView from "./views/AMIControlView.jsx";

const VIEWS = [
  { id: "summary", label: "Сводка", component: SummaryView, permission: "summary" },
  { id: "answered", label: "Принятые", component: AnsweredView, permission: "answered" },
  { id: "unanswered", label: "Непринятые", component: UnansweredView, permission: "unanswered" },
  { id: "answered-cdr", label: "Принятые (CDR)", component: AnsweredCdrView, permission: "answered" },
  { id: "unanswered-cdr", label: "Непринятые (CDR)", component: UnansweredCdrView, permission: "unanswered" },
  { id: "outbound", label: "Исходящие", component: OutboundView, permission: "answered" },
  { id: "distribution", label: "Распределение", component: DistributionView, permission: "distribution" },
  { id: "agent-daily", label: "По агентам (даты)", component: AgentDailyView, permission: "distribution" },
  { id: "queue-hourly", label: "По очередям (часы)", component: QueueHourlyView, permission: "distribution" },
  { id: "analytics", label: "Аналитика", component: AnalyticsView, permission: "distribution" },
  { id: "inbound", label: "Входящие (DID/Trunk)", component: InboundView, permission: "distribution" },
  { id: "realtime-calls", label: "Звонки онлайн", component: RealtimeCallsView, permission: "realtime" },
  { id: "realtime-queues", label: "Очереди онлайн", component: RealtimeQueuesView, permission: "realtime" },
  { id: "search", label: "Поиск", component: SearchView, permission: "raw" },
  { id: "ami-control", label: "Управление AMI", component: AMIControlView, permission: "admin" },
  { id: "raw", label: "Сырые события", component: RawEventsView, permission: "raw" },
  { id: "users", label: "Пользователи", component: UserAdminView, permission: "admin" },
];

export default function App() {
  const { user, loading: authLoading, logout } = useAuth();
  const [activeView, setActiveView] = useState("summary");
  const { queues, agents, loading, error } = useMetaData(user);

  const allowed = useMemo(() => new Set(user?.allowed_reports ?? []), [user]);
  const availableViews = useMemo(
    () =>
      VIEWS.filter((view) => {
        if (!user) {
          return false;
        }
        if (view.permission === "admin") {
          return user.role === "admin";
        }
        if (allowed.has("*")) {
          return true;
        }
        return allowed.has(view.permission);
      }),
    [allowed, user],
  );

  const defaultView = availableViews[0]?.id ?? null;

  const CurrentView = useMemo(() => availableViews.find((view) => view.id === activeView)?.component, [activeView, availableViews]);

  if (authLoading) {
    return (
      <div className="app">
        <header className="app__header">
          <h1 className="app__title">Asterisk Queue Stats</h1>
        </header>
        <div className="view">
          <div className="card">Проверяем сессию…</div>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="app">
        <header className="app__header">
          <h1 className="app__title">Asterisk Queue Stats</h1>
          <p className="app__subtitle">Авторизация</p>
        </header>
        <LoginView />
      </div>
    );
  }

  if (!defaultView) {
    return (
      <div className="app">
        <header className="app__header">
          <h1 className="app__title">Asterisk Queue Stats</h1>
        </header>
        <div className="view">
          <div className="card error">Для роли {user.role} не настроены доступные разделы.</div>
        </div>
      </div>
    );
  }

  useEffect(() => {
    if (!availableViews.some((view) => view.id === activeView) && defaultView) {
      setActiveView(defaultView);
    }
  }, [availableViews, activeView, defaultView]);

  return (
    <div className="app">
      <header className="app__header">
        <h1 className="app__title">Asterisk Queue Stats</h1>
        <p className="app__subtitle">
          {user.first_name || user.last_name ? `${user.first_name} ${user.last_name}`.trim() : user.username} · роль {user.role}
        </p>
        <button type="button" onClick={logout} className="button" style={{ marginTop: "0.75rem" }}>
          Выйти
        </button>
      </header>

      <div className="app__content">
        <nav className="sidebar">
          {availableViews.map((view) => (
            <button
              key={view.id}
              type="button"
              className={`sidebar__button ${activeView === view.id ? "sidebar__button--active" : ""}`}
              onClick={() => setActiveView(view.id)}
            >
              {view.label}
            </button>
          ))}
        </nav>
        <main>
          {loading && (
            <div className="view">
              <div className="card">Загрузка справочников…</div>
            </div>
          )}
          {error && (
            <div className="view">
              <div className="card error">Не удалось получить очереди/агентов: {error.message}</div>
            </div>
          )}
          {!loading && !error && CurrentView && <CurrentView queues={queues} agents={agents} />}
        </main>
      </div>
    </div>
  );
}
