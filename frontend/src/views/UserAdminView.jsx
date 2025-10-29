import { useEffect, useState } from "react";
import client from "../api/client.js";
import { useAuth } from "../context/AuthContext.jsx";

const emptyUser = {
  username: "",
  password: "",
  first_name: "",
  last_name: "",
  email: "",
  role: "agent",
};

const ROLE_LABELS = {
  admin: "Администратор",
  supervisor: "Супервайзер",
  analyst: "Аналитик",
  agent: "Агент",
};

export default function UserAdminView() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState([]);
  const [formData, setFormData] = useState(emptyUser);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  const loadUsers = async () => {
    try {
      setLoading(true);
      const response = await client.get("/auth/users/");
      setUsers(response.data.users ?? []);
      setError(null);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadUsers();
  }, []);

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    try {
      await client.post("/auth/users/", formData);
      setFormData(emptyUser);
      await loadUsers();
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  };

  const removeUser = async (id) => {
    if (currentUser && currentUser.id === id) {
      setError(new Error("Нельзя удалить текущего пользователя"));
      return;
    }
    if (!window.confirm("Удалить пользователя?")) {
      return;
    }
    try {
      await client.delete(`/auth/users/${id}/`);
      await loadUsers();
    } catch (err) {
      setError(err);
    }
  };

  return (
    <div className="view">
      <div className="card">
        <h2 className="card__title">Управление пользователями</h2>
        <form className="filters" style={{ flexWrap: "wrap" }} onSubmit={submit}>
          <div className="filters__column">
            <label htmlFor="username">Логин</label>
            <input
              id="username"
              required
              value={formData.username}
              onChange={(event) => setFormData((prev) => ({ ...prev, username: event.target.value }))}
            />
          </div>
          <div className="filters__column">
            <label htmlFor="password">Пароль</label>
            <input
              id="password"
              required
              type="password"
              value={formData.password}
              onChange={(event) => setFormData((prev) => ({ ...prev, password: event.target.value }))}
            />
          </div>
          <div className="filters__column">
            <label htmlFor="first_name">Имя</label>
            <input
              id="first_name"
              value={formData.first_name}
              onChange={(event) => setFormData((prev) => ({ ...prev, first_name: event.target.value }))}
            />
          </div>
          <div className="filters__column">
            <label htmlFor="last_name">Фамилия</label>
            <input
              id="last_name"
              value={formData.last_name}
              onChange={(event) => setFormData((prev) => ({ ...prev, last_name: event.target.value }))}
            />
          </div>
          <div className="filters__column">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              value={formData.email}
              onChange={(event) => setFormData((prev) => ({ ...prev, email: event.target.value }))}
            />
          </div>
          <div className="filters__column">
            <label htmlFor="role">Роль</label>
            <select
              id="role"
              value={formData.role}
              onChange={(event) => setFormData((prev) => ({ ...prev, role: event.target.value }))}
            >
              {Object.entries(ROLE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <div className="filters__column">
            <label>&nbsp;</label>
            <button type="submit" disabled={saving}>
              {saving ? "Создание…" : "Создать"}
            </button>
          </div>
        </form>
        {error && <div className="error">{error.response?.data?.detail || error.message}</div>}
      </div>
      <div className="card">
        <h3 className="card__title">Пользователи</h3>
        {loading ? (
          <div className="muted">Загрузка…</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Логин</th>
                <th>Имя</th>
                <th>Роль</th>
                <th>Email</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              {users.map((item) => (
                <tr key={item.id}>
                  <td>{item.username}</td>
                  <td>
                    {item.last_name} {item.first_name}
                  </td>
                  <td>{ROLE_LABELS[item.role] || item.role}</td>
                  <td>{item.email}</td>
                  <td>
                    <button type="button" onClick={() => removeUser(item.id)} className="button button--danger">
                      Удалить
                    </button>
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
