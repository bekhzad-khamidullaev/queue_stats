import { useEffect, useState, useCallback } from "react";
import client from "../api/client.js";

export default function useMetaData(user) {
  const [queues, setQueues] = useState([]);
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    if (!user) {
      setQueues([]);
      setAgents([]);
      setLoading(false);
      setError(null);
      return;
    }

    const allowed = new Set(user.allowed_reports || []);
    const wantAgents = allowed.has("*") || allowed.has("answered") || allowed.has("distribution") || allowed.has("raw");

    setLoading(true);
    setError(null);

    try {
      const queueRequest = client.get("/meta/queues/");
      const agentRequest = wantAgents ? client.get("/meta/agents/") : Promise.resolve({ data: { agents: [] } });

      const [queuesRes, agentsRes] = await Promise.allSettled([queueRequest, agentRequest]);

      if (queuesRes.status === "fulfilled") {
        setQueues(queuesRes.value.data.queues ?? []);
      } else if (queuesRes.reason?.response?.status !== 403) {
        setError(queuesRes.reason);
      }

      if (agentsRes.status === "fulfilled") {
        setAgents(agentsRes.value.data.agents ?? []);
      } else if (agentsRes.reason?.response?.status !== 403) {
        setError(agentsRes.reason);
      }
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    if (user) {
      load();
    }
  }, [load, user]);

  return { queues, agents, loading, error };
}
