export function fmtPrice(value: number | null | undefined, digits = 5): string {
  return value == null ? "—" : value.toFixed(digits);
}

const TRADING_NAMES: Record<string, string> = { XAU_USD: "GOLD", XAG_USD: "SILVER" };

/** How the pair is named on screen and at the broker: EUR_USD -> EUR/USD, XAU_USD -> GOLD. */
export function pairName(instrument: string | null | undefined) {
  if (!instrument) return "";
  return TRADING_NAMES[instrument] ?? instrument.replace("_", "/");
}

/** Broker volume: 1 lot = 100,000 units of currency, or 100 oz of gold/silver. MT4/MT5 minimum is 0.01. */
export function fmtLots(units: number | null | undefined, metal: boolean) {
  if (units == null) return "—";
  const lots = units / (metal ? 100 : 100_000);
  return lots < 0.01 ? "0.01" : lots.toFixed(2);
}

/** Past this price the move has already happened - skip the trade (a quarter of the stop distance). */
export function maxEntry(side: string, entry: number | null, stop: number | null) {
  if (entry == null || stop == null) return null;
  const q = Math.abs(entry - stop) * 0.25;
  return side === "BUY" ? entry + q : entry - q;
}

export function fmtUsd(value: number | null | undefined): string {
  return value == null ? "—" : `$${value.toFixed(2)}`;
}

export function fmtInt(value: number | null | undefined): string {
  return value == null ? "—" : value.toLocaleString("en-US");
}

/** "2024-03-04 10:15 UTC" */
export function fmtUtc(iso: string | null | undefined, withSeconds = false): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const s = d.toISOString().replace("T", " ");
  return `${withSeconds ? s.slice(0, 19) : s.slice(0, 16)} UTC`;
}

/** A 15-minute candle shown by the time it CLOSED (the backend stores its open time): 09:30 -> 09:45. */
export function fmtCandle(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return fmtUtc(new Date(d.getTime() + 15 * 60_000).toISOString());
}

/**
 * Forex: Sunday 17:00 → Friday 17:00 New York time.
 * Metals: Sunday 18:00 → Friday 17:00, with a daily 17:00–18:00 break Mon–Thu.
 * (Mirrors backend app/core/market_hours.py.)
 */
export function isMarketOpen(assetClass: "forex" | "metal" = "forex", now: Date = new Date()): boolean {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    hour: "numeric",
    hourCycle: "h23",
  }).formatToParts(now);
  const weekday = parts.find((p) => p.type === "weekday")?.value;
  const hour = Number(parts.find((p) => p.type === "hour")?.value);
  if (weekday === "Sat") return false;
  if (weekday === "Fri" && hour >= 17) return false;
  const sundayOpen = assetClass === "metal" ? 18 : 17;
  if (weekday === "Sun" && hour < sundayOpen) return false;
  if (assetClass === "metal" && hour === 17 && ["Mon", "Tue", "Wed", "Thu"].includes(weekday ?? "")) return false;
  return true;
}
