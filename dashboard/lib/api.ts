const API_BASE =
  process.env.NEXT_PUBLIC_EARNING_EDGE_API_BASE_URL?.replace(/\/$/, "") ??
  "http://127.0.0.1:8000";

async function localRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!response.ok) {
    let detail = `Request failed: ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) detail = payload.detail;
    } catch {
      // Preserve the status fallback for non-JSON bodies.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!response.ok) {
    let detail = `Request failed: ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        detail = payload.detail;
      }
    } catch {
      // Ignore non-JSON error bodies and preserve the HTTP status message.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function withUser(path: string, userId?: string) {
  if (!userId) return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}user_id=${encodeURIComponent(userId)}`;
}

export type DashboardAuthResponse = {
  status: string;
  message: string;
  user: import("@/lib/dashboard-data").DashboardUser;
};

export type DashboardSettingsUpdate = Partial<{
  accountSize: number;
  riskProfile: string;
  timezoneLabel: string;
  broker: string;
  strategyPermission: string;
  maxContracts: number;
}>;

export async function registerDashboardUser(username: string, password: string) {
  return request<DashboardAuthResponse>("/api/dashboard/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function loginDashboardUser(username: string, password: string) {
  return request<DashboardAuthResponse>("/api/dashboard/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function fetchDashboardSnapshot(userId?: string) {
  return request<import("@/lib/dashboard-data").DashboardSnapshot>(
    withUser("/api/dashboard/snapshot", userId),
  );
}

export async function fetchRecommendationAction(
  recommendationId: string,
  action: "why" | "risk" | "save-note",
) {
  return request<{ title: string; html: string }>(
    `/api/dashboard/recommendations/${recommendationId}/${action}`,
  );
}

export async function submitRecommendationFeedback(
  recommendationId: string,
  action: "bought" | "skipped",
) {
  return request<{ status: string; message: string }>(
    `/api/dashboard/recommendations/${recommendationId}/feedback`,
    {
      method: "POST",
      body: JSON.stringify({ action }),
    },
  );
}

export async function fetchNextAlternative(recommendationId: string) {
  return request<{
    status: "ok" | "empty";
    message: string;
    recommendation?: import("@/lib/dashboard-data").DashboardRecommendation;
  }>(`/api/dashboard/recommendations/${recommendationId}/alternatives`, {
    method: "POST",
  });
}

export async function runScan(userId?: string) {
  return request<{
    outcome: string;
    run_id: string | null;
    error_message: string | null;
    missing?: string[];
  }>(withUser("/api/dashboard/run-scan", userId), { method: "POST" });
}

export async function updateDashboardSettings(payload: DashboardSettingsUpdate, userId?: string) {
  return request<{
    status: string;
    message: string;
    user: import("@/lib/dashboard-data").DashboardUser;
  }>(withUser("/api/dashboard/settings", userId), {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function updateOpenRouterKey(apiKey: string, userId?: string) {
  return request<{ status: string; message: string }>(withUser("/api/dashboard/api-keys/openrouter", userId), {
    method: "POST",
    body: JSON.stringify({ apiKey }),
  });
}

export async function removeOpenRouterKey(userId?: string) {
  return request<{ status: string; message: string }>(withUser("/api/dashboard/api-keys/openrouter", userId), {
    method: "DELETE",
  });
}

export async function updateAlpacaCredentials(apiKey: string, apiSecret: string, userId?: string) {
  return request<{ status: string; message: string }>(withUser("/api/dashboard/api-keys/alpaca", userId), {
    method: "POST",
    body: JSON.stringify({ apiKey, apiSecret }),
  });
}

export async function removeAlpacaCredentials(userId?: string) {
  return request<{ status: string; message: string }>(withUser("/api/dashboard/api-keys/alpaca", userId), {
    method: "DELETE",
  });
}

export async function updateAlphaVantageKey(apiKey: string, userId?: string) {
  return request<{ status: string; message: string }>(withUser("/api/dashboard/api-keys/alpha-vantage", userId), {
    method: "POST",
    body: JSON.stringify({ apiKey }),
  });
}

export async function removeAlphaVantageKey(userId?: string) {
  return request<{ status: string; message: string }>(withUser("/api/dashboard/api-keys/alpha-vantage", userId), {
    method: "DELETE",
  });
}

export async function fetchSimulationAccount(accountId: string, startingCash: number) {
  return localRequest<import("@/types/simulation").SimulationAccount>(
    `/api/simulation/account/${encodeURIComponent(accountId)}?startingCash=${encodeURIComponent(startingCash)}`,
  );
}

export async function placeSimulationOrder(
  payload: import("@/types/simulation").PlaceOrderPayload,
) {
  return localRequest<import("@/types/simulation").PlaceOrderResponse>("/api/simulation/orders", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function cancelSimulationOrder(orderId: string) {
  return localRequest<import("@/types/simulation").SimulationAccount>(
    `/api/simulation/orders/${encodeURIComponent(orderId)}/cancel`,
    { method: "POST" },
  );
}

export async function updateSimulationPositionRisk(
  positionId: string,
  payload: import("@/types/simulation").RiskUpdatePayload,
) {
  return localRequest<import("@/types/simulation").SimulationAccount>(
    `/api/simulation/positions/${encodeURIComponent(positionId)}/risk`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}
