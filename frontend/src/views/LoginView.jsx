import { useState } from "react";
import { useAuth } from "../context/AuthContext.jsx";

export default function LoginView() {
  const { login, error } = useAuth();
  const [credentials, setCredentials] = useState({ username: "", password: "" });
  const [remember, setRemember] = useState(true);
  const [submissionError, setSubmissionError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setSubmissionError(null);
    try {
      await login(credentials, remember);
    } catch (err) {
      setSubmissionError(err.response?.data?.detail || err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="view">
      <div className="card" style={{ maxWidth: "400px", margin: "4rem auto" }}>
        <h2 className="card__title">Вход в систему</h2>
        <form onSubmit={onSubmit} className="filters" style={{ flexDirection: "column", gap: "0.75rem" }}>
          <div className="filters__column" style={{ width: "100%" }}>
            <label htmlFor="username">Логин</label>
            <input
              id="username"
              value={credentials.username}
              onChange={(event) => setCredentials((prev) => ({ ...prev, username: event.target.value }))}
            />
          </div>
          <div className="filters__column" style={{ width: "100%" }}>
            <label htmlFor="password">Пароль</label>
            <input
              id="password"
              type="password"
              value={credentials.password}
              onChange={(event) => setCredentials((prev) => ({ ...prev, password: event.target.value }))}
            />
          </div>
          <div className="filters__column" style={{ width: "100%" }}>
            <label htmlFor="remember" style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <input
                id="remember"
                type="checkbox"
                checked={remember}
                onChange={(event) => setRemember(event.target.checked)}
              />
              Запомнить меня
            </label>
          </div>
          <button type="submit" disabled={submitting}>
            {submitting ? "Проверяем…" : "Войти"}
          </button>
          {(submissionError || error) && (
            <div className="error" style={{ width: "100%" }}>
              {submissionError || error.message}
            </div>
          )}
        </form>
      </div>
    </div>
  );
}
