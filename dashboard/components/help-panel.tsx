"use client";

export function HelpPanel() {
  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <div className="text-lg font-bold">Help</div>

      <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
        <div className="text-sm font-bold mb-2">What is Earning Edge?</div>
        <p className="text-xs text-slate-400 leading-relaxed">
          Earning Edge scans the largest companies reporting earnings next week, studies option
          chains, and recommends one clear setup per scan — never both a call and a put for the same
          stock. The dashboard mirrors the Telegram bot experience with an interactive paper-trading
          simulator.
        </p>
      </div>

      <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
        <div className="text-sm font-bold mb-2">How does paper trading work?</div>
        <p className="text-xs text-slate-400 leading-relaxed">
          When you click "I bought it" on a Recommended setup, a paper position is automatically
          created with the suggested quantity and entry premium. You can track open positions, close
          them at any premium, and monitor your P&L. All paper data is stored locally in your
          browser.
        </p>
      </div>

      <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
        <div className="text-sm font-bold mb-2">Actions available</div>
        <ul className="text-xs text-slate-400 leading-relaxed space-y-1">
          <li><b>Why this?</b> — View the reasoning and evidence behind the recommendation.</li>
          <li><b>Risk / Sizing</b> — See contract details, strike, expiry, and risk budget.</li>
          <li><b>Save Note</b> — Store a quick decision note locally.</li>
          <li><b>Alternatives</b> — Load the next-best setup from the candidate pool.</li>
          <li><b>I bought it</b> — Mark as acknowledged and auto-create a paper position.</li>
          <li><b>I skipped it</b> — Log the setup as skipped for your audit trail.</li>
        </ul>
      </div>

      <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
        <div className="text-sm font-bold mb-2">Running a scan</div>
        <p className="text-xs text-slate-400 leading-relaxed">
          Click "Run Scan Now" in the top bar to trigger a manual scan. This runs the same pipeline
          as the Telegram bot: Finviz screener, candidate validation, option chain scoring, and
          LLM-based decision.
        </p>
      </div>
    </div>
  );
}
