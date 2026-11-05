"use client";

import clsx from "clsx";
import { ArrowDownRight, ArrowUpRight, BadgeCheck, ChevronDown, Crown, History, Info, Store } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Pick, american, kickoffLabel, pct } from "@/lib/api";
import { AddToParlay } from "./parlay";
import { Headshot, Meter, TeamLogo, TierBadge } from "./ui";
import { useTeams } from "./teams";

const tierColor = (t?: string | null) =>
  t === "segura" ? "var(--good)" : t === "arriesgada" ? "var(--serious)" : "var(--accent)";

export function EvChip({ ev }: { ev?: number | null }) {
  if (ev == null) return null;
  return (
    <span className={clsx("rounded-md px-1.5 py-0.5 text-[11px] font-semibold tnum",
      ev >= 0.02 ? "bg-good-soft text-good" : ev <= -0.03 ? "bg-s3 text-mute" : "bg-s3 text-ink2")}>
      VE {ev > 0 ? "+" : ""}{(ev * 100).toFixed(1)}%
    </span>
  );
}

/** Incertidumbre visible: rango donde cae el jugador 8 de cada 10 partidos vs. la línea. */
export function RangeBar({ q, line, hist, unit }: { q: number[]; line?: number | null; hist?: number[]; unit?: string }) {
  if (!q || q.length < 5) return null;
  const recent = (hist ?? []).slice(-8);
  const vals = [...q, ...(line != null ? [line] : []), ...recent];
  const lo = Math.max(0, Math.min(...vals));
  const hi = Math.max(...vals);
  const span = hi - lo || 1;
  const x = (v: number) => `${(((v - lo) / span) * 100).toFixed(2)}%`;
  const w = (a: number, b: number) => `${(((b - a) / span) * 100).toFixed(2)}%`;
  const fmt = (v: number) => (Math.abs(v) >= 10 ? Math.round(v) : Math.round(v * 10) / 10);
  return (
    <div className="mt-3" title="Barra clara: 8 de cada 10 partidos. Barra fuerte: la mitad de los partidos. Puntos: sus últimos juegos.">
      <div className="mb-1 flex items-baseline justify-between text-[11px] text-mute">
        <span>Rango probable</span>
        <span className="tnum">8 de cada 10: <b className="text-ink2">{fmt(q[0])}–{fmt(q[4])}</b> {unit}</span>
      </div>
      <div className="relative h-5">
        <div className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-accent-soft" style={{ left: x(q[0]), width: w(q[0], q[4]) }} />
        <div className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-accent/60" style={{ left: x(q[1]), width: w(q[1], q[3]) }} />
        <div className="absolute top-0 h-5 w-0.5 -translate-x-1/2 rounded bg-accent" style={{ left: x(q[2]) }} />
        {recent.map((v, i) => (
          <div key={i} className="absolute top-1/2 h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-ink2/50 ring-1 ring-s1" style={{ left: x(v) }} />
        ))}
        {line != null && (
          <div className="absolute -top-0.5 h-6 -translate-x-1/2 border-l-2 border-dashed border-ink" style={{ left: x(line) }} />
        )}
      </div>
      <div className="mt-0.5 flex justify-between text-[10px] text-mute tnum">
        <span>{fmt(lo)}</span>
        <span>mediana {fmt(q[2])}{line != null ? ` · línea ${line}` : ""}</span>
        <span>{fmt(hi)}</span>
      </div>
    </div>
  );
}

