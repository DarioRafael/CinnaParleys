"use client";

import { ArrowSquareOut, CheckCircle, Circle, ClockCounterClockwise, FastForward, PuzzlePiece } from "@phosphor-icons/react";
import clsx from "clsx";
import Link from "next/link";
import { useRef, useState } from "react";
import { Team, ago, kickoffLabel, useApi } from "@/lib/api";
import { IconTile } from "./icons";
import { TeamLogo } from "./ui";

type Estado = { partidos: { nombre: string; at: string; mercados: number }[]; ultima?: { nombre: string; at: string } | null };
type Semana = {
  semana: number; faltan: number;
  partidos: { game_id: string; kickoff: string; home: Team; away: Team; pd_id: number | null; url: string | null;
    recibido: string | null; mercados: number | null }[];
};

/** Tarjeta corta para Armados: estado de la conexión con Playdoit y cuántos partidos de la semana faltan. */
export function ConectaTuCasa() {
  const { data } = useApi<Estado>("/api/playdoit/estado", { refreshInterval: 20000 });
  const { data: sem } = useApi<Semana>("/api/playdoit/semana", { refreshInterval: 20000 });
  const n = data?.partidos.length ?? 0;
  const faltan = sem?.faltan ?? 0;
  return (
    <div className="card flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
      <IconTile icon={PuzzlePiece} tone={n ? "menta" : "canela"} size={42} />
      <div className="min-w-0 flex-1 text-sm text-ink2">
        {n ? (
          <><b className="text-ink">Playdoit conectado: {n} partido{n === 1 ? "" : "s"} con sus líneas reales.</b>
            {faltan ? <> Faltan <b className="text-ink">{faltan}</b> de la semana (o ya tienen más de 12 h): ábrelos con un clic desde «Ver conexión».</>
              : " Todos los partidos de la semana están al día."}</>
        ) : (
          <><b className="text-ink">Usa las líneas y momios reales de Playdoit.</b> Con la extensión «Cinna» en tu navegador, cada partido que
            abras en Playdoit se manda solo y los armados se hacen con lo que de verdad ofrece la casa.</>
        )}
      </div>
      <Link href="/importar" className="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-line px-3 py-2 text-sm font-semibold text-ink2 hover:border-accent hover:text-ink">
        {n ? "Ver conexión" : "Conectar Playdoit"}
      </Link>
    </div>
  );
}

const DIA = (iso: string) => new Date(iso).toLocaleDateString("es-MX", { weekday: "long", day: "numeric", month: "short" });

/** Los partidos que faltan de la semana, cada uno con su enlace directo a Playdoit: un clic y llega solo. */
export function SemanaPlaydoit() {
  const { data } = useApi<Semana>("/api/playdoit/semana", { refreshInterval: 4000, dedupingInterval: 2000 });
  // partidos que ya abriste en esta sesión (para no repetir el mismo antes de que llegue)
  const abiertos = useRef<Record<string, number>>({});
  const [, refrescar] = useState(0);
  if (!data || !data.partidos.length) return null;
  const ahora = Date.now();
  const conLink = data.partidos.filter((p) => p.url && ahora - (abiertos.current[p.game_id] ?? 0) > 60_000);
  const faltan = conLink.filter((p) => !p.recibido);
  // primero los que faltan (por hora del partido); si ya están todos, el que llegó hace más tiempo (para actualizarlo)
  const siguiente = faltan[0] ?? [...conLink].sort((a, b) => (a.recibido ?? "").localeCompare(b.recibido ?? ""))[0];
  const abrirSiguiente = () => {
    if (!siguiente?.url) return;
    abiertos.current[siguiente.game_id] = Date.now();
    window.open(siguiente.url, "cinna_playdoit");       // siempre la misma pestaña de Playdoit
    refrescar((n) => n + 1);
  };
  const dias: Record<string, Semana["partidos"]> = {};
  for (const p of data.partidos) (dias[DIA(p.kickoff)] ??= []).push(p);
  const listos = data.partidos.length - data.faltan;
  return (
    <section className="card space-y-4 p-5">
      <div className="flex flex-wrap items-center gap-3">
        <IconTile icon={ClockCounterClockwise} tone={data.faltan ? "miel" : "menta"} size={42} />
        <div className="min-w-0 flex-1">
          <div className="font-display text-lg font-semibold text-ink">Semana {data.semana}: {listos} de {data.partidos.length} partidos al día</div>
          <p className="text-sm text-ink2">Toca «Abrir el siguiente»: se abre el partido en Playdoit, llega solo y aquí se pone en verde.
            Vuelve a tocarlo para el que sigue. Antes de apostar, actualízalos para tener los momios del momento.</p>
        </div>
      </div>
      {siguiente && (
        <div className="flex flex-col gap-2 rounded-2xl bg-s2 p-3 sm:flex-row sm:items-center">
          <button onClick={abrirSiguiente}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-brand-fill px-4 py-2.5 text-sm font-bold text-on-brand shadow-sm">
            <FastForward size={18} weight="fill" />
            {faltan.length ? "Abrir el siguiente que falta" : "Actualizar el siguiente"}
          </button>
          <div className="min-w-0 flex-1 text-xs text-ink2">
            Sigue: <b className="text-ink">{siguiente.away.nick ?? siguiente.away.abbr} @ {siguiente.home.nick ?? siguiente.home.abbr}</b>
            {faltan.length ? ` · faltan ${faltan.length}` : " · todos al día; éste es el que llegó hace más tiempo"}
            <div className="text-mute">Tip: pon Playdoit y Cinna lado a lado; así cada clic aquí abre el siguiente allá sin cambiar de ventana.</div>
          </div>
        </div>
      )}
      <div className="space-y-4">
        {Object.entries(dias).map(([dia, ps]) => (
          <div key={dia}>
            <div className="mb-2 text-xs font-bold uppercase tracking-wide text-mute">{dia}</div>
            <ul className="grid gap-2 md:grid-cols-2">
              {ps.map((p) => (
                <li key={p.game_id} className={clsx("flex items-center gap-3 rounded-xl px-3 py-2", p.recibido ? "bg-good-soft" : "bg-s2")}>
                  {p.recibido ? <CheckCircle size={20} weight="fill" className="shrink-0 text-good" /> : <Circle size={20} className="shrink-0 text-mute" />}
                  <div className="flex shrink-0 items-center gap-1"><TeamLogo team={p.away} size={22} /><span className="text-[10px] text-mute">@</span><TeamLogo team={p.home} size={22} /></div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold text-ink">{p.away.nick ?? p.away.abbr} @ {p.home.nick ?? p.home.abbr}</div>
                    <div className="text-[11px] text-mute">{kickoffLabel(p.kickoff)}{p.recibido ? ` · llegó ${ago(p.recibido)}` : ""}</div>
                  </div>
                  {p.url ? (
                    <a href={p.url} target="cinna_playdoit"
                      onClick={() => { abiertos.current[p.game_id] = Date.now(); }}
                      className={clsx("inline-flex shrink-0 items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-semibold",
                        p.recibido ? "border border-line bg-s1 text-ink2 hover:text-ink" : "bg-brand-fill text-on-brand")}>
                      {p.recibido ? "Actualizar" : "Abrir en Playdoit"} <ArrowSquareOut size={13} weight="bold" />
                    </a>
                  ) : (
                    <span className="shrink-0 text-[11px] text-mute" title="Abre la lista de NFL en Playdoit una vez y aparece su enlace">Búscalo en Playdoit</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
