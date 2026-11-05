"use client";

import { Duo } from "@/components/icons";
import { FilmSlate, Popcorn } from "@phosphor-icons/react";
import clsx from "clsx";
import { useMemo, useState } from "react";
import { useApi } from "@/lib/api";
import { Empty, Loading, PageHeader } from "@/components/ui";
import { Clip, TIPO, VideoCard, useVideo } from "@/components/videos";

type Resp = { videos: Clip[]; tipos: Record<string, number>; total: number };
type Filtro = "todos" | Clip["tipo"];

export default function VideosPage() {
  const { data, isLoading } = useApi<Resp>("/api/videos?limit=160");
  const [f, setF] = useState<Filtro>("todos");
  const [team, setTeam] = useState<string | null>(null);
  const { play } = useVideo();

  const teams = useMemo(() => {
    const m = new Map<string, { abbr: string; logo: string | null; n: number }>();
    for (const c of data?.videos ?? []) for (const t of c.logos ?? []) {
      const x = m.get(t.abbr) ?? { ...t, n: 0 };
      x.n += 1;
      m.set(t.abbr, x);
    }
    return [...m.values()].sort((a, b) => b.n - a.n);
  }, [data]);

  const list = (data?.videos ?? []).filter((c) => (f === "todos" || c.tipo === f) && (!team || c.equipos.includes(team)));
  const hero = list[0];

  return (
    <div className="space-y-6">
      <PageHeader duo={Popcorn} tone="lila" kicker="la jornada" title="Jugadas y videos">
        <p>Clips de ESPN de esta semana: previas para tus props, lesiones, quién juega de QB y jugadas. Tócalos y se ven aquí mismo.
          Son para ver y entender el contexto: <b>no cambian las probabilidades</b> (eso sale de los datos).</p>
      </PageHeader>

      {isLoading && !data ? <Loading label="Haciendo palomitas…" /> : !data?.videos.length ? (
        <Empty mood="think">Todavía no hay videos. ESPN los publica durante la semana; vuelve en un rato.</Empty>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            {(["todos", "props", "jugada", "noticia"] as Filtro[]).map((k) => {
              const n = k === "todos" ? data.total : data.tipos[k] ?? 0;
              if (k !== "todos" && !n) return null;
              return (
                <button key={k} onClick={() => setF(k)}
                  className={clsx("inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-sm font-bold transition-all duration-300",
                    f === k ? "scale-[1.03] border-transparent bg-brand-fill text-on-brand shadow-[0_8px_16px_-10px_var(--brand)]" : "border-line bg-s1 text-ink2 hover:text-ink")}>
                  <Duo icon={k === "todos" ? FilmSlate : TIPO[k].icon} tone={k === "todos" ? "lila" : TIPO[k].tone} size={18}
                    className={f === k ? "[--ti:currentColor]" : undefined} />
                  {k === "todos" ? "Todos" : TIPO[k].label}
                  <span className={clsx("rounded-full px-1.5 text-[11px] tnum", f === k ? "bg-white/25" : "bg-s2 text-mute")}>{n}</span>
                </button>
              );
            })}
          </div>

          {teams.length > 1 && (
            <div className="no-scrollbar -mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1">
              <button onClick={() => setTeam(null)}
                className={clsx("shrink-0 rounded-full border px-3 py-1 text-xs font-bold", !team ? "border-transparent bg-pink-soft text-ink" : "border-line bg-s1 text-mute")}>
                Todos los equipos
              </button>
              {teams.map((t) => (
                <button key={t.abbr} onClick={() => setTeam(team === t.abbr ? null : t.abbr)} title={`${t.n} videos`}
                  className={clsx("flex shrink-0 items-center gap-1 rounded-full border py-0.5 pl-1 pr-2.5 text-xs font-bold transition-colors",
                    team === t.abbr ? "border-transparent bg-pink-soft text-ink" : "border-line bg-s1 text-ink2 hover:text-ink")}>
                  {t.logo && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={t.logo} alt="" className="h-5 w-5 object-contain" />
                  )}
                  {t.abbr}
                </button>
              ))}
            </div>
          )}

          {hero ? (
            <div className="grid gap-6 lg:grid-cols-[1.35fr_1fr]">
              <button onClick={() => play(hero, list)} className="group card card-lift flex overflow-hidden text-left">
                <div className="relative aspect-video w-full lg:aspect-auto lg:min-h-[300px]">
                  {hero.poster && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={hero.poster} alt="" className="absolute inset-0 h-full w-full object-cover transition-transform duration-700 group-hover:scale-[1.04]" />
                  )}
                  <div className="absolute inset-0 bg-[linear-gradient(180deg,transparent_40%,rgba(20,10,6,0.8))]" />
                  <span className="play-ring absolute left-1/2 top-1/2 grid h-16 w-16 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-white/95 text-[#b5582b] shadow-xl transition-transform group-hover:scale-110">
                    <svg viewBox="0 0 24 24" className="ml-1 h-7 w-7 fill-current" aria-hidden="true"><path d="M8 5.5v13l11-6.5z" /></svg>
                  </span>
                  <div className="absolute inset-x-4 bottom-3">
                    <span className="font-hand text-lg font-semibold text-[#ffd9e3]">lo más nuevo</span>
                    <div className="font-display text-xl font-semibold leading-snug text-white md:text-2xl">{hero.titulo}</div>
                  </div>
                </div>
              </button>
              <div className="grid grid-cols-2 content-start gap-4">
                {list.slice(1, 5).map((c) => <VideoCard key={c.id} c={c} list={list} compact />)}
              </div>
            </div>
          ) : <Empty mood="think">No hay videos con ese filtro.</Empty>}

          {list.length > 5 && (
            <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
              {list.slice(5).map((c) => <VideoCard key={c.id} c={c} list={list} />)}
            </div>
          )}
          <p className="text-center text-xs text-mute">Videos públicos de ESPN (en inglés), sin cuenta ni costo. Se renuevan solos cada media hora.</p>
        </>
      )}
    </div>
  );
}
