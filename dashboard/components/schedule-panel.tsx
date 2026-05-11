"use client";

import { type ScheduleEntry } from "@/lib/dashboard-data";

export function SchedulePanel({ schedules }: { schedules: ScheduleEntry[] }) {
  return (
    <div className="flex flex-col gap-5">
      <h2 className="text-base font-semibold text-white">Schedule</h2>
      <div className="flex flex-col gap-2">
        {schedules.map((sched) => (
          <div
            key={sched.id}
            className="rounded-md border border-white/[0.06] bg-[#161b22] p-4 flex items-center justify-between"
          >
            <div>
              <div className="text-sm font-semibold text-white">{sched.weekday}</div>
              <div className="text-xs text-[#8b949e]">
                {sched.localTime} · {sched.timezone}
              </div>
            </div>
            <span
              className={`text-[10px] px-2 py-0.5 rounded font-medium ${
                sched.status === "active"
                  ? "bg-[#238636]/10 text-[#3fb950]"
                  : "bg-[#d29922]/10 text-[#e3b341]"
              }`}
            >
              {sched.status}
            </span>
          </div>
        ))}
        {schedules.length === 0 && (
          <div className="text-sm text-[#8b949e] text-center py-8">No schedules configured yet.</div>
        )}
      </div>
    </div>
  );
}