export function PickCard({ p, expanded = false }: { p: Pick; expanded?: boolean }) {
  const [open, setOpen] = useState(expanded);
  const teams = useTeams();
  const r = Array.isArray(p.reasons) ? { facts: p.reasons as string[] } : p.reasons ?? {};
  const isPlayer = p.type === "player";
  const href = isPlayer ? `/jugador/${p.player_id}` : `/partido/${p.game_id}`;
  const team = teams[(isPlayer ? p.team : p.side) ?? ""] ?? null;
  const facts = (r.facts ?? []).filter((f) => !f.startsWith("Mejor precio"));
  return (
    <div className="card overflow-hidden">
      <div className="flex items-start gap-3 px-4 pt-4">
        {isPlayer ? <Headshot src={p.headshot} name={p.name} size={42} /> : team ? <TeamLogo team={team} size={42} /> : (
          <div className="relative h-[42px] w-[42px] shrink-0">
            <TeamLogo team={teams[p.away ?? ""] ?? null} size={28} className="absolute left-0 top-0" />
            <TeamLogo team={teams[p.home ?? ""] ?? null} size={28} className="absolute bottom-0 right-0" />
          </div>
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <TierBadge tier={p.tier} />
            {p.elite && (
              <span className="inline-flex items-center gap-1 rounded-full bg-[var(--warning)]/15 px-2 py-0.5 text-[11px] font-bold text-warning"
                title="Cinna y el meta-modelo (entrenado con 186 mil apuestas reales) coinciden">
                <Crown size={12} /> {p.super_elite ? "Súper élite" : "Élite"}
              </span>
            )}
            {p.triple && (
              <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-semibold text-accent"
                title="El modelo, el mercado (8 casas) y los expertos van del mismo lado">
                <BadgeCheck size={12} /> Triple coincidencia
              </span>
            )}
            <span className="text-[11px] text-mute">{p.market_label}{p.lk ? ` · ${p.lk}` : ""}</span>
          </div>
          <Link href={href} className="mt-1 block text-[15px] font-semibold leading-snug hover:underline">{p.title}</Link>
          <div className="mt-0.5 text-xs text-mute">
            {isPlayer && `${p.position} · `}{p.game_label} · {kickoffLabel(p.kickoff)}
          </div>
        </div>
      </div>

      <div className="px-4 pt-3">
        <div className="flex items-end gap-4">
          <div className="shrink-0">
            <div className="text-[28px] font-semibold leading-none tracking-tight">{pct(p.prob)}</div>
            <div className="mt-1 text-[11px] text-mute">probabilidad</div>
          </div>
          <div className="grid flex-1 grid-cols-2 gap-x-3 gap-y-1 text-xs sm:grid-cols-3">
            <div><div className="text-mute">Confianza</div><div className="font-semibold tnum">{Math.round(p.confidence)}/100</div></div>
            <div><div className="text-mute">Momio justo</div><div className="font-semibold tnum">{american(p.fair_american)}</div></div>
            {p.prob_market != null ? (
              <div><div className="text-mute">Mercado</div><div className="font-semibold tnum">{pct(p.prob_market)}</div></div>
            ) : p.mu != null ? (
              <div><div className="text-mute">Proyección</div><div className="font-semibold tnum">{p.med ?? p.mu} {p.unit}</div></div>
            ) : null}
          </div>
        </div>
        <div className="mt-2.5"><Meter value={p.prob} color={tierColor(p.tier)} /></div>
        {isPlayer && p.q && (p.kind === "ou" || p.kind === "alt") && (
          <RangeBar q={p.q} line={p.line} hist={p.hist} unit={p.unit} />
        )}
        {p.class_hist && p.class_hist.n >= 100 && (
          <div className="mt-2 flex items-center gap-1.5 text-[11px] text-ink2" title="Backtest contra líneas reales de cierre de 8 casas">
            <History size={12} className="text-mute" />
            <span>
              Picks así acertaron <b className="text-ink tnum">{pct(p.class_hist.hit, 1)}</b>
              {p.class_hist.mkt != null && <> cuando el mercado les daba {pct(p.class_hist.mkt, 0)}</>} ({p.class_hist.n.toLocaleString("es-MX")} apuestas reales)
              {p.class_hist.roi != null && (
                <> · retorno <b className={p.class_hist.roi >= 0 ? "text-good tnum" : "text-ink tnum"}>
                  {p.class_hist.roi >= 0 ? "+" : ""}{(p.class_hist.roi * 100).toFixed(0)}%</b></>
              )}
            </span>
          </div>
        )}
        {p.book && p.odds != null && (
          <div className="mt-2.5 flex flex-wrap items-center gap-2 rounded-lg bg-s2 px-2.5 py-1.5 text-xs">
            <Store size={13} className="text-mute" />
            <span className="text-ink2">Mejor precio</span>
            <span className="font-semibold tnum">{p.book} {american(p.odds)}</span>
            {p.line != null && p.kind === "ou" && <span className="text-mute">línea {p.line}</span>}
            <span className="ml-auto flex items-center gap-2">
              <EvChip ev={p.ev} />
              {p.kelly != null && p.kelly > 0 && <span className="text-mute tnum" title="Kelly fraccionado (¼), tope 3% del bank">apuesta {(p.kelly * 100).toFixed(1)}%</span>}
            </span>
          </div>
        )}
      </div>

      {facts.length > 0 && (
        <ul className="mt-3 space-y-1 px-4 text-[13px] text-ink2">
          {facts.slice(0, open ? 8 : 2).map((f, i) => (
            <li key={i} className="flex gap-2"><Info size={13} className="mt-0.5 shrink-0 text-mute" />{f}</li>
          ))}
        </ul>
      )}

      {open && (r.up?.length || r.down?.length) ? (
        <div className="mt-3 grid gap-3 px-4 sm:grid-cols-2">
          {r.up && r.up.length > 0 && (
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-mute">Sube su proyección</div>
              {r.up.map((x, i) => (
                <div key={i} className="flex gap-1.5 py-0.5 text-[13px] text-ink2">
                  <ArrowUpRight size={14} className="mt-0.5 shrink-0 text-good" />{x.text}
                </div>
              ))}
            </div>
          )}
          {r.down && r.down.length > 0 && (
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-mute">Baja su proyección</div>
              {r.down.map((x, i) => (
                <div key={i} className="flex gap-1.5 py-0.5 text-[13px] text-ink2">
                  <ArrowDownRight size={14} className="mt-0.5 shrink-0 text-critical" />{x.text}
                </div>
              ))}
            </div>
          )}
        </div>
      ) : null}

      <div className="mt-3 flex items-center justify-between border-t border-line px-4 py-2.5">
        <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-1 text-xs text-ink2 hover:text-ink">
          <ChevronDown size={14} className={clsx("transition-transform", open && "rotate-180")} />
          {open ? "Menos detalle" : "Por qué"}
        </button>
        <AddToParlay pick={p} />
      </div>
    </div>
  );
}

/** Fila compacta para tablas de picks dentro de un partido o jugador. */
export function PickRow({ p }: { p: Pick }) {
  return (
    <div className="flex items-center gap-3 border-b border-line px-3 py-2.5 last:border-0">
      <TierBadge tier={p.tier} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{p.title}</div>
        <div className="truncate text-xs text-mute">{Array.isArray(p.reasons) ? p.reasons[0] : p.reasons?.facts?.[1] ?? p.reasons?.facts?.[0]}</div>
      </div>
      <div className="w-14 text-right text-sm font-semibold tnum">{pct(p.prob)}</div>
      <AddToParlay pick={p} compact />
    </div>
  );
}
