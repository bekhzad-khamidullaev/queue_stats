import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import client from "../api/client.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchProfile = useCallback(async () => {
    try {
      setLoading(true);
      const response = await client.get("/auth/me/");
      setUser(response.data.user);
      setError(null);
    } catch (err) {
      setUser(null);
      setError(err.response && err.response.status === 401 ? null : err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchProfile();
  }, [fetchProfile]);

  const login = useCallback(
    async (credentials) => {
      const response = await client.post("/auth/login/", credentials);
      setUser(response.data.user);
      setError(null);
      return response.data.user;
    },
    [],
  );

  const logout = useCallback(async () => {
    await client.post("/auth/logout/");
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({
      user,
      loading,
      error,
      login,
      logout,
      refresh: fetchProfile,
    }),
    [user, loading, error, login, logout, fetchProfile],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}

