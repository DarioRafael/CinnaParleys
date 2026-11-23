"use client";

import {
  ArrowsLeftRight, CaretDown, ChartBar, CheckCircle, Football, Scales, ShieldCheck, ShieldStar, SlidersHorizontal, Sparkle, Target, Timer,
  TrendDown, Trophy, WarningCircle, XCircle,
} from "@phosphor-icons/react";
import clsx from "clsx";
import { useState } from "react";
import { pct } from "@/lib/api";
import { IconTile, PIcon, Tone } from "./icons";
import { Headshot } from "./ui";

/* Piezas compartidas para mostrar parlays: armados por partido, súper parlay y combinaciones de varios partidos. */

export type Pata = {
  titulo: string; tipo?: string; prob: number; p_kalshi?: number | null; fuente_minimo?: string; proyeccion?: number | null;
  porque?: string; rol?: string | null; a_favor?: string[]; en_contra?: string[]; se_cae_si?: string[];
  semaforo?: "verde" | "amarillo" | "rojo"; dec?: number; precio_real?: boolean; super?: boolean; headshot?: string | null;
  name?: string; team?: string; grupo?: string; veredicto?: string; partido?: string; racha?: string | null;
  linea_casa?: number | null;
};
export type Parlay = {
  perfil: string; label: string; desc: string; prob_conjunta: number; si_fueran_independientes?: number;
  pago_estimado: number; pago_justo: number | null; precios_reales?: boolean; patas: Pata[];
};

export const PERFIL: Record<string, { icon: PIcon; tone: Tone }> = {
  muy_seguro: { icon: ShieldStar, tone: "menta" },
  seguro: { icon: ShieldCheck, tone: "menta" },
  partido: { icon: Football, tone: "canela" },
  menos: { icon: TrendDown, tone: "cielo" },
  guion: { icon: Trophy, tone: "miel" },
  balanceado: { icon: Scales, tone: "lila" },
  buen_pago: { icon: Sparkle, tone: "rosa" },
  medida: { icon: SlidersHorizontal, tone: "cielo" },
};
export const GRUPO: Record<string, { icon: PIcon; tone: Tone }> = {
  Ganador: { icon: Trophy, tone: "miel" },
  Ventaja: { icon: ArrowsLeftRight, tone: "lila" },
  Puntos: { icon: ChartBar, tone: "cielo" },
  Touchdowns: { icon: Football, tone: "canela" },
  "Goles de campo": { icon: Target, tone: "menta" },
  "1ª mitad": { icon: Timer, tone: "rosa" },
};
const SEM = { verde: "var(--good)", amarillo: "var(--warning)", rojo: "var(--critical)" } as const;

/** Qué tan seguido sale, en palabras. */
export function deCada10(p: number) {
  const n = Math.round(p * 10);
  return n <= 0 ? "menos de 1 de cada 10" : n >= 10 ? "casi siempre" : `~${n} de cada 10`;
}

function tipoPata(l: Pata): string {
  if (l.tipo === "partido") return l.grupo ?? "Partido";
  if (l.tipo === "td") return "Anota TD";
  if (l.tipo === "elite") return l.super ? "Súper élite" : "Élite";
  return "Escalón";
}

export function AvatarPata({ l, size = 36 }: { l: Pata; size?: number }) {
  if (l.tipo === "partido") {
    const g = GRUPO[l.grupo ?? ""] ?? GRUPO.Puntos;
    return <IconTile icon={g.icon} tone={g.tone} size={size} />;
  }
  return <Headshot src={l.headshot} name={l.name ?? l.titulo} size={size} />;
}

