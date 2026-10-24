export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Health = {
  status: "ok" | "degraded";
  app: string;
  environment: string;
  trading_mode: string;
  server_time: string;
  database: { ok: boolean; error: string | null };
  data_provider: { name: string; configured: boolean };
};

export type AppConfig = {
  trading_mode: string;
  instruments: string[];
  granularity: string;
  data_provider: string;
  risk: {
    account_currency: string;
    account_balance: number;
    max_trade_allocation_percent: number;
    max_trade_allocation: number;
    max_risk_percent: number;
    max_risk_amount: number;
    leverage_forex: number;
    leverage_metal: number;
    max_open_trades: number;
    max_daily_loss_percent: number;
    stop_loss_atr_multiplier: number;
    take_profit_atr_multiplier: number;
    target_risk_reward: number;
  };
  signal: { probability_threshold: number; prediction_horizon_candles: number };
};

export type InstrumentInfo = {
  name: string;
  display_name: string;
  description: string;
  asset_class: "forex" | "metal";
  pip_size: number;
  display_precision: number;
  unit_label: string;
  candles: number;
  last_time: string | null;
  validation_status: ValidationStatus | null;
};

export type RiskPreview = {
  instrument: string;
  direction: "BUY" | "SELL";
  units: number;
  tradable: boolean;
  reason: string | null;
  limited_by: "risk" | "allocation";
  entry: number;
  stop_loss: number;
  take_profit: number;
  stop_distance_pips: number;
  max_risk_amount: number;
  risk_amount: number;
  max_allocation: number;
  margin_required: number;
  leverage: number;
  position_value: number;
  potential_profit: number;
  risk_reward: number;
  atr_pips: number;
  as_of: string;
};

export type Indicators = {
  instrument: string;
  time: string;
  close: number | null;
  rsi_14: number | null;
  macd: number | null;
  macd_signal: number | null;
  macd_hist: number | null;
  atr_14: number | null;
  atr_pips: number | null;
  ema20: number | null;
  ema50: number | null;
  ema200: number | null;
  bb_upper: number | null;
  bb_lower: number | null;
  atr_ratio_100: number | null;
  volatility: string;
  trend: string;
  session: string;
  display_precision: number;
};

export type TradeStats = {
  trades: number;
  expectancy_r: number | null;
  lower_bound_r?: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  total_r?: number | null;
  positive_fold_share?: number | null;
};

type Period = { start: string; end: string; rows: number };

export type ModelSummary = {
  version: string;
  created_at: string;
  model: string;
  deployable: boolean;
  not_deployable_reasons: string[];
  threshold: number;
  instruments: string[];
  periods: { train: Period; validation: Period; test: Period };
  test: TradeStats & {
    by_instrument: Record<string, TradeStats>;
    classification: {
      log_loss: number;
      log_loss_baseline: number;
      confusion_matrix: { labels: string[]; matrix: number[][] };
    };
  };
  comparison: Record<string, { threshold: number; validation: TradeStats | null; walk_forward: TradeStats; log_loss: number; log_loss_baseline: number }>;
  feature_importance: Record<string, number>;
};

export type GroupStats = { trades: number; pnl: number; win_rate: number; avg_r: number };

export type BacktestMetrics = {
  starting_balance: number;
  final_balance: number;
  total_return_pct: number;
  trades: number;
  win_rate?: number;
  loss_rate?: number;
  profit_factor?: number | null;
  max_drawdown_pct?: number;
  sharpe_ratio?: number | null;
  average_trade?: number;
  average_winner?: number | null;
  average_loser?: number | null;
  average_r?: number;
  average_pips_gained?: number | null;
  average_pips_lost?: number | null;
  longest_winning_streak?: number;
  longest_losing_streak?: number;
  by_side?: Record<string, GroupStats>;
  by_instrument?: Record<string, GroupStats>;
  by_session?: Record<string, GroupStats>;
  by_year?: Record<string, GroupStats>;
  by_month?: Record<string, GroupStats>;
  risk_of_ruin?: { prob_drawdown_20pct?: number; prob_drawdown_50pct?: number; median_final_balance?: number };
};

