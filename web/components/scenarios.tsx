"use client";

import clsx from "clsx";
import { ArrowRight, ChevronDown, Flame, Shield, Swords, Timer } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { pct } from "@/lib/api";
import { Headshot, SectionTitle } from "./ui";

export type EscBlock = {
  nombre: string; que_pasa: string; prob: number; marcador_tipico: string;
  picks_que_suben: { pick: string; normal: number; en_este_escenario: number }[];
  jugadores_clave: { jugador: string; stat: string; normal: number; en_este_escenario: number | null }[];
};
export type Romper = {
  jugador: string; player_id: string; equipo: string; posicion: string; hazana: string; prob: number;
  mercado?: number | null; momio?: string | null; valor?: boolean; mejor_escenario?: string | null;
  prob_en_ese_escenario?: number | null; proyeccion?: number | null; headshot?: string | null; partido?: string; game_id?: string;
};
export type Escenarios = {
  favorito: string; debil: string; escenarios: EscBlock[]; ritmo: EscBlock[];
  medio_tiempo: Record<string, number>; romper: Romper[];
};
type Tend = { equipo: number; liga: number; temporada: number };
export type Esquema = {
  nota: string; equipos: Record<string, { defensa?: Record<string, Tend>; ofensiva?: Record<string, Tend> }>;
  matchups: { jugador: string; equipo: string; posicion: string; notas: string[] }[];
};

// color por escenario de resultado: favorito fuerte → débil
const SC_COLORS = ["var(--accent)", "color-mix(in oklab, var(--accent) 55%, var(--surface-3))", "color-mix(in oklab, var(--text-secondary) 45%, var(--surface-3))", "var(--warning)"];

function Delta({ a, b, fmt = (x: number) => pct(x) }: { a: number; b: number | null; fmt?: (x: number) => string }) {
  if (b == null) return null;
  return (
    <span className="inline-flex items-center gap-1 tnum">
      <span className="text-mute">{fmt(a)}</span>
      <ArrowRight size={11} className="text-mute" />
      <b className={clsx(b > a ? "text-good" : b < a ? "text-critical" : "text-ink")}>{fmt(b)}</b>
    </span>
  );
}