/** Una pata con su probabilidad y, al tocarla, por qué está y en qué caso se cae. */
export function PataFila({ l, abierta = false, mostrarPartido = false }: { l: Pata; abierta?: boolean; mostrarPartido?: boolean }) {
  const [open, setOpen] = useState(abierta);
  const favor = l.a_favor ?? [], contra = l.en_contra ?? [], cae = l.se_cae_si ?? [];
  const hayDetalle = !!(l.porque || favor.length || contra.length || cae.length || l.racha);
  return (
    <div className={clsx("rounded-xl border border-line bg-s1 transition-colors", open && "bg-s2/50")}>
      <button onClick={() => hayDetalle && setOpen((x) => !x)} className="flex w-full items-center gap-3 px-3 py-2.5 text-left">
        <div className="relative">
          <AvatarPata l={l} />
          {l.semaforo && l.semaforo !== "verde" && (
            <span className="absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full ring-2 ring-[var(--surface-1)]"
              style={{ background: SEM[l.semaforo] }} title={l.semaforo === "amarillo" ? "Con algún foco amarillo" : "Foco rojo"} />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-semibold leading-snug text-ink">{l.titulo}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-[11px] text-mute">
            <span>{tipoPata(l)}</span>
            {mostrarPartido && l.partido && <><span>·</span><span>{l.partido}</span></>}
            {l.veredicto === "casi azar" && <><span>·</span><span>promedio de la liga</span></>}
            {l.fuente_minimo === "estimado" && <><span>·</span><span>mínimo estimado</span></>}
            {l.fuente_minimo === "tu captura" && <><span>·</span><span>de tu captura</span></>}
            {l.p_kalshi != null && <><span>·</span><span>Kalshi {pct(l.p_kalshi)}</span></>}
          </div>
        </div>
        <div className="w-14 shrink-0 text-right">
          <div className={clsx("font-display text-lg font-semibold leading-none tnum", l.prob >= 0.75 ? "text-good" : "text-ink")}>{pct(l.prob)}</div>
          <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-s3">
            <div className="h-full rounded-full" style={{ width: `${l.prob * 100}%`, background: l.prob >= 0.75 ? "var(--good)" : "var(--accent)" }} />
          </div>
        </div>
        {hayDetalle && <CaretDown size={14} className={clsx("shrink-0 text-mute transition-transform", open && "rotate-180")} />}
      </button>
      {open && hayDetalle && (
        <div className="space-y-2 border-t border-line px-3 py-2.5 text-xs">
          {l.porque && <p className="text-ink2">{l.porque}{l.rol ? `. Es ${l.rol}.` : ""}</p>}
          {favor.length > 0 && (
            <ul className="space-y-1">
              {favor.map((t) => <li key={t} className="flex gap-1.5 text-ink2"><CheckCircle size={14} weight="fill" className="mt-px shrink-0 text-good" />{t}</li>)}
            </ul>
          )}
          {contra.length > 0 && (
            <ul className="space-y-1">
              {contra.map((t) => <li key={t} className="flex gap-1.5 text-ink2"><WarningCircle size={14} weight="fill" className="mt-px shrink-0 text-warning" />{t}</li>)}
            </ul>
          )}
          {cae.length > 0 && (
            <div className="flex gap-1.5 text-ink2"><XCircle size={14} weight="fill" className="mt-px shrink-0 text-critical" />
              <span><b className="text-ink">Se cae si</b> {cae.join("; ")}</span></div>
          )}
          {l.racha && <p className="text-[11px] text-mute">Racha (sólo contexto): lo pasó {l.racha}{l.proyeccion != null ? ` · proyección ${l.proyeccion}` : ""}</p>}
        </div>
      )}
    </div>
  );
}

/** Tarjeta de un parlay: qué tan seguido sale, cuánto paga y sus patas. */
export function ParlayCard({ pz, mostrarPartido = false, destacado = false }: { pz: Parlay; mostrarPartido?: boolean; destacado?: boolean }) {
  const P = PERFIL[pz.perfil] ?? PERFIL.balanceado;
  const grupos = [...new Set(pz.patas.map((l) => (l.tipo === "partido" ? l.grupo : "Jugadores")).filter(Boolean))] as string[];
  return (
    <div className={clsx("card flex flex-col overflow-hidden", destacado && "ring-2 ring-[var(--good)]/40")}>
      <div className="flex items-start gap-3 p-4 pb-3">
        <IconTile icon={P.icon} tone={P.tone} size={42} />
        <div className="min-w-0 flex-1">
          <div className="font-display text-[17px] font-semibold leading-tight text-ink">{pz.label}</div>
          <p className="mt-0.5 text-xs leading-snug text-mute">{pz.desc}</p>
        </div>
        <div className="shrink-0 text-right">
          <div className={clsx("font-display text-[28px] font-semibold leading-none tnum", pz.prob_conjunta >= 0.5 ? "text-good" : "text-ink")}>
            {pct(pz.prob_conjunta)}</div>
          <div className="mt-1 text-[11px] text-mute">sale {deCada10(pz.prob_conjunta)}</div>
        </div>
      </div>
      {grupos.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-4 pb-3">
          {grupos.map((g) => {
            const G = GRUPO[g];
            return (
              <span key={g} className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold", G ? `tone-${G.tone}` : "")}
                style={G ? { background: "var(--tb)", color: "var(--ti)" } : { background: "var(--surface-2)", color: "var(--text-secondary)" }}>
                {g}
              </span>
            );
          })}
          <span className="inline-flex items-center rounded-full bg-s2 px-2 py-0.5 text-[11px] font-semibold text-ink2">{pz.patas.length} patas</span>
        </div>
      )}
      <div className="flex-1 space-y-2 px-4 pb-4">
        {pz.patas.map((l) => <PataFila key={`${l.partido ?? ""}|${l.titulo}`} l={l} mostrarPartido={mostrarPartido} />)}
      </div>
      <div className="grid grid-cols-2 border-t border-line bg-s2/60 text-xs">
        <div className="px-4 py-2.5">
          <div className="text-mute">Paga {pz.precios_reales ? "" : "(estimado)"}</div>
          <div className="font-display text-base font-semibold text-ink tnum">~{pz.pago_estimado.toFixed(2)}x</div>
        </div>
        <div className="border-l border-line px-4 py-2.5">
          <div className="text-mute">Vale la pena si paga más de</div>
          <div className="font-display text-base font-semibold text-ink tnum">{pz.pago_justo ? `${pz.pago_justo.toFixed(2)}x` : "—"}</div>
        </div>
      </div>
    </div>
  );
}