export type BacktestTrade = Record<string, string | number | null>;

export type BacktestResult = {
  version: string;
  model: string;
  granularity: string;
  period: "test" | "walk_forward";
  start: string;
  end: string;
  signals: number;
  skipped: Record<string, number>;
  config: { risk_percent: number; max_open_trades: number; max_daily_loss_percent: number; threshold: number;
    sl_atr: number; tp_atr: number };
  metrics: BacktestMetrics;
  available_periods: string[];
  equity: { time: string; balance: number; drawdown_pct: number }[];
  trades: BacktestTrade[];
  trades_total: number;
};

export type SignalRow = {
  id: number;
  instrument: string;
  granularity: string;
  candle_time: string;
  created_at: string;
  expires_at: string | null;
  model_version: string | null;
  mode: "practice" | "proven";
  p_buy: number | null;
  p_wait: number | null;
  p_sell: number | null;
  model_decision: "BUY" | "SELL" | "WAIT";
  decision: "BUY" | "SELL" | "WAIT";
  reason: string | null;
  entry: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  atr: number | null;
  units: number | null;
  risk_amount: number | null;
  potential_profit: number | null;
  risk_reward: number | null;
  margin_required: number | null;
  balance: number | null;
  status: "actionable" | "taken" | "skipped" | "expired" | "info";
  outcome_r: number | null;
  outcome_reason: string | null;
};

export type CoachTrade = {
  id: number;
  signal_id: number | null;
  instrument: string;
  side: "BUY" | "SELL";
  units: number;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  risk_amount: number;
  opened_at: string;
  close_by: string;
  status: "open" | "closed";
  advice: "close" | "warn" | null;
  advice_reason: string | null;
  last_price: number | null;
  exit_price: number | null;
  closed_at: string | null;
  close_reason: string | null;
  pips: number | null;
  pnl: number | null;
  r_multiple: number | null;
  balance_after: number | null;
};

export type CoachStats = {
  balance: number;
  starting_balance: number;
  your_trades: { closed: number; open: number; total_pnl: number; win_rate: number | null; average_r: number | null };
  ai_track_record: { calls: number; scored: number; average_r: number | null; win_rate: number | null; total_r: number };
  signals_followed: number;
  signals_skipped: number;
  signals_expired: number;
};

export type LiveStatus = {
  running: boolean;
  message: string;
  last_poll: string | null;
  last_candle: Record<string, string>;
  prices: Record<string, { instrument: string; price: number; time: string; source: "stream" | "candle" }>;
  stream_symbols: string[];
  stream_connected: boolean;
  requests_today: number;
  errors: { time: string; message: string }[];
  coach_mode?: string;
};

export type ChartData = {
  instrument: string;
  granularity: string;
  display_precision: number;
  candles: { time: number; open: number; high: number; low: number; close: number }[];
  ema20: { time: number; value: number }[];
  ema50: { time: number; value: number }[];
  ema200: { time: number; value: number }[];
  signals: { id: number; time: number; decision: "BUY" | "SELL"; status: string; mode: string; entry: number | null;
    stop_loss: number | null; take_profit: number | null; outcome_r: number | null }[];
  trades: { id: number; side: "BUY" | "SELL"; status: "open" | "closed"; entry_price: number; stop_loss: number;
    take_profit: number; exit_price: number | null; opened_at: number; closed_at: number | null; pnl: number | null }[];
};

export type DataSummary = {
  instrument: string;
  granularity: string;
  candles: number;
  first_time: string | null;
  last_time: string | null;
  sources: string[];
  parquet_file: string | null;
  parquet_size_mb: number | null;
  last_validation_status: ValidationStatus | null;
  last_validation_at: string | null;
};

export type Candle = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  bid_close: number | null;
  ask_close: number | null;
  spread: number | null;
  spread_pips: number | null;
  volume: number | null;
};

export type CandlesResponse = { instrument: string; granularity: string; count: number; candles: Candle[] };

