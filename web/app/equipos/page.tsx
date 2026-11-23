"use client";

import { CaretRight, FootballHelmet } from "@phosphor-icons/react";
import clsx from "clsx";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Team, kickoffLabel, pct, useApi } from "@/lib/api";
import { Loading, TeamLogo, PageHeader } from "@/components/ui";
import { COLS, RankPill } from "@/components/equipo-rank";

type R = { value: number | null; rank: number };
type Proximo = { game_id: string; kickoff: string; rival: string; local: boolean; status: string; p_gana?: number | null; rival_team?: Team };
type TeamRow = Team & { ranks: Record<string, R>; proximo?: Proximo | null };

export default function TeamsPage() {
  const { data, isLoading } = useApi<{ teams: TeamRow[] }>("/api/teams");
  const [sort, setSort] = useState("net");
  const router = useRouter();
  const rows = useMemo(() => [...(data?.teams ?? [])].sort((a, b) => (a.ranks[sort]?.rank ?? 99) - (b.ranks[sort]?.rank ?? 99)), [data, sort]);
  if (isLoading && !data) return <Loading />;
  return (
    <div className="space-y-5">
      <PageHeader duo={FootballHelmet} tone="canela" kicker="para entender" title="Equipos">
        <p>Los 32 equipos según Cinna, ajustados por la calidad de sus rivales (#1 = el mejor). Toca un equipo para ver su próximo partido,
          sus resultados, sus jugadores y sus picks. Toca una columna para ordenar.</p>
      </PageHeader>
      <div className="card overflow-x-auto">
        <table className="w-full min-w-[1040px] text-sm">
          <thead>
            <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-mute">
              <th className="px-4 py-3 font-medium">#</th>
              <th className="px-2 py-3 font-medium">Equipo</th>
              <th className="px-3 py-3 font-medium">Próximo partido</th>
              {COLS.map((c) => (
                <th key={c.key} title={c.hint} onClick={() => setSort(c.key)}
                  className={clsx("cursor-pointer px-3 py-3 text-right font-medium hover:text-ink", sort === c.key && "text-accent")}>{c.label}</th>
              ))}
              <th className="w-8" />
            </tr>
          </thead>
          <tbody>
            {rows.map((t, i) => {
              const n = t.proximo;
              return (
                <tr key={t.abbr} onClick={() => router.push(`/equipos/${t.abbr}`)}
                  className="group cursor-pointer border-b border-line last:border-0 hover:bg-s2">
                  <td className="px-4 py-2.5 text-mute tnum">{i + 1}</td>
                  <td className="px-2 py-2.5">
                    <div className="flex items-center gap-2.5"><TeamLogo team={t} size={28} />
                      <div><div className="font-semibold text-ink group-hover:text-accent">{t.nick}</div><div className="text-[11px] text-mute">{t.division}</div></div></div>
                  </td>
                  <td className="px-3 py-2.5">
                    {n ? (
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] font-semibold text-mute">{n.local ? "vs" : "@"}</span>
                        <TeamLogo team={n.rival_team ?? { abbr: n.rival }} size={22} />
                        <div className="leading-tight">
                          <div className="text-xs font-semibold text-ink">{n.rival_team?.nick ?? n.rival}</div>
                          <div className="text-[11px] text-mute">{n.status === "in" ? "en vivo" : kickoffLabel(n.kickoff)}
                            {n.p_gana != null && <> · gana <b className={clsx("tnum", n.p_gana >= 0.5 ? "text-good" : "text-ink2")}>{pct(n.p_gana)}</b></>}</div>
                        </div>
                      </div>
                    ) : <span className="text-xs text-mute">—</span>}
                  </td>
                  {COLS.map((c) => {
                    const r = t.ranks[c.key];
                    if (!r) return <td key={c.key} className="px-3 text-right text-mute">—</td>;
                    return (
                      <td key={c.key} className="px-3 py-2.5 text-right tnum">
                        <div className="font-semibold">{r.value == null ? "—" : c.fmt ? c.fmt(r.value) : r.value.toFixed(3)}</div>
                        <RankPill rank={r.rank} />
                      </td>
                    );
                  })}
                  <td className="pr-3 text-mute"><CaretRight size={14} className="transition-transform group-hover:translate-x-0.5" /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
