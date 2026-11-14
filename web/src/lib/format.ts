// How numbers, sizes and times are shown.

export function bytes(value: number | null | undefined, digits = 1): string {
  if (value == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit++;
  }
  return `${size.toFixed(unit === 0 ? 0 : size < 10 ? digits : 0)} ${units[unit]}`;
}

export const percent = (value: number | null | undefined, digits = 0) =>
  value == null ? "—" : `${value.toFixed(digits)}%`;

export const number = (value: number | null | undefined, digits = 0) =>
  value == null ? "—" : value.toLocaleString(undefined, { maximumFractionDigits: digits });

export const ms = (value: number | null | undefined) =>
  value == null ? "—" : value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;

const toDate = (value: string | number | null | undefined) =>
  value == null ? null : typeof value === "number" ? new Date(value * 1000) : new Date(value);

const relative = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
export function ago(value: string | number | null | undefined): string {
  const date = toDate(value);
  if (!date) return "never";
  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  const abs = Math.abs(seconds);
  if (abs < 45) return seconds <= 0 ? "just now" : "in a few seconds";
  const [amount, unit]: [number, Intl.RelativeTimeFormatUnit] =
    abs < 3600 ? [seconds / 60, "minute"] : abs < 86400 ? [seconds / 3600, "hour"] : abs < 2592000 ? [seconds / 86400, "day"] : [seconds / 2592000, "month"];
  return relative.format(Math.round(amount), unit);
}

export function dateTime(value: string | number | null | undefined): string {
  const date = toDate(value);
  return date ? date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—";
}

export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m`;
  return `${Math.max(0, Math.floor(seconds))}s`;
}

export function elapsed(from: string | null, to?: string | null): string {
  if (!from) return "";
  const end = to ? new Date(to).getTime() : Date.now();
  return duration((end - new Date(from).getTime()) / 1000);
}

/** Two colours for an instance's monogram, always the same for the same name. */
export function monogram(name: string): { from: string; to: string; letters: string } {
  let hash = 0;
  for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  const hue = hash % 360;
  const letters = name.split(/[-_.]/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("") || name[0] || "?";
  return { from: `hsl(${hue} 52% 58%)`, to: `hsl(${(hue + 40) % 360} 58% 42%)`, letters };
}

export const STATUS_LABEL: Record<string, string> = {
  online: "Online",
  starting: "Starting",
  busy: "Working",
  paused: "Paused",
  switched_off: "Switched off",
  stopped: "Stopped",
  unknown: "Checking",
  queued: "Queued",
  running: "Running",
  success: "Done",
  failed: "Failed",
};

/** An amount in cents as money: 500, "usd" -> "$5.00". */
export function money(cents: number | null | undefined, currency: string | null | undefined = "usd"): string {
  if (cents == null) return "—";
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: (currency || "usd").toUpperCase() }).format(cents / 100);
  } catch {
    return `${(cents / 100).toFixed(2)} ${(currency || "").toUpperCase()}`;
  }
}

export function day(value: string | number | null | undefined): string {
  const parsed = toDate(value);
  return parsed ? parsed.toLocaleDateString(undefined, { dateStyle: "medium" }) : "—";
}
