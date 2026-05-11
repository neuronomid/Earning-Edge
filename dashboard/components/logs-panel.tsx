"use client";

export function LogsPanel() {
  const logs = [
    { level: "info", message: "Dashboard initialized", time: "2026-05-06T10:00:00Z" },
    { level: "info", message: "Connected to FastAPI backend", time: "2026-05-06T10:00:01Z" },
    { level: "info", message: "Loaded demo snapshot as fallback", time: "2026-05-06T10:00:02Z" },
  ];

  return (
    <div className="flex flex-col gap-5">
      <h2 className="text-base font-semibold text-white">Logs</h2>
      <div className="rounded-md border border-white/[0.06] bg-[#0d1016] p-4 font-mono text-xs overflow-x-auto">
        {logs.map((log, i) => (
          <div key={i} className="flex gap-3 py-1 border-b border-white/[0.04] last:border-0">
            <span className="text-[#484f58] shrink-0">{new Date(log.time).toLocaleTimeString()}</span>
            <span
              className={`shrink-0 w-10 font-medium ${
                log.level === "info" ? "text-[#58a6ff]" : log.level === "warn" ? "text-[#e3b341]" : "text-[#f85149]"
              }`}
            >
              {log.level}
            </span>
            <span className="text-[#c9d1d9]">{log.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
