"use client";

import clsx from "clsx";

/* Columnas del ranking de poder y la píldora de posición (se usan en Equipos y en la ficha de cada equipo). */

export const COLS: { key: string; label: string; hint: string; fmt?: (v: number) => string }[] = [
  { key: "net", label: "Poder", hint: "Puntos netos por partido ajustados por rival", fmt: (v) => (v > 0 ? "+" : "") + v.toFixed(1) },
  { key: "off_pass", label: "Of. aérea", hint: "EPA por dropback ajustado" },
  { key: "off_rush", label: "Of. terrestre", hint: "EPA por carrera ajustado" },
  { key: "def_pass", label: "Def. aérea", hint: "EPA permitido por pase" },
  { key: "def_rush", label: "Def. terrestre", hint: "EPA permitido por carrera" },
  { key: "qb", label: "QB", hint: "EPA por jugada del titular", fmt: (v) => (v > 0 ? "+" : "") + v.toFixed(2) },
  { key: "pace", label: "Ritmo", hint: "Segundos por jugada (1 = más rápido)", fmt: (v) => v.toFixed(1) + "s" },
  { key: "proe", label: "Pasa +", hint: "Pases sobre lo esperado", fmt: (v) => (v > 0 ? "+" : "") + (v * 100).toFixed(1) + "%" },
];

/** Posición en la liga como píldora de color: verde arriba, rojo abajo. */
export function RankPill({ rank }: { rank: number }) {
  const good = rank <= 8, bad = rank >= 25;
  return (
    <span className={clsx("inline-block min-w-[30px] rounded-md px-1 text-center text-[11px] font-semibold tnum",
      good ? "bg-good-soft text-good" : bad ? "bg-[var(--critical)]/10 text-critical" : "bg-s2 text-mute")}>#{rank}</span>
  );
}
