"use client";

import useSWR, { SWRConfiguration } from "swr";

export const fetcher = async (url: string) => {
  const r = await fetch(url);
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || r.statusText);
  }
  return r.json();
};

export async function post<T = unknown>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export function useApi<T = any>(url: string | null, cfg?: SWRConfiguration) {
  return useSWR<T>(url, fetcher, { revalidateOnFocus: true, keepPreviousData: true, ...cfg });
}

/* ---------------------------------------------------------------- tipos */
export type Team = {
  abbr: string; name: string; nick: string; logo: string | null; color: string; color2?: string;
  score?: number | null; record?: string | null; conf?: string; division?: string;
};

export type GamePred = {
  p_home: number; p_away: number; p_tie: number; p_ot: number; home_mu: number; away_mu: number;
  total_mu: number; margin_mu: number; p_home_cover?: number; p_over?: number;
  model_only?: { p_home: number; p_away: number; home_mu: number; away_mu: number; p_ot: number };
  starters?: { home?: Starter; away?: Starter };
  top_scores?: { home: number; away: number; p: number }[];
  factors?: { team: string | null; text: string; weight: number }[];
};
export type Starter = { player_id: string; name: string; p_play: number; reason?: string; changed?: boolean; backup_name?: string };

export type Market = {
  book?: string; details?: string; spread_home?: number | null; spread_home_open?: number | null;
  total?: number | null; total_open?: number | null; ml_home?: number | null; ml_away?: number | null;
  over_odds?: number | null; under_odds?: number | null;
};

export type Weather = { temp_f?: number; wind_mph?: number; gust_mph?: number; precip_prob?: number; label?: string } | null;

export type GameCard = {
  game_id: string; season: number; week: number; kickoff: string; status: "pre" | "in" | "post";
  status_detail: string; venue: string; city: string; indoor: boolean; broadcast?: string;
  period?: number; clock?: string; home: Team; away: Team; market: Market; weather: Weather;
  fpi?: { home: number; away: number } | null; injuries: { home: number; away: number };
  top_pick?: Pick | null; pred?: GamePred;
};

export type Reason = { feature: string; text: string; effect: number };
export type Pick = {
  pick_id: string; game_id: string; player_id?: string | null; type: "player" | "game"; market: string;
  kind?: string; market_label: string; side: string; line?: number | null; open?: number | null;
  prob: number; prob_model?: number | null; prob_market?: number | null; ev?: number | null; book?: string | null;
  dec?: number | null; kelly?: number | null; agree?: boolean | null; experts_agree?: boolean | null; triple?: boolean;
  elite?: boolean; super_elite?: boolean; prob_raw?: number; class_hist?: { n: number; hit: number; roi?: number | null; mkt?: number | null } | null;
  edge?: number | null; tier: "segura" | "valor" | "arriesgada" | null;
  confidence: number; title: string; lk?: string; fair_american?: number; fair_decimal?: number;
  mu?: number; med?: number; mu_model?: number; market_line?: number | null; q?: number[]; unit?: string; hist?: number[];
  name?: string; team?: string; opp?: string; position?: string; headshot?: string | null; kickoff: string;
  game_label: string; availability?: { p_play: number; status: string };
  reasons?: { facts?: string[]; up?: Reason[]; down?: Reason[] } | string[];
  implied?: number | null; odds?: number | null; home?: string; away?: string;
};

/* ---------------------------------------------------------------- formato */
const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;

export function kickoffLabel(iso: string, withDay = true) {
  const d = new Date(iso);
  const day = d.toLocaleDateString("es-MX", { weekday: "short", day: "numeric", month: "short", timeZone: TZ });
  const time = d.toLocaleTimeString("es-MX", { hour: "numeric", minute: "2-digit", timeZone: TZ });
  return withDay ? `${day} · ${time}` : time;
}

export function dayKey(iso: string) {
  return new Date(iso).toLocaleDateString("es-MX", { weekday: "long", day: "numeric", month: "long", timeZone: TZ });
}

export function ago(iso?: string | null) {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "hace segundos";
  if (s < 3600) return `hace ${Math.round(s / 60)} min`;
  if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
  return `hace ${Math.round(s / 86400)} d`;
}

export const pct = (p?: number | null, d = 0) => (p == null || isNaN(p) ? "—" : `${(p * 100).toFixed(d)}%`);
export const num = (x?: number | null, d = 1) => (x == null || isNaN(x) ? "—" : x.toFixed(d));
export const american = (o?: number | null) => (o == null ? "—" : o > 0 ? `+${Math.round(o)}` : `${Math.round(o)}`);
export const signed = (x?: number | null, d = 1) => (x == null ? "—" : `${x > 0 ? "+" : ""}${x.toFixed(d)}`);

export function spreadLabel(team: string, spreadHome: number | null | undefined, isHome: boolean) {
  if (spreadHome == null) return "";
  const s = isHome ? -spreadHome : spreadHome;
  return `${team} ${s > 0 ? "+" : ""}${s}`;
}

export const TIER: Record<string, { label: string; short: string; cls: string; dot: string }> = {
  segura: { label: "Segura", short: "Segura", cls: "text-good bg-good-soft", dot: "var(--good)" },
  valor: { label: "Valor", short: "Valor", cls: "text-accent bg-accent-soft", dot: "var(--accent)" },
  arriesgada: { label: "Arriesgada", short: "Riesgo", cls: "text-serious bg-serious-soft", dot: "var(--serious)" },
};

export const POS_ORDER = ["QB", "RB", "WR", "TE"];
