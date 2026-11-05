"use client";

import { FootballHelmet } from "@phosphor-icons/react";
import clsx from "clsx";
import { useMemo, useState } from "react";
import { Team, useApi } from "@/lib/api";
import { Loading, TeamLogo, PageHeader } from "@/components/ui";

type R = { value: number | null; rank: number };
type TeamRow = Team & { ranks: Record<string, R> };

const COLS: { key: string; label: string; hint: string; fmt?: (v: number) => string }[] = [
  { key: "net", label: "Poder", hint: "Puntos netos por partido ajustados por rival", fmt: (v) => (v > 0 ? "+" : "") + v.toFixed(1) },
  { key: "off_pass", label: "Of. aérea", hint: "EPA por dropback ajustado" },
  { key: "off_rush", label: "Of. terrestre", hint: "EPA por carrera ajustado" },
  { key: "def_pass", label: "Def. aérea", hint: "EPA permitido por pase" },
  { key: "def_rush", label: "Def. terrestre", hint: "EPA permitido por carrera" },
  { key: "qb", label: "QB", hint: "EPA por jugada del titular", fmt: (v) => (v > 0 ? "+" : "") + v.toFixed(2) },
  { key: "pace", label: "Ritmo", hint: "Segundos por jugada (1 = más rápido)", fmt: (v) => v.toFixed(1) + "s" },
  { key: "proe", label: "Pasa +", hint: "Pases sobre lo esperado", fmt: (v) => (v > 0 ? "+" : "") + (v * 100).toFixed(1) + "%" },
];

export default function TeamsPage() {
  const { data, isLoading } = useApi<{ teams: TeamRow[] }>("/api/teams");
  const [sort, setSort] = useState("net");
  const rows = useMemo(() => [...(data?.teams ?? [])].sort((a, b) => (a.ranks[sort]?.rank ?? 99) - (b.ranks[sort]?.rank ?? 99)), [data, sort]);
  if (isLoading && !data) return <Loading />;
  return (
    <div className="space-y-5">
      <PageHeader duo={FootballHelmet} tone="canela" kicker="para entender" title="Ranking de poder">
        <p>Los 32 equipos según Cinna, ajustados por la calidad de sus rivales. El número pequeño es la posición en la liga (1 = mejor). Toca una columna para ordenar.</p>
      </PageHeader>
      <div className="card overflow-x-auto">
        <table className="w-full min-w-[900px] text-sm">
          <thead>
            <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-mute">
              <th className="px-4 py-3 font-medium">#</th>
              <th className="px-2 py-3 font-medium">Equipo</th>
              {COLS.map((c) => (
                <th key={c.key} title={c.hint} onClick={() => setSort(c.key)}
                  className={clsx("cursor-pointer px-3 py-3 text-right font-medium hover:text-ink", sort === c.key && "text-accent")}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((t, i) => (
              <tr key={t.abbr} className="border-b border-line last:border-0 hover:bg-s2">
                <td className="px-4 py-2.5 text-mute tnum">{i + 1}</td>
                <td className="px-2 py-2.5">
                  <div className="flex items-center gap-2.5"><TeamLogo team={t} size={26} /><div><div className="font-semibold">{t.nick}</div><div className="text-[11px] text-mute">{t.division}</div></div></div>
                </td>
                {COLS.map((c) => {
                  const r = t.ranks[c.key];
                  if (!r) return <td key={c.key} className="px-3 text-right text-mute">—</td>;
                  const good = r.rank <= 8, bad = r.rank >= 25;
                  return (
                    <td key={c.key} className="px-3 py-2.5 text-right tnum">
                      <div className="font-semibold">{r.value == null ? "—" : c.fmt ? c.fmt(r.value) : r.value.toFixed(3)}</div>
                      <div className={clsx("text-[11px]", good ? "text-good" : bad ? "text-critical" : "text-mute")}>#{r.rank}</div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
