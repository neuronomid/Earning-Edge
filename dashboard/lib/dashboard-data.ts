export type RecommendationStatus = "recommend" | "watchlist" | "no_trade";
export type FeedbackAction = "bought" | "skipped";

export type DashboardUser = {
  id: string;
  username?: string | null;
  name: string;
  broker: string;
  timezone: string;
  timezoneLabel: string;
  accountSize: number;
  riskProfile: string;
  strategyPermission: string;
  maxContracts: number;
};

export type DashboardSystem = {
  openRouterStatus: string;
  openRouterKeyDisplay?: string | null;
  alpacaStatus: string;
  alpacaKeyDisplay?: string | null;
  alpacaSecretDisplay?: string | null;
  alphaVantageStatus: string;
  alphaVantageKeyDisplay?: string | null;
  heavyModel: string;
  lightModel: string;
};

export type DashboardRecommendation = {
  id: string;
  rank: number;
  setupLabel: string;
  status: RecommendationStatus;
  ticker: string;
  companyName: string;
  strategySource: string;
  strategyLabel: string;
  direction: "Bullish" | "Bearish";
  optionType: "Call" | "Put";
  positionSide: "Long" | "Short";
  strike: number;
  expiry: string;
  earningsDate: string;
  earningsTiming: string;
  currentPrice: number;
  contractId: string;
  contractSymbol?: string | null;
  bidPrice: number | null;
  askPrice: number | null;
  midPrice: number | null;
  lastPrice: number | null;
  contractSource: string;
  suggestedEntry: number;
  markPremium: number;
  suggestedQuantity: number;
  estimatedMaxLoss: string;
  accountRiskPercent: number;
  confidenceScore: number;
  riskLevel: string;
  finalScore: number;
  directionScore: number;
  contractScore: number;
  dataConfidence: number;
  delta: number;
  impliedVolatility: number;
  spreadPercent: number;
  volume: number;
  openInterest: number;
  breakeven: number;
  expectedMove: string;
  reasonSummary: string;
  keyEvidence: string[];
  keyConcerns: string[];
  llmDecisionNote: string;
  warningText?: string | null;
  feedbackAction?: FeedbackAction | null;
};

export type CandidateRow = {
  ticker: string;
  companyName: string;
  strategySource: string;
  direction: string;
  finalScore: number;
  directionScore: number;
  dataConfidence: number;
  currentPrice: number;
  earningsDate: string | null;
  relativeVolume: number;
  optionQuality: string;
  sector: string;
  note: string;
};

export type WorkflowRunCard = {
  id: string;
  startedAt: string;
  triggerType: "manual" | "cron";
  status: "success" | "partial" | "failed" | "no_trade" | string;
  screenerStatus: "success" | "partial" | "failed" | string;
  selectedTicker: string | null;
  contractsConsidered: number;
  finalistsSentToLlm: number;
  llmTriggered: boolean;
  decisionEngine: string | null;
  modelUsed: string | null;
  warningText?: string | null;
  summary: string;
  watchlist: string[];
};

export type ScheduleEntry = {
  id: string;
  weekday: string;
  localTime: string;
  timezone: string;
  status: "active" | "paused";
};

export type PipelineStep = {
  id: string;
  label: string;
  provider: string;
  status: string;
  candidateCount: number;
  fallbackUsed: boolean;
};

export type DashboardSnapshot = {
  mode: "live" | "demo";
  user: DashboardUser;
  snapshotDate: string | null;
  warningText?: string | null;
  selectedRecommendationId: string | null;
  recommendations: DashboardRecommendation[];
  candidateUniverse: CandidateRow[];
  recentRuns: WorkflowRunCard[];
  schedules: ScheduleEntry[];
  system: DashboardSystem;
  telegramMessageText?: string | null;
  pipelineSteps: PipelineStep[];
};

export type PaperPosition = {
  id: string;
  recommendationId: string;
  ticker: string;
  companyName: string;
  optionType: "Call" | "Put";
  positionSide: "Long" | "Short";
  strike: number;
  expiry: string;
  quantity: number;
  entryPremium: number;
  currentPremium: number;
  capitalReserved: number;
  maxLossText: string;
  thesis: string;
  openedAt: string;
  closedAt?: string;
  status: "open" | "closed";
  closedPremium?: number;
  stopLoss?: number | null;
  takeProfit?: number | null;
  triggeredBy?: "stop_loss" | "take_profit" | null;
};

