"use client";

import { Duo } from "./icons";
import { Football, Megaphone, Popcorn } from "@phosphor-icons/react";
import clsx from "clsx";
import { useApi } from "@/lib/api";
import { Empty, Loading, SectionTitle } from "./ui";
import { Clip, VideoCard, VideoRail } from "./videos";

type Jugada = { texto: string; cuarto: number | null; reloj: string | null; equipo: string | null; local: number | null; visita: number | null; tipo: string };
type Resp = { status: string; jugadas: Jugada[]; videos: Clip[] };

/** Pestaña "Jugadas" del partido: anotaciones en orden (en vivo se renueva) y videos del partido y sus equipos. */
export function JugadasPanel({ gameId, home, away }: { gameId: string; home: string; away: string }) {
  const { data, isLoading } = useApi<Resp>(`/api/partido/${gameId}/jugadas`, { refreshInterval: (d) => (d?.status === "in" ? 60000 : 0) });
  if (isLoading && !data) return <Loading label="Buscando las jugadas…" />;
  if (!data) return null;
  const { jugadas, videos } = data;
  return (
    <div className="space-y-6">
      {jugadas.length > 0 && (
        <section className="card p-5">
          <SectionTitle icon={Football} tone="canela">Así se fueron los puntos</SectionTitle>
          <ol className="relative ml-2 space-y-3 border-l-2 border-dashed border-line pl-5">
            {jugadas.map((j, k) => {
              const td = /TD|touchdown/i.test(j.tipo) || /touchdown| pass from | run \(/i.test(j.texto);
              return (
                <li key={k} className="enter relative" style={{ animationDelay: `${Math.min(k, 12) * 0.04}s` }}>
                  <span className={clsx("absolute -left-[31px] top-0.5 grid h-5 w-5 place-items-center rounded-full ring-4 ring-[var(--surface-1)]",
                    td ? "bg-pink" : "bg-[var(--caramel)]")}>
                    <span className="h-1.5 w-1.5 rounded-full bg-white" />
                  </span>
                  <div className="flex flex-wrap items-baseline gap-x-2 text-xs text-mute">
                    <span className="font-bold text-ink2">Q{j.cuarto ?? "?"} · {j.reloj}</span>
                    {j.equipo && <span className="rounded-full bg-s2 px-1.5 font-bold text-ink2">{j.equipo}</span>}
                    <span className="font-display text-sm font-semibold tnum text-ink">{away} {j.visita ?? 0} – {j.local ?? 0} {home}</span>
                  </div>
                  <div className="mt-0.5 text-sm text-ink">{j.texto}</div>
                </li>
              );
            })}
          </ol>
          <p className="mt-3 text-xs text-mute">Texto oficial de ESPN (en inglés).</p>
        </section>
      )}
      {videos.length > 0 ? (
        <section>
          <SectionTitle icon={Popcorn} tone="lila">Videos de {away} y {home}</SectionTitle>
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {videos.map((c) => <VideoCard key={c.id} c={c} list={videos} />)}
          </div>
        </section>
      ) : !jugadas.length && (
        <Empty mood="think">Todavía no hay jugadas ni videos de este partido. Aparecen en cuanto empieza.</Empty>
      )}
    </div>
  );
}

/** Videos donde sale el jugador (si ESPN tiene). */
export function PlayerVideos({ playerId, name }: { playerId: string; name: string }) {
  const { data } = useApi<{ videos: Clip[] }>(`/api/videos?player_id=${playerId}&limit=12`);
  if (!data?.videos.length) return null;
  return <VideoRail clips={data.videos} title={<>Videos de {name}</>} />;
}

export function NewsVideos() {
  const { data } = useApi<{ videos: Clip[] }>("/api/videos?limit=16");
  if (!data?.videos.length) return null;
  return (
    <div className="card p-5">
      <VideoRail clips={data.videos} title={<span className="flex items-center gap-1">Lo que se dice en video <Duo icon={Megaphone} tone="rosa" size={18} /></span>} />
    </div>
  );
}
