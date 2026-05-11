"use client";

import { FormEvent, useState } from "react";
import {
  loginDashboardUser,
  registerDashboardUser,
  type DashboardAuthResponse,
} from "@/lib/api";

export function AuthPanel({
  onAuthenticated,
}: {
  onAuthenticated: (response: DashboardAuthResponse) => void;
}) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("");
    setBusy(true);
    try {
      const action = mode === "login" ? loginDashboardUser : registerDashboardUser;
      const response = await action(username.trim(), password);
      onAuthenticated(response);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Authentication failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-[#070a0f] text-[#e2e4e9]">
      <div className="mx-auto flex min-h-screen max-w-[480px] flex-col justify-center px-6">
        <div className="mb-8 flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-[#2f81f7] text-sm font-bold text-white">
            EE
          </div>
          <div>
            <h1 className="text-lg font-semibold tracking-tight text-white">Earning Edge</h1>
            <p className="text-xs text-[#8b949e]">Dashboard access</p>
          </div>
        </div>

        <form
          onSubmit={(event) => void handleSubmit(event)}
          className="rounded-lg border border-white/[0.06] bg-[#161b22] p-5"
        >
          <div className="mb-5 grid grid-cols-2 rounded-md border border-white/[0.06] bg-[#0d1016] p-1">
            <button
              type="button"
              onClick={() => setMode("login")}
              className={`rounded px-3 py-2 text-sm font-medium transition ${
                mode === "login"
                  ? "bg-[#238636] text-white"
                  : "text-[#8b949e] hover:text-white"
              }`}
            >
              Login
            </button>
            <button
              type="button"
              onClick={() => setMode("register")}
              className={`rounded px-3 py-2 text-sm font-medium transition ${
                mode === "register"
                  ? "bg-[#238636] text-white"
                  : "text-[#8b949e] hover:text-white"
              }`}
            >
              Register
            </button>
          </div>

          <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-[#8b949e]">
            Username
          </label>
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            minLength={2}
            maxLength={40}
            autoComplete="username"
            className="mb-4 w-full rounded-md border border-white/[0.06] bg-[#0d1016] px-3 py-2 text-sm text-white outline-none transition focus:border-[#2f81f7]"
            required
          />

          <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-[#8b949e]">
            Password
          </label>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            minLength={4}
            maxLength={128}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            className="mb-5 w-full rounded-md border border-white/[0.06] bg-[#0d1016] px-3 py-2 text-sm text-white outline-none transition focus:border-[#2f81f7]"
            required
          />

          {status && (
            <div className="mb-4 rounded-md border border-[#f85149]/20 bg-[#f85149]/10 px-3 py-2 text-xs text-[#ffb3ad]">
              {status}
            </div>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-md bg-[#238636] px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-[#2ea043] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {busy ? "Working..." : mode === "login" ? "Login" : "Register"}
          </button>
        </form>
      </div>
    </main>
  );
}