export type ActivityItem = {
  id: string;
  title: string;
  detail: string;
  tone: "positive" | "neutral" | "warning";
  timestamp: string;
};

export type PaperState = {
  startingBalance: number;
  positions: PaperPosition[];
  feedback: Record<string, FeedbackAction>;
  activity: ActivityItem[];
};

export const demoSnapshot: DashboardSnapshot = {
  mode: "demo",
  user: {
    id: "demo-user",
    username: "demo",
    name: "Trader 1234",
    broker: "IBKR Paper",
    timezone: "Eastern (ET)",
    timezoneLabel: "ET",
    accountSize: 150000,
    riskProfile: "Balanced",
    strategyPermission: "long_and_short",
    maxContracts: 3,
  },
  snapshotDate: "2026-05-06T14:36:00.000Z",
  warningText: null,
  selectedRecommendationId: "rec-amd-primary",
  recommendations: [
    {
      id: "rec-amd-primary",
      rank: 1,
      setupLabel: "Best setup",
      status: "recommend",
      ticker: "AMD",
      companyName: "Advanced Micro Devices",
      strategySource: "Catalyst Confluence",
      strategyLabel: "Long Call",
      direction: "Bullish",
      optionType: "Call",
      positionSide: "Long",
      strike: 104,
      expiry: "2026-05-16",
      earningsDate: "2026-05-08",
      earningsTiming: "AMC",
      currentPrice: 102.4,
      contractId: "rec-amd-primary:AMD:2026-05-16:CALL:104.00",
      contractSymbol: "AMD260516C00104000",
      bidPrice: 1.55,
      askPrice: 1.69,
      midPrice: 1.62,
      lastPrice: 1.6,
      contractSource: "demo",
      suggestedEntry: 1.25,
      markPremium: 1.62,
      suggestedQuantity: 2,
      estimatedMaxLoss: "$125.00 max loss per contract",
      accountRiskPercent: 2,
      confidenceScore: 82,
      riskLevel: "High",
      finalScore: 82,
      directionScore: 80,
      contractScore: 84,
      dataConfidence: 88,
      delta: 0.52,
      impliedVolatility: 44,
      spreadPercent: 12.4,
      volume: 120,
      openInterest: 320,
      breakeven: 105.25,
      expectedMove: "6.4%",
      reasonSummary:
        "AMD carried the cleanest mix of momentum, earnings catalyst alignment, and option liquidity in the finalist set.",
      keyEvidence: [
        "Trend stayed constructive across 20, 50, and 200 day context.",
        "The selected contract kept a realistic breakeven relative to expected move.",
        "News tone was supportive without needing heroic assumptions.",
        "This was the highest final score in the stored run artifacts.",
      ],
      keyConcerns: [
        "IV crush can hurt the premium even if the stock moves the right way.",
        "The setup still depends on disciplined sizing through earnings.",
        "A weak broader tape could flatten the follow-through.",
      ],
      llmDecisionNote:
        "The heavy decision layer selected AMD from the top four finalists after scoring narrowed the field.",
    },
    {
      id: "rec-aapl-alt",
      rank: 2,
      setupLabel: "2nd best setup",
      status: "watchlist",
      ticker: "AAPL",
      companyName: "Apple",
      strategySource: "Catalyst Confluence",
      strategyLabel: "Long Call",
      direction: "Bullish",
      optionType: "Call",
      positionSide: "Long",
      strike: 195,
      expiry: "2026-05-16",
      earningsDate: "2026-05-08",
      earningsTiming: "AMC",
      currentPrice: 190.15,
      contractId: "rec-aapl-alt:AAPL:2026-05-16:CALL:195.00",
      contractSymbol: "AAPL260516C00195000",
      bidPrice: 2.62,
      askPrice: 2.86,
      midPrice: 2.74,
      lastPrice: 2.72,
      contractSource: "demo",
      suggestedEntry: 2.4,
      markPremium: 2.74,
      suggestedQuantity: 0,
      estimatedMaxLoss: "$240.00 max loss per contract",
      accountRiskPercent: 2,
      confidenceScore: 64,
      riskLevel: "Moderate",
      finalScore: 64,
      directionScore: 70,
      contractScore: 67,
      dataConfidence: 79,
      delta: 0.47,
      impliedVolatility: 31,
      spreadPercent: 9.1,
      volume: 212,
      openInterest: 610,
      breakeven: 197.4,
      expectedMove: "4.3%",
      reasonSummary:
        "AAPL stayed attractive, but the overall opportunity was better as a watchlist than a fully sized paper entry.",
      keyEvidence: [
        "Liquidity and spread quality remained clean.",
        "Relative strength held up better than most mega-cap peers.",
        "The contract survived the hard filters with a stable spread profile.",
      ],
      keyConcerns: [
        "The final score stayed below the live recommendation threshold.",
        "Directional edge was softer than AMD after contract scoring.",
      ],
      llmDecisionNote:
        "This is the next alternative the dashboard should surface if the user rejects AMD.",
    },
  ],
  candidateUniverse: [
    {
      ticker: "AMD",
      companyName: "Advanced Micro Devices",
      strategySource: "Catalyst Confluence",
      direction: "Bullish",
      finalScore: 82,
      directionScore: 80,
      dataConfidence: 88,
      currentPrice: 102.4,
      earningsDate: "2026-05-08",
      relativeVolume: 1.9,
      optionQuality: "Tight call spread",
      sector: "Semiconductors",
      note: "Highest final score with the strongest contract fit.",
    },
    {
      ticker: "AAPL",
      companyName: "Apple",
      strategySource: "Catalyst Confluence",
      direction: "Bullish",
      finalScore: 64,
      directionScore: 70,
      dataConfidence: 79,
      currentPrice: 190.15,
      earningsDate: "2026-05-08",
      relativeVolume: 1.4,
      optionQuality: "Watchlist viable",
      sector: "Consumer Electronics",
      note: "Good contract, softer edge than the lead idea.",
    },
  ],
  recentRuns: [
    {
      id: "run-2026-05-05",
      startedAt: "2026-05-05T14:30:00.000Z",
      triggerType: "manual",
      status: "success",
      screenerStatus: "success",
      selectedTicker: "AMD",
      contractsConsidered: 8,
      finalistsSentToLlm: 4,
      llmTriggered: true,
      decisionEngine: "llm",
      modelUsed: "anthropic/claude-opus-4.7",
      summary:
        "Finviz loaded normally, ten candidates were scored, and the lead contract came from AMD.",
      watchlist: ["AAPL", "MSFT", "NFLX"],
    },
  ],
  schedules: [
    {
      id: "sched-mon",
      weekday: "Monday",
      localTime: "10:30 AM",
      timezone: "Eastern (ET)",
      status: "active",
    },
    {
      id: "sched-wed",
      weekday: "Wednesday",
      localTime: "01:15 PM",
      timezone: "Eastern (ET)",
      status: "active",
    },
  ],
  system: {
    openRouterStatus: "Configured",
    openRouterKeyDisplay: "sk-or-v1...demo",
    alpacaStatus: "Connected",
    alphaVantageStatus: "Connected",
    heavyModel: "anthropic/claude-opus-4.7",
    lightModel: "google/gemini-3.1-flash-lite-preview",
  },
  telegramMessageText: null,
  pipelineSteps: [
    {
      id: "step-1",
      label: "Catalyst Confluence",
      provider: "Finviz",
      status: "success",
      candidateCount: 6,
      fallbackUsed: false,
    },
    {
      id: "step-2",
      label: "Liquid Momentum Setup",
      provider: "Finviz",
      status: "success",
      candidateCount: 4,
      fallbackUsed: false,
    },
  ],
};

export const disconnectedSnapshot: DashboardSnapshot = {
  mode: "demo",
  user: {
    id: "disconnected-user",
    username: null,
    name: "Dashboard not connected",
    broker: "Unknown",
    timezone: "Eastern (ET)",
    timezoneLabel: "ET",
    accountSize: 0,
    riskProfile: "Balanced",
    strategyPermission: "long_and_short",
    maxContracts: 0,
  },
  snapshotDate: null,
  warningText: "Live dashboard data is unavailable right now.",
  selectedRecommendationId: null,
  recommendations: [],
  candidateUniverse: [],
  recentRuns: [],
  schedules: [],
  system: {
    openRouterStatus: "Missing",
    openRouterKeyDisplay: null,
    alpacaStatus: "Not connected",
    alphaVantageStatus: "Not connected",
    heavyModel: "anthropic/claude-opus-4.7",
    lightModel: "google/gemini-3.1-flash-lite-preview",
  },
  telegramMessageText: null,
  pipelineSteps: [],
};

export const defaultPaperState: PaperState = {
  startingBalance: 150000,
  positions: [],
  feedback: {},
  activity: [],
};
