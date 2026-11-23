"use client";

import { ArrowUpRight, CaretDown, Check, CirclesThreePlus, Info, ShieldStar, X } from "@phosphor-icons/react";
import clsx from "clsx";
import Link from "next/link";
import { useState } from "react";
import { GameCard, kickoffLabel, pct, useApi } from "@/lib/api";
import { IconTile } from "./icons";
import { Parlay, ParlayCard } from "./patas";
import { Loading, TeamLogo } from "./ui";

/** Tira con los partidos que faltan de la jornada: se pueden elegir (uno o varios) o abrir. */
export function TiraPartidos({ juegos, sel, onToggle, conteo }: {
  juegos: GameCard[]; sel: string[]; onToggle: (id: string) => void; conteo?: Record<string, number>;
}) {
  if (!juegos.length) return null;
  return (
    <div className="-mx-1 flex snap-x gap-3 overflow-x-auto px-1 pb-2">
      {juegos.map((g) => {
        const on = sel.includes(g.game_id);
        const ph = g.pred?.p_home;
        const fav = ph == null ? null : ph >= 0.5 ? g.home : g.away;
        const pf = ph == null ? null : Math.max(ph, 1 - ph);
        return (
          <div key={g.game_id} className={clsx("card relative w-[214px] shrink-0 snap-start p-3 transition-shadow",
            on ? "ring-2 ring-[var(--accent)]" : "hover:shadow-md")}>
            <button onClick={() => onToggle(g.game_id)} className="block w-full text-left" aria-pressed={on}
              title={on ? "Quitar de la selección" : "Elegir este partido"}>
              <div className="flex items-center gap-2">
                <TeamLogo team={g.away} size={28} />
                <span className="text-[11px] font-semibold text-mute">@</span>
                <TeamLogo team={g.home} size={28} />
                <span className={clsx("ml-auto grid h-5 w-5 place-items-center rounded-md border",
                  on ? "border-[var(--accent)] bg-accent text-on-accent" : "border-line-strong text-transparent")}>
                  <Check size={12} weight="bold" />
                </span>
              </div>
              <div className="mt-2 truncate text-sm font-semibold text-ink">{g.away.nick} @ {g.home.nick}</div>
              <div className="text-[11px] text-mute">{kickoffLabel(g.kickoff)}</div>
              <div className="mt-2 flex items-center justify-between text-[11px]">
                <span className="text-ink2">{fav ? <>Cinna: <b className="text-ink">{fav.abbr} {pct(pf)}</b></> : "Sin simulación"}</span>
                {conteo && <span className="rounded-full bg-s2 px-1.5 font-semibold text-ink2 tnum">{conteo[g.game_id] ?? 0} picks</span>}
              </div>
            </button>
            <Link href={`/partido/${g.game_id}`} title="Abrir el partido"
              className="absolute right-9 top-3 grid h-5 w-5 place-items-center rounded-md text-mute hover:bg-s2 hover:text-accent">
              <ArrowUpRight size={14} weight="bold" />
            </Link>
          </div>
        );
      })}
    </div>
  );
}

type Comb = { partidos?: string[]; opciones?: Parlay[]; avisos?: string[]; nota?: string; error?: string };

/** «Súper pick» con los partidos elegidos: lo más probable para cada nivel de pago. */
export function CombinarPartidos({ sel, juegos, onClear }: { sel: string[]; juegos: GameCard[]; onClear: () => void }) {
  const { data, isLoading } = useApi<Comb>(sel.length ? `/api/combinar?games=${sel.join(",")}` : null);
  const [todas, setTodas] = useState(false);
  const ops = data?.opciones ?? [];
  const nombres = sel.map((id) => juegos.find((g) => g.game_id === id)).filter(Boolean) as GameCard[];
  return (
    <section className="card space-y-4 p-4 sm:p-5">
      <div className="flex flex-wrap items-center gap-3">
        <IconTile icon={nombres.length > 1 ? CirclesThreePlus : ShieldStar} tone="menta" size={42} />
        <div className="min-w-0 flex-1">
          <div className="font-display text-lg font-semibold text-ink">
            {nombres.length > 1 ? `Súper pick con ${nombres.length} partidos` : "Súper pick de este partido"}
          </div>
          <div className="flex flex-wrap gap-1.5 pt-1">
            {nombres.map((g) => (
              <span key={g.game_id} className="inline-flex items-center gap-1 rounded-full bg-s2 py-0.5 pl-1 pr-2 text-[11px] font-semibold text-ink2">
                <TeamLogo team={g.away} size={16} /><TeamLogo team={g.home} size={16} />{g.away.abbr} @ {g.home.abbr}
              </span>
            ))}
          </div>
        </div>
        {nombres.length === 1 && (
          <Link href={`/partido/${nombres[0].game_id}`}
            className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-on-accent">
            Abrir el partido <ArrowUpRight size={14} weight="bold" />
          </Link>
        )}
        <button onClick={onClear} className="inline-flex items-center gap-1 rounded-xl border border-line px-3 py-2 text-sm font-semibold text-ink2 hover:text-ink">
          <X size={14} weight="bold" /> Limpiar
        </button>
      </div>
      {isLoading && !data ? <Loading label="Buscando la combinación más firme…" /> : data?.error ? (
        <p className="text-sm text-mute">{data.error}</p>
      ) : (
        <>
          <div className="grid grid-cols-1 items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
            {(todas ? ops : ops.slice(0, 3)).map((o, i) => <ParlayCard key={o.perfil} pz={o} mostrarPartido={sel.length > 1} destacado={i === 0} />)}
          </div>
          {ops.length > 3 && (
            <button onClick={() => setTodas((x) => !x)}
              className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold text-ink2 hover:bg-s2 hover:text-ink">
              <CaretDown size={14} className={clsx("transition-transform", todas && "rotate-180")} />
              {todas ? "Ver menos" : `Ver las ${ops.length} opciones`}
            </button>
          )}
          {(data?.avisos ?? []).map((a) => <p key={a} className="text-xs text-warning">{a}</p>)}
          {data?.nota && <p className="flex gap-2 text-[11px] text-mute"><Info size={14} className="mt-px shrink-0" />{data.nota}</p>}
        </>
      )}
    </section>
  );
}
