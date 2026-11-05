"use client";

import { Duo, IconTile, PIcon, Tone } from "./icons";
import { Football, Newspaper, Popcorn, Target } from "@phosphor-icons/react";
import clsx from "clsx";
import { ChevronLeft, ChevronRight, ExternalLink, Play, X } from "lucide-react";
import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { ago } from "@/lib/api";

export type Clip = {
  id: string; titulo: string; descripcion?: string; publicado?: string | null; duracion?: number | null;
  poster?: string | null; mp4: string; equipos: string[]; jugadores?: { espn_id: string; name: string }[];
  tipo: "props" | "jugada" | "noticia"; web?: string | null; logos?: { abbr: string; logo: string | null }[];
};

export const TIPO: Record<Clip["tipo"], { label: string; icon: PIcon; tone: Tone }> = {
  props: { label: "Para tus apuestas", icon: Target, tone: "rosa" },
  jugada: { label: "Jugada", icon: Football, tone: "canela" },
  noticia: { label: "Noticia", icon: Newspaper, tone: "cielo" },
};

export function dur(s?: number | null) {
  if (!s) return "";
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.round(s % 60)).padStart(2, "0")}`;
}

type Ctx = { play: (c: Clip, list?: Clip[]) => void };
const VideoCtx = createContext<Ctx>({ play: () => undefined });
export const useVideo = () => useContext(VideoCtx);

/** Reproductor flotante compartido: cualquier tarjeta de video de la app lo abre. */
export function VideoProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ list: Clip[]; idx: number } | null>(null);
  const play = useCallback((c: Clip, list?: Clip[]) => {
    const l = list && list.some((x) => x.id === c.id) ? list : [c];
    setState({ list: l, idx: l.findIndex((x) => x.id === c.id) });
  }, []);
  return (
    <VideoCtx.Provider value={{ play }}>
      {children}
      {state && (
        <Lightbox list={state.list} idx={state.idx} onClose={() => setState(null)}
          onNav={(d) => setState((s) => s && { ...s, idx: (s.idx + d + s.list.length) % s.list.length })} />
      )}
    </VideoCtx.Provider>
  );
}

function Lightbox({ list, idx, onClose, onNav }: { list: Clip[]; idx: number; onClose: () => void; onNav: (d: number) => void }) {
  const c = list[idx];
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight" && list.length > 1) onNav(1);
      if (e.key === "ArrowLeft" && list.length > 1) onNav(-1);
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = prev; };
  }, [list.length, onClose, onNav]);
  return (
    <div className="fixed inset-0 z-[70] grid place-items-center p-3 sm:p-6" role="dialog" aria-modal="true" aria-label={c.titulo}>
      <button className="absolute inset-0 bg-[rgba(24,14,10,0.78)] backdrop-blur-sm" aria-label="Cerrar video" onClick={onClose} />
      <div className="enter relative w-full max-w-4xl">
        <div className="mb-2 flex items-center justify-between gap-3 px-1 text-white">
          <span className="flex items-center gap-2 font-hand text-xl">
            <Duo icon={Popcorn} tone="lila" size={26} /> {list.length > 1 ? `${idx + 1} de ${list.length}` : "A verlo"}
          </span>
          <button onClick={onClose} className="rounded-full bg-white/15 p-2 hover:bg-white/25" aria-label="Cerrar"><X size={18} /></button>
        </div>
        <div className="overflow-hidden rounded-3xl bg-black shadow-2xl ring-4 ring-[var(--pink-soft)]">
          <video key={c.id} src={c.mp4} poster={c.poster ?? undefined} controls autoPlay playsInline className="aspect-video w-full bg-black" />
        </div>
        <div className="mt-3 rounded-2xl bg-s1 p-4">
          <div className="flex flex-wrap items-center gap-2 text-xs text-mute">
            <TipoChip t={c.tipo} />
            {c.duracion ? <span className="tnum">{dur(c.duracion)}</span> : null}
            {c.publicado && <span>· {ago(c.publicado)}</span>}
            <span>· en inglés (ESPN)</span>
          </div>
          <div className="mt-1.5 font-display text-lg font-semibold leading-snug text-ink">{c.titulo}</div>
          {c.descripcion && <p className="mt-1 text-sm text-ink2">{c.descripcion}</p>}
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <Tags c={c} />
            {c.web && (
              <a href={c.web} target="_blank" rel="noopener noreferrer" className="ml-auto inline-flex items-center gap-1 text-xs font-semibold text-accent hover:underline">
                Ver en ESPN <ExternalLink size={12} />
              </a>
            )}
          </div>
        </div>
        {list.length > 1 && (
          <>
            <button onClick={() => onNav(-1)} aria-label="Video anterior"
              className="absolute left-1 top-1/2 -translate-y-1/2 rounded-full bg-white/90 p-2.5 text-[#3a2318] shadow-lg hover:scale-105 sm:-left-14"><ChevronLeft size={20} /></button>
            <button onClick={() => onNav(1)} aria-label="Video siguiente"
              className="absolute right-1 top-1/2 -translate-y-1/2 rounded-full bg-white/90 p-2.5 text-[#3a2318] shadow-lg hover:scale-105 sm:-right-14"><ChevronRight size={20} /></button>
          </>
        )}
      </div>
    </div>
  );
}

export function TipoChip({ t }: { t: Clip["tipo"] }) {
  const x = TIPO[t] ?? TIPO.noticia;
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-bold",
      t === "props" ? "bg-pink-soft text-ink" : t === "jugada" ? "bg-good-soft text-good" : "bg-s2 text-ink2")}>
      <Duo icon={x.icon} tone={x.tone} size={14} /> {x.label}
    </span>
  );
}

function Tags({ c, max = 4 }: { c: Clip; max?: number }) {
  const logos = c.logos ?? c.equipos.map((abbr) => ({ abbr, logo: null }));
  return (
    <>
      {logos.slice(0, max).map((t) => (
        <span key={t.abbr} className="inline-flex items-center gap-1 rounded-full bg-s2 py-0.5 pl-0.5 pr-2 text-[11px] font-bold text-ink2">
          {t.logo ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={t.logo} alt="" className="h-4 w-4 object-contain" />
          ) : <span className="w-1" />}
          {t.abbr}
        </span>
      ))}
    </>
  );
}

/** Tarjeta de video: miniatura con zoom suave y botón de play que late. */
export function VideoCard({ c, list, compact }: { c: Clip; list?: Clip[]; compact?: boolean }) {
  const { play } = useVideo();
  return (
    <button onClick={() => play(c, list)} className="group block w-full text-left" aria-label={`Ver video: ${c.titulo}`}>
      <div className="relative overflow-hidden rounded-2xl bg-s3 ring-1 ring-[var(--border)]">
        {c.poster ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={c.poster} alt="" loading="lazy" className="aspect-video w-full object-cover transition-transform duration-500 group-hover:scale-[1.06]" />
        ) : <div className="aspect-video w-full" />}
        <div className="absolute inset-0 bg-[linear-gradient(180deg,transparent_45%,rgba(20,10,6,0.55))]" />
        <span className="absolute inset-0 grid place-items-center">
          <span className="play-ring grid h-11 w-11 place-items-center rounded-full bg-white/95 text-[#b5582b] shadow-lg transition-transform duration-300 group-hover:scale-110">
            <Play size={18} className="ml-0.5 fill-current" />
          </span>
        </span>
        {c.duracion ? <span className="absolute bottom-2 right-2 rounded-md bg-black/65 px-1.5 py-0.5 text-[11px] font-bold text-white tnum">{dur(c.duracion)}</span> : null}
        <span className="absolute left-2 top-2"><TipoChip t={c.tipo} /></span>
      </div>
      <div className={clsx("mt-2 line-clamp-2 font-semibold leading-snug text-ink group-hover:text-brand", compact ? "text-[13px]" : "text-sm")}>{c.titulo}</div>
      {!compact && (
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-mute">
          <Tags c={c} max={3} />
          {c.publicado && <span>{ago(c.publicado)}</span>}
        </div>
      )}
    </button>
  );
}

/** Carrusel horizontal de videos (se desliza con el dedo o con las flechas). */
export function VideoRail({ clips, title, right }: { clips: Clip[]; title?: ReactNode; right?: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  if (!clips.length) return null;
  const by = (d: number) => ref.current?.scrollBy({ left: d * (ref.current.clientWidth * 0.8), behavior: "smooth" });
  return (
    <section>
      <div className="mb-3 flex items-end justify-between gap-3">
        <h2 className="flex items-center gap-2 font-display text-[13px] font-medium uppercase tracking-[0.12em] text-ink2">
          <IconTile icon={Popcorn} tone="lila" size={26} className="-my-1" /> {title ?? "Videos"}
        </h2>
        <div className="flex items-center gap-2">
          {right}
          <button onClick={() => by(-1)} aria-label="Anteriores" className="rounded-full border border-line bg-s1 p-1.5 text-ink2 hover:text-brand"><ChevronLeft size={16} /></button>
          <button onClick={() => by(1)} aria-label="Siguientes" className="rounded-full border border-line bg-s1 p-1.5 text-ink2 hover:text-brand"><ChevronRight size={16} /></button>
        </div>
      </div>
      <div ref={ref} className="no-scrollbar -mx-1 flex snap-x snap-mandatory gap-4 overflow-x-auto px-1 pb-2">
        {clips.map((c) => (
          <div key={c.id} className="w-[240px] shrink-0 snap-start sm:w-[270px]"><VideoCard c={c} list={clips} /></div>
        ))}
      </div>
    </section>
  );
}