export type ValidationStatus = "PASS" | "WARN" | "FAIL";

export type ValidationCheck = {
  name: string;
  severity: "error" | "warning" | "info";
  count: number;
  message: string;
  examples: string[];
  passed: boolean;
};

export type Gap = { start: string; end: string; missing_candles: number; category: string };

export type ValidationReport = {
  instrument: string;
  granularity: string;
  generated_at: string;
  status: ValidationStatus;
  rows: number;
  fields_available: { bid_ask?: boolean; volume?: boolean };
  cleaning?: { rows_raw: number; rows_removed: number; removed_by_reason: Record<string, number> };
  first_time: string | null;
  last_time: string | null;
  checks: ValidationCheck[];
  coverage: {
    expected_excluding_holidays: number;
    present: number;
    missing_excluding_holidays: number;
    holiday_missing: number;
    coverage_pct: number;
    min_coverage_pct: number;
  };
  coverage_by_year: { year: number; expected: number; present: number; missing: number; coverage_pct: number }[];
  gaps: { summary: Record<string, { gaps: number; missing_candles: number }>; largest: Gap[] };
  spread_pips: Partial<{ mean: number; median: number; p95: number; p99: number; min: number; max: number }>;
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(method: "GET" | "POST" | "DELETE", path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      cache: "no-store",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, `Backend unreachable at ${API_URL}`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

const q = (instrument: string) => `instrument=${encodeURIComponent(instrument)}`;

export const api = {
  health: () => request<Health>("GET", "/api/health"),
  config: () => request<AppConfig>("GET", "/api/config"),
  instruments: () => request<InstrumentInfo[]>("GET", "/api/instruments"),
  dataSummary: (instrument: string) => request<DataSummary>("GET", `/api/data/summary?${q(instrument)}`),
  candles: (instrument: string, limit = 20) =>
    request<CandlesResponse>("GET", `/api/candles?${q(instrument)}&limit=${limit}`),
  validation: (instrument: string) => request<ValidationReport>("GET", `/api/data/validation?${q(instrument)}`),
  model: () => request<ModelSummary>("GET", "/api/model"),
  chart: (instrument: string, limit = 400) => request<ChartData>("GET", `/api/chart?${q(instrument)}&limit=${limit}`),
  currentSignals: () => request<(SignalRow | { instrument: string; decision: null })[]>("GET", "/api/signals/current"),
  latestSignal: (instrument: string) => request<SignalRow | null>("GET", `/api/signals/latest?${q(instrument)}`),
  signals: (onlyTrades = true, limit = 50) =>
    request<SignalRow[]>("GET", `/api/signals?only_trades=${onlyTrades}&limit=${limit}`),
  takeSignal: (id: number, fill_price: number, units?: number) =>
    request<CoachTrade>("POST", `/api/signals/${id}/take`, { fill_price, units }),
  skipSignal: (id: number) => request<SignalRow>("POST", `/api/signals/${id}/skip`),
  openTrades: () => request<CoachTrade[]>("GET", "/api/trades?status=open"),
  closedTrades: () => request<CoachTrade[]>("GET", "/api/trades?status=closed&limit=200"),
  closeTrade: (id: number, exit_price: number, reason?: string) =>
    request<CoachTrade>("POST", `/api/trades/${id}/close`, { exit_price, reason }),
  cancelTrade: (id: number) => request<CoachTrade>("DELETE", `/api/trades/${id}`),
  coachStats: () => request<CoachStats>("GET", "/api/coach/stats"),
  liveStatus: () => request<LiveStatus>("GET", "/api/live/status"),
  backtest: (period: "test" | "walk_forward") => request<BacktestResult>("GET", `/api/backtest?period=${period}`),
  indicators: (instrument: string) => request<Indicators>("GET", `/api/indicators?${q(instrument)}`),
  riskPreview: (instrument: string) => request<RiskPreview>("GET", `/api/risk/preview?${q(instrument)}`),
  runValidation: (instrument: string) => request<ValidationReport>("POST", `/api/data/validation?${q(instrument)}`),
};