function ScenarioCard({ s, color }: { s: EscBlock; color?: string }) {
  const notable = s.jugadores_clave.filter((j) => j.en_este_escenario != null && Math.abs((j.en_este_escenario ?? 0) - j.normal) >= Math.max(0.08 * Math.abs(j.normal || 1), 0.4));
  return (
    <div className="card p-4">
      <div className="flex items-start gap-3">
        {color && <span className="mt-1 h-3 w-3 shrink-0 rounded-sm" style={{ background: color }} />}
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <div className="font-semibold">{s.nombre}</div>
            <div className="text-lg font-bold tnum">{pct(s.prob)}</div>
          </div>
          <div className="text-xs text-mute">{s.que_pasa} · marcador típico <span className="text-ink2">{s.marcador_tipico}</span></div>
        </div>
      </div>
      {s.picks_que_suben.length > 0 && (
        <div className="mt-3">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-mute">Picks que suben si pasa esto</div>
          <ul className="mt-1 space-y-1 text-[13px]">
            {s.picks_que_suben.map((x) => (
              <li key={x.pick} className="flex flex-wrap items-baseline justify-between gap-x-3">
                <span className="text-ink2">{x.pick}</span>
                <Delta a={x.normal} b={x.en_este_escenario} />
              </li>
            ))}
          </ul>
        </div>
      )}
      {notable.length > 0 && (
        <div className="mt-3">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-mute">Jugadores (mediana)</div>
          <ul className="mt-1 space-y-0.5 text-xs">
            {notable.slice(0, 6).map((j) => (
              <li key={j.jugador + j.stat} className="flex justify-between gap-3">
                <span className="text-ink2">{j.jugador} · {j.stat}</span>
                <Delta a={j.normal} b={j.en_este_escenario} fmt={(x) => (Math.abs(x) >= 10 ? x.toFixed(0) : x.toFixed(1))} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function RomperList({ items, showGame = false }: { items: Romper[]; showGame?: boolean }) {
  if (!items.length) return null;
  return (
    <div className="card divide-y divide-[var(--border)]">
      {items.map((b, i) => (
        <div key={b.player_id + b.hazana + i} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
          <Headshot src={b.headshot} name={b.jugador} size={34} />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold">
              <Link href={`/jugador/${b.player_id}`} className="hover:underline">{b.jugador}</Link>
              <span className="ml-1.5 text-xs font-normal text-mute">{b.posicion} · {b.equipo}{showGame && b.partido ? ` · ${b.partido}` : ""}</span>
            </div>
            <div className="text-xs text-ink2">
              {b.hazana}
              {b.mejor_escenario && b.prob_en_ese_escenario != null && (
                <span className="text-mute"> · si «{b.mejor_escenario}» sube a <b className="text-ink2 tnum">{pct(b.prob_en_ese_escenario)}</b></span>
              )}
            </div>
          </div>
          {b.mercado != null && (
            <div className="text-right text-[11px] text-mute">
              mercado {pct(b.mercado)}{b.momio ? <div className="tnum">{b.momio}</div> : null}
            </div>
          )}
          {b.valor && <span className="rounded-md bg-good-soft px-1.5 py-0.5 text-[11px] font-semibold text-good">con valor</span>}
          <div className="w-14 text-right text-lg font-bold tnum">{pct(b.prob)}</div>
        </div>
      ))}
    </div>
  );
}

const DEF_LABEL: Record<string, string> = { hombre: "Cobertura de hombre", blitz: "Blitz", presion: "Presión al QB", caja_cargada: "Caja cargada (8+) vs carrera", caja_ligera: "Caja ligera (≤6) vs carrera" };
const OFF_LABEL: Record<string, string> = { play_action: "Play action", motion: "Motion", rpo: "RPO", pantallas: "Pantallas", fuera_del_pocket: "QB fuera del pocket" };

function SchemeBlock({ sq, home, away }: { sq: Esquema; home: string; away: string }) {
  const [open, setOpen] = useState(false);
  const row = (label: string, a?: Tend, b?: Tend) => (
    <tr key={label} className="border-b border-line last:border-0">
      <td className="py-1.5 pr-3 text-ink2">{label}</td>
      {[a, b].map((t, i) => (
        <td key={i} className="px-2 py-1.5 text-right tnum">
          {t ? <span className={clsx(t.equipo > t.liga * 1.15 ? "text-ink font-semibold" : t.equipo < t.liga * 0.85 ? "text-mute" : "text-ink2")}>{pct(t.equipo, 0)}</span> : "—"}
        </td>
      ))}
      <td className="py-1.5 pl-2 text-right text-mute tnum">{pct((a ?? b)?.liga, 0)}</td>
    </tr>
  );
  const ea = sq.equipos[away] ?? {}, eh = sq.equipos[home] ?? {};
  return (
    <div className="card">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 px-5 py-3.5 text-left text-sm font-semibold">
        <Swords size={15} className="text-mute" /> Esquema: cómo defiende y ataca cada equipo
        <ChevronDown size={15} className={clsx("ml-auto text-mute transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="grid gap-5 border-t border-line p-5 lg:grid-cols-2">
          <div>
            <table className="w-full text-sm">
              <thead><tr className="text-left text-[11px] uppercase tracking-wider text-mute">
                <th className="pb-1.5 font-medium">Defensa</th><th className="pb-1.5 text-right font-medium">{away}</th>
                <th className="pb-1.5 text-right font-medium">{home}</th><th className="pb-1.5 text-right font-medium">Liga</th></tr></thead>
              <tbody>{Object.keys(DEF_LABEL).map((k) => row(DEF_LABEL[k], ea.defensa?.[k], eh.defensa?.[k]))}</tbody>
            </table>
            <table className="mt-4 w-full text-sm">
              <thead><tr className="text-left text-[11px] uppercase tracking-wider text-mute">
                <th className="pb-1.5 font-medium">Ofensiva</th><th className="pb-1.5 text-right font-medium">{away}</th>
                <th className="pb-1.5 text-right font-medium">{home}</th><th className="pb-1.5 text-right font-medium">Liga</th></tr></thead>
              <tbody>{Object.keys(OFF_LABEL).map((k) => row(OFF_LABEL[k], ea.ofensiva?.[k], eh.ofensiva?.[k]))}</tbody>
            </table>
          </div>
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wider text-mute">Matchups a vigilar</div>
            <ul className="mt-2 space-y-2 text-[13px]">
              {sq.matchups.length ? sq.matchups.map((mm) => (
                <li key={mm.jugador}><b className="text-ink">{mm.jugador}</b> <span className="text-xs text-mute">{mm.posicion} · {mm.equipo}</span>
                  {mm.notas.map((n) => <div key={n} className="text-ink2">{n}</div>)}</li>
              )) : <li className="text-mute">Sin matchups llamativos.</li>}
            </ul>
            <p className="mt-3 text-[11px] text-mute">{sq.nota} Coberturas y presión: temporada pasada (la liga publica las de este año con retraso); blitz, caja y play action: esta temporada.</p>
          </div>
        </div>
      )}
    </div>
  );
}

export function ScenariosPanel({ esc, sq, home, away }: { esc: Escenarios; sq?: Esquema | null; home: string; away: string }) {
  const mt = esc.medio_tiempo;
  const fav = esc.favorito, dog = esc.debil;
  return (
    <div className="space-y-6">
      <section>
        <SectionTitle right={<span className="text-xs text-mute">20,000 partidos simulados con todos los jugadores</span>}>Cómo se puede dar el partido</SectionTitle>
        <div className="card p-4">
          <div className="flex h-7 w-full gap-[2px] overflow-hidden rounded-md">
            {esc.escenarios.map((s, i) => (
              <div key={s.nombre} title={`${s.nombre}: ${pct(s.prob)}`} className="flex h-full items-center justify-center text-[11px] font-semibold"
                style={{ width: `${s.prob * 100}%`, background: SC_COLORS[i], color: i === 0 ? "white" : "var(--text-primary)" }}>
                {s.prob >= 0.1 ? pct(s.prob, 0) : ""}
              </div>
            ))}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink2">
            {esc.escenarios.map((s, i) => (
              <span key={s.nombre} className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: SC_COLORS[i] }} />{s.nombre} <b className="tnum text-ink">{pct(s.prob)}</b></span>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 border-t border-line pt-3 text-xs text-ink2">
            <span className="inline-flex items-center gap-1.5"><Timer size={13} className="text-mute" /> Al medio tiempo: {fav} arriba <b className="tnum text-ink">{pct(mt[`${fav}_arriba`])}</b> · {dog} arriba <b className="tnum text-ink">{pct(mt[`${dog}_arriba`])}</b> · empate {pct(mt.empatados)}</span>
            <span>Si {fav} va abajo al medio, remonta {pct(mt[`remontada_${fav}`])} · si {dog} va abajo, remonta {pct(mt[`remontada_${dog}`])}</span>
          </div>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          {esc.escenarios.map((s, i) => <ScenarioCard key={s.nombre} s={s} color={SC_COLORS[i]} />)}
        </div>
      </section>
      <section>
        <SectionTitle>Ritmo del partido</SectionTitle>
        <div className="grid gap-4 lg:grid-cols-2">{esc.ritmo.map((s) => <ScenarioCard key={s.nombre} s={s} />)}</div>
      </section>
      {esc.romper.length > 0 && (
        <section>
          <SectionTitle right={<span className="inline-flex items-center gap-1 text-xs text-mute"><Flame size={13} /> probabilidad de juego grande</span>}>La pueden romper</SectionTitle>
          <RomperList items={esc.romper} />
        </section>
      )}
      {sq && <SchemeBlock sq={sq} home={home} away={away} />}
      <p className="flex items-start gap-2 text-xs text-mute"><Shield size={13} className="mt-0.5 shrink-0" />
        Cada escenario sale de las mismas 20,000 simulaciones: si el partido va por ahí, así cambian los jugadores. Las probabilidades de los
        picks usan la calibración real de Cinna; el escenario sólo mueve cuánto suben o bajan.</p>
    </div>
  );
}
