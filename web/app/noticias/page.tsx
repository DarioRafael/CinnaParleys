"use client";

import { Newspaper } from "@phosphor-icons/react";
import clsx from "clsx";
import { Zap } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { ago, pct, useApi } from "@/lib/api";
import { NewsItem, NewsList } from "@/components/news-list";
import { NewsVideos } from "@/components/jugadas";
import { Loading, SectionTitle, Segmented, PageHeader } from "@/components/ui";

type Inj = { player_id: string; name: string; team: string; position: string; status: string; p_play: number; source: string; comment: string; updated_at: string; role_snap: number };

export default function NewsPage() {
  const [filter, setFilter] = useState<"impacto" | "insiders" | "todas">("impacto");
  const q = filter === "impacto" ? "?only_impact=true&limit=80" : filter === "insiders" ? "?tier=2&limit=80" : "?limit=120";
  const { data, isLoading } = useApi<{ news: NewsItem[] }>(`/api/news${q}`);
  const { data: ch } = useApi<{ changes: { id: number; at: string; kind: string; message: string; game_id: string; player_id: string }[] }>("/api/changes?limit=40");
  const { data: inj } = useApi<{ injuries: Inj[] }>("/api/injuries?key_only=true");
  const key = (inj?.injuries ?? []).slice(0, 40);

  return (
    <div className="space-y-5">
      <PageHeader duo={Newspaper} tone="cielo" kicker="la jornada" title="Noticias y cambios">
        <p>ESPN, reporte oficial de lesiones, Rotowire, PFT, CBS, Yahoo e insiders de X (vía Bluesky). Las fuentes oficiales pesan más que los rumores.</p>
      </PageHeader>
      <NewsVideos />
      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <div className="space-y-3">
          <Segmented value={filter} onChange={setFilter} options={[
            { value: "impacto", label: "Con impacto" }, { value: "insiders", label: "Oficial + insiders" }, { value: "todas", label: "Todas" },
          ]} />
          {isLoading && !data ? <Loading /> : <NewsList items={data?.news ?? []} showEvents />}
        </div>
        <div className="space-y-6">
          <div className="card p-5">
            <SectionTitle>Lo que Cinna cambió</SectionTitle>
            {(ch?.changes ?? []).length === 0 && <div className="text-sm text-mute">Sin cambios importantes desde la última actualización.</div>}
            <div className="space-y-2.5">
              {(ch?.changes ?? []).map((c) => (
                <Link key={c.id} href={c.player_id ? `/jugador/${c.player_id}` : `/partido/${c.game_id}`} className="flex gap-2.5 text-sm hover:underline">
                  <Zap size={14} className="mt-0.5 shrink-0 text-warning" />
                  <div><div className="text-ink2">{c.message}</div><div className="text-[11px] text-mute">{ago(c.at)}</div></div>
                </Link>
              ))}
            </div>
          </div>
          <div className="card overflow-hidden">
            <div className="px-5 pt-5"><SectionTitle>Bajas y dudas clave</SectionTitle></div>
            {key.map((i) => (
              <Link key={i.player_id} href={`/jugador/${i.player_id}`} className="flex items-center gap-3 border-t border-line px-5 py-2.5 text-sm hover:bg-s2">
                <span className="w-9 text-xs text-mute">{i.team}</span>
                <span className="min-w-0 flex-1 truncate">{i.name} <span className="text-xs text-mute">{i.position}</span></span>
                <span className={clsx("text-xs font-semibold", i.p_play < 0.2 ? "text-critical" : "text-serious")}>{i.status}</span>
                <span className="w-16 text-right text-[11px] text-mute tnum">{pct(i.role_snap)} snaps</span>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
