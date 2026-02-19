const normalize = (value) => String(value ?? "").trim().toLowerCase();

const expandAgentKeys = (value) => {
  const raw = String(value ?? "").trim();
  if (!raw) {
    return [];
  }

  const keys = new Set([raw]);
  const noSuffix = raw.split("@")[0];
  keys.add(noSuffix);

  const slashPart = noSuffix.includes("/") ? noSuffix.split("/").pop() : noSuffix;
  if (slashPart) {
    keys.add(slashPart);
    keys.add(slashPart.split("-")[0]);
  }

  keys.add(noSuffix.split("-")[0]);

  const digits = slashPart.replace(/\D+/g, "");
  if (digits) {
    keys.add(digits);
  }

  return Array.from(keys).filter(Boolean);
};

export const buildQueueNameMap = (queues = []) => {
  const map = new Map();
  for (const queue of queues) {
    const key = normalize(queue?.queuename);
    if (!key) {
      continue;
    }
    const label = String(queue?.descr || queue?.queuename || "").trim();
    if (label) {
      map.set(key, label);
    }
  }
  return map;
};

export const buildAgentNameMap = (agents = []) => {
  const map = new Map();
  for (const agent of agents) {
    const label = String(agent?.name || agent?.agent || "").trim();
    const keys = expandAgentKeys(agent?.agent);
    for (const key of keys) {
      map.set(normalize(key), label || String(agent?.agent || ""));
    }
  }
  return map;
};

export const formatQueueName = (value, queueNameMap) => {
  const key = normalize(value);
  if (!key) {
    return value;
  }
  return queueNameMap?.get(key) || value;
};

export const formatAgentName = (value, agentNameMap) => {
  for (const key of expandAgentKeys(value)) {
    const label = agentNameMap?.get(normalize(key));
    if (label) {
      return label;
    }
  }
  return value;
};
