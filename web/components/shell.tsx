"use client";

import { Duo, IconTile, PIcon, Tone } from "./icons";
import { Alarm, Calculator, Cards, ChartLineUp, ChatsCircle, Football, FootballHelmet, Newspaper, NotePencil, Popcorn, Target, Ticket } from "@phosphor-icons/react";
import clsx from "clsx";
import { Menu as MenuIcon, Play, RefreshCw, Search, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { mutate } from "swr";
import { Team, ago, post, precargar, useApi } from "@/lib/api";
import { CinnaBun, CinnaLogo, Mood, Wordmark } from "./brand";
import { BotonEscanear, EscanerProvider } from "./escaner";
import { ParlayProvider } from "./parlay";
import { ThemeSwitch } from "./theme";
import { Clip, VideoProvider, dur, useVideo } from "./videos";

/* ------------------------------------------------------------------ menú */
type BadgeKey = "segura" | "cambios";
type NavItem = { href: string; label: string; hint: string; icon: PIcon; tone: Tone; badge?: BadgeKey };
const SECTIONS: { title: string; items: NavItem[] }[] = [
  {
    title: "la jornada",
    items: [
      { href: "/", label: "Semana", hint: "Partidos y pronósticos", icon: Football, tone: "canela" },
      { href: "/picks", label: "Picks", hint: "Seguras, valor y riesgo", icon: Target, tone: "rosa", badge: "segura" },
      { href: "/noticias", label: "Noticias", hint: "Lesiones y cambios", icon: Newspaper, tone: "cielo", badge: "cambios" },
      { href: "/videos", label: "Videos", hint: "Clips para tus props", icon: Popcorn, tone: "lila" },
    ],
  },
  {
    title: "a jugar",
    items: [
      { href: "/armados", label: "Armados", hint: "Parlays listos por partido", icon: Cards, tone: "rosa" },
      { href: "/parlays", label: "Parlays", hint: "Súper parlay y guiones", icon: Ticket, tone: "miel" },
      { href: "/draftea", label: "Draftea", hint: "Tus líneas, revisadas", icon: NotePencil, tone: "menta" },
      { href: "/calculadora", label: "Calculadora", hint: "Probabilidad de una línea", icon: Calculator, tone: "cielo" },
    ],
  },
  {
    title: "para entender",
    items: [
      { href: "/equipos", label: "Equipos", hint: "Ranking de poder", icon: FootballHelmet, tone: "canela" },
      { href: "/rendimiento", label: "Rendimiento", hint: "Cómo le ha ido a Cinna", icon: ChartLineUp, tone: "menta" },
      { href: "/claude", label: "Pregúntale a Claude", hint: "Platica el partido", icon: ChatsCircle, tone: "rosa" },
    ],
  },
];
const ALL = SECTIONS.flatMap((s) => s.items);
const MOBILE = ["/", "/picks", "/parlays", "/videos"].map((h) => ALL.find((x) => x.href === h)!);

// datos que usa cada pantalla (mismas llaves que las páginas): se bajan al pasar el mouse por el menú
const PRECARGA: Record<string, string[]> = {
  "/": ["/api/week", "/api/picks?tier=segura&limit=60", "/api/changes?limit=4", "/api/romper?limit=8", "/api/videos?limit=14",
    "/api/parlays?mode=top_elite&legs=2&top=1&casa=Draftea", "/api/parlays?mode=top_elite&legs=3&top=1&casa=Draftea",
    "/api/parlays?mode=balanceada&top=1&casa=Draftea"],
  "/picks": ["/api/picks?limit=500"],
  "/noticias": ["/api/news?only_impact=true&limit=80", "/api/changes?limit=40", "/api/injuries?key_only=true", "/api/videos?limit=16"],
  "/videos": ["/api/videos?limit=160"],
  "/parlays": ["/api/week", "/api/parlays?mode=top_elite&casa=Draftea", "/api/super_parlay", "/api/guiones?n=8&nivel=0.65",
    "/api/plan?banca=1000&riesgo=conservador", "/api/mis_apuestas"],
  "/draftea": ["/api/draftea/catalogo", "/api/draftea"],
  "/equipos": ["/api/teams"],
  "/rendimiento": ["/api/performance", "/api/autopsias", "/api/categorias"],
};

const isActive = (href: string, path: string) =>
  href === "/" ? path === "/" || path.startsWith("/partido") : path.startsWith(href);

export type MenuData = {
  temporada: number; semana: number; partidos: number; terminados: number;
  proximo: { game_id: string; kickoff: string; home: Team; away: Team } | null;
  en_vivo: { game_id: string; detalle: string; cuarto: number | null; home: Team; away: Team }[];
  conteos: { segura: number; valor: number; arriesgada: number; cambios: number; videos: number };
  clips: Clip[]; tips: string[]; ahora: string;
};
export const useMenu = () => useApi<MenuData>("/api/menu", { refreshInterval: 60000 });

function useNow(ms = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

/** Ánimo de Cinna según el momento: en vivo se emociona, de madrugada tiene sueño. */
export function useMood(m?: MenuData): Mood {
  const h = new Date().getHours();
  if (m?.en_vivo.length) return "wow";
  if (h >= 23 || h < 6) return "sleepy";
  return "happy";
}

/* ------------------------------------------------------------------ marco */
export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [drawer, setDrawer] = useState(false);
  useEffect(() => {
    // cuando la página ya cargó y está tranquila, baja los datos de las demás pantallas (una por una)
    const orden = ["/picks", "/parlays", "/noticias", "/videos", "/rendimiento", "/equipos", "/draftea", "/"];
    let i = 0;
    let t: ReturnType<typeof setTimeout>;
    const idle = (cb: () => void) => ("requestIdleCallback" in window
      ? (window as Window & { requestIdleCallback: (f: () => void) => number }).requestIdleCallback(cb) : setTimeout(cb, 200));
    const siguiente = () => {
      if (i >= orden.length) return;
      precargar(PRECARGA[orden[i++]]);
      t = setTimeout(() => idle(siguiente), 700);
    };
    t = setTimeout(() => idle(siguiente), 3500);
    return () => clearTimeout(t);
  }, []);
  useEffect(() => setDrawer(false), [path]);
  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawer(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawer]);

  return (
    <ParlayProvider>
      <VideoProvider>
      <EscanerProvider>
        <div className="flex min-h-screen">
          <aside className="side side-edge sticky top-0 z-20 hidden h-screen w-[272px] shrink-0 md:block">
            <SideMenu path={path} />
          </aside>

          {drawer && (
            <div className="fixed inset-0 z-50 md:hidden" role="dialog" aria-modal="true" aria-label="Menú">
              <button className="absolute inset-0 bg-[rgba(30,18,12,0.45)] backdrop-blur-[2px]" aria-label="Cerrar menú" onClick={() => setDrawer(false)} />
              <aside className="side drawer-in absolute inset-y-0 left-0 w-[86%] max-w-[300px] shadow-2xl">
                <button onClick={() => setDrawer(false)} aria-label="Cerrar menú"
                  className="absolute right-3 top-4 z-20 rounded-full bg-s1/80 p-2 text-ink2 hover:text-brand"><X size={18} /></button>
                <SideMenu path={path} />
              </aside>
            </div>
          )}

          <div className="flex min-w-0 flex-1 flex-col">
            <TopBar onMenu={() => setDrawer(true)} />
            <main key={path} className="enter mx-auto w-full max-w-[1400px] flex-1 px-4 pb-28 pt-5 md:px-8 md:pb-12">{children}</main>
          </div>

          <nav className="fixed inset-x-3 bottom-3 z-30 flex rounded-2xl border border-line bg-s1/95 p-1 shadow-lg backdrop-blur md:hidden">
            {MOBILE.map(({ href, label, icon }) => {
              const active = isActive(href, path);
              return (
                <Link key={href} href={href} data-active={active} onTouchStart={() => precargar(PRECARGA[href])}
                  className={clsx("nav-item flex flex-1 flex-col items-center gap-0.5 rounded-xl py-1.5 text-[10.5px] font-semibold transition-colors",
                    active ? "bg-[var(--hero-to)] text-brand" : "text-mute")}>
                  <Duo icon={icon} tone={active ? "canela" : "neutro"} size={24} className="nav-icon" /> {label}
                </Link>
              );
            })}
            <button onClick={() => setDrawer(true)} className="flex flex-1 flex-col items-center gap-0.5 rounded-xl py-1.5 text-[10.5px] font-semibold text-mute">
              <span className="grid h-6 w-6 place-items-center"><MenuIcon size={20} /></span> Menú
            </button>
          </nav>
        </div>
      </EscanerProvider>
      </VideoProvider>
    </ParlayProvider>
  );
}

/* ------------------------------------------------------------------ menú lateral */

function SideMenu({ path }: { path: string }) {
  const { data: m } = useMenu();
  const innerRef = useRef<HTMLDivElement>(null);
  const [pill, setPill] = useState<{ top: number; height: number } | null>(null);

  useLayoutEffect(() => {
    const update = () => {
      const el = innerRef.current?.querySelector<HTMLElement>('[data-active="true"]');
      setPill(el ? { top: el.offsetTop, height: el.offsetHeight } : null);
    };
    update();
    const ro = new ResizeObserver(update);
    if (innerRef.current) ro.observe(innerRef.current);
    return () => ro.disconnect();
  }, [path]);

  const mood = useMood(m);
  return (
    <div className="relative flex h-full flex-col">
      <Link href="/" className="group relative z-10 flex items-center gap-3 px-5 pb-3 pt-4">
        <CinnaLogo size={40} className="transition-transform duration-300 group-hover:-rotate-12" />
        <div>
          <Wordmark />
          <div className="mt-1 text-[10.5px] font-semibold uppercase leading-none tracking-[0.16em] text-mute">Análisis NFL</div>
        </div>
      </Link>

      <KickoffTicket m={m} />

      <nav className="no-scrollbar relative mt-3 min-h-0 flex-1 overflow-y-auto px-3 pb-2" aria-label="Secciones">
        <div ref={innerRef} className="relative">
          {pill && (
            <div className="nav-pill pointer-events-none absolute inset-x-0 rounded-xl bg-pill shadow-[0_1px_0_var(--border),0_8px_18px_-10px_rgba(var(--shadow-color),0.4)]"
              style={{ top: pill.top, height: pill.height }}>
              <span className="absolute -left-3 top-1/2 h-6 w-[3px] -translate-y-1/2 rounded-r-full bg-[var(--brand)]" />
            </div>
          )}
          {SECTIONS.map((sec, si) => (
            <div key={sec.title} className={si ? "mt-2.5" : ""}>
              <SectionLabel>{sec.title}</SectionLabel>
              {sec.items.map((it) => {
                const active = isActive(it.href, path);
                const badge = it.badge && m ? m.conteos[it.badge] : 0;
                return (
                  <Link key={it.href} href={it.href} data-active={active} aria-current={active ? "page" : undefined} title={it.hint}
                    onMouseEnter={() => precargar(PRECARGA[it.href])} onFocus={() => precargar(PRECARGA[it.href])}
                    className={clsx("nav-item relative z-10 flex items-center gap-3 rounded-xl px-2 py-[5px] transition-colors",
                      !active && "hover:bg-[var(--tile)]")}>
                    <IconTile icon={it.icon} tone={active ? "canela" : "neutro"} size={34} iconSize={19} iconClassName="nav-icon" />
                    <span className="min-w-0 flex-1">
                      <span className={clsx("block text-[14px] leading-tight", active ? "font-semibold text-ink" : "font-medium text-ink2")}>{it.label}</span>
                      <span className="nav-hint"><span><span className="block truncate pt-0.5 text-[11.5px] text-mute">{it.hint}</span></span></span>
                    </span>
                    {badge ? (
                      <span className={clsx("rounded-md px-1.5 py-px text-[10.5px] font-semibold tnum",
                        it.badge === "cambios" ? "bg-[var(--accent-soft)] text-accent" : "bg-s2 text-ink2")}
                        title={it.badge === "cambios" ? `${badge} cambios por noticias en las últimas 12 h` : "Picks seguras"}>
                        {it.badge === "cambios" ? "nuevo" : badge}
                      </span>
                    ) : null}
                  </Link>
                );
              })}
            </div>
          ))}
        </div>
      </nav>

      <div className="space-y-2.5 px-4 pb-4 pt-1">
        <div className="hidden [@media(min-height:940px)]:block"><ClipDelMomento clips={m?.clips ?? []} /></div>
        <div className="[@media(min-height:940px)]:hidden"><ClipMini clips={m?.clips ?? []} /></div>
        {m?.tips?.length ? <CinnaTip tips={m.tips} mood={mood} /> : null}
        <div className="flex items-center justify-between">
          <ThemeSwitch />
          <SourceHealth />
        </div>
      </div>
    </div>
  );
}

function SectionLabel({ children }: { children: ReactNode }) {
  return <div className="mb-1 px-2 text-[10.5px] font-semibold uppercase tracking-[0.14em] text-mute">{children}</div>;
}

function countdown(ms: number) {
  if (ms <= 0) return "¡ya casi!";
  const s = Math.floor(ms / 1000);
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), mi = Math.floor((s % 3600) / 60), se = s % 60;
  const p = (n: number) => String(n).padStart(2, "0");
  return d > 0 ? `${d} d ${p(h)} h ${p(mi)} m` : `${p(h)}:${p(mi)}:${p(se)}`;
}

function MiniLogo({ t, size = 22 }: { t: Team; size?: number }) {
  return t.logo ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={t.logo} alt={t.abbr} width={size} height={size} className="object-contain" style={{ width: size, height: size }} />
  ) : <span className="text-[11px] font-bold">{t.abbr}</span>;
}

/** Boleto con muescas: cuenta regresiva al próximo kickoff, o el marcador en vivo (rota entre partidos). */
function KickoffTicket({ m }: { m?: MenuData }) {
  const now = useNow(1000);
  const [i, setI] = useState(0);
  const live = m?.en_vivo ?? [];
  useEffect(() => {
    if (live.length < 2) return;
    const t = setInterval(() => setI((x) => x + 1), 5000);
    return () => clearInterval(t);
  }, [live.length]);
  if (!m) return <div className="mx-4 h-[78px] rounded-2xl bg-tile" />;
  const g = live.length ? live[i % live.length] : null;
  const nx = m.proximo;
  const href = g ? `/partido/${g.game_id}` : nx ? `/partido/${nx.game_id}` : "/";
  return (
    <Link href={href} className="group relative z-10 mx-4 block transition-transform duration-200 hover:-translate-y-px">
      <div className="ticket flex h-[74px] overflow-hidden rounded-xl border border-line bg-pill">
        <div className="grid w-[62px] shrink-0 place-items-center bg-[var(--brand)] text-on-brand">
          <div className="text-center leading-none">
            <div className="text-[9px] font-semibold tracking-[0.18em] opacity-90">SEMANA</div>
            <div className="mt-1 font-display text-[30px] font-semibold">{m.semana}</div>
          </div>
        </div>
        <div className="my-2 border-l-2 border-dashed border-[var(--border-strong)]" />
        <div className="flex min-w-0 flex-1 flex-col justify-center px-3">
          {g ? (
            <div key={g.game_id} className="swap-in">
              <div className="flex items-center gap-1.5 text-[10.5px] font-extrabold uppercase tracking-wider text-critical">
                <span className="live-dot h-1.5 w-1.5 rounded-full bg-[var(--critical)]" /> En vivo{g.cuarto ? ` · Q${g.cuarto}` : ""}
                {live.length > 1 && <span className="ml-auto text-mute tnum">{(i % live.length) + 1}/{live.length}</span>}
              </div>
              <div className="mt-1 flex items-center gap-1.5 font-display text-[18px] font-semibold tnum text-ink">
                <MiniLogo t={g.away} /> {g.away.score ?? 0}
                <span className="text-mute">–</span>
                {g.home.score ?? 0} <MiniLogo t={g.home} />
              </div>
            </div>
          ) : nx ? (
            <>
              <div className="flex items-center gap-1 text-[10.5px] font-extrabold uppercase tracking-wider text-mute">
                <Duo icon={Alarm} tone="canela" size={15} /> Próximo kickoff
              </div>
              <div className="mt-0.5 flex items-center gap-1 text-[12px] font-bold text-ink2">
                <MiniLogo t={nx.away} size={18} /> {nx.away.abbr} <span className="text-mute">@</span> <MiniLogo t={nx.home} size={18} /> {nx.home.abbr}
              </div>
              <div className="font-display text-[17px] font-semibold leading-tight tnum text-ink">{countdown(new Date(nx.kickoff).getTime() - now)}</div>
            </>
          ) : (
            <>
              <div className="text-[10.5px] font-extrabold uppercase tracking-wider text-mute">Semana terminada</div>
              <div className="font-display text-[15px] font-semibold text-ink">{m.terminados} de {m.partidos} partidos</div>
            </>
          )}
        </div>
      </div>
    </Link>
  );
}

/** Un clip que va cambiando solo; al tocarlo se abre el reproductor. */
function ClipDelMomento({ clips }: { clips: Clip[] }) {
  const { play } = useVideo();
  const [i, setI] = useState(0);
  useEffect(() => {
    if (clips.length < 2) return;
    const t = setInterval(() => setI((x) => (x + 1) % clips.length), 9000);
    return () => clearInterval(t);
  }, [clips.length]);
  if (!clips.length) return null;
  const c = clips[i % clips.length];
  return (
    <div>
      <div className="mb-1 flex items-center justify-between px-1">
        <span className="flex items-center gap-1.5 text-[10.5px] font-extrabold uppercase tracking-[0.14em] text-mute"><Duo icon={Popcorn} tone="lila" size={16} /> Clip del momento</span>
        <Link href="/videos" className="text-[11px] font-bold text-mute hover:text-brand">ver todos</Link>
      </div>
      <button onClick={() => play(c, clips)} className="group relative block w-full overflow-hidden rounded-2xl text-left ring-1 ring-[var(--border)]" aria-label={`Ver video: ${c.titulo}`}>
        {c.poster ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img key={c.id} src={c.poster} alt="" className="swap-in aspect-video w-full object-cover transition-transform duration-700 group-hover:scale-105" />
        ) : <div className="aspect-video w-full bg-s3" />}
        <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(20,10,6,0)_30%,rgba(20,10,6,0.82))]" />
        <span className="play-ring absolute left-1/2 top-[38%] grid h-9 w-9 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-white/95 text-[#b5582b]">
          <Play size={15} className="ml-0.5 fill-current" />
        </span>
        {c.duracion ? <span className="absolute right-2 top-2 rounded-md bg-black/60 px-1.5 text-[10.5px] font-bold text-white tnum">{dur(c.duracion)}</span> : null}
        <span key={`t-${c.id}`} className="swap-in absolute inset-x-2.5 bottom-2 line-clamp-2 text-[12px] font-bold leading-snug text-white">{c.titulo}</span>
      </button>
      {clips.length > 1 && (
        <div className="mt-1.5 flex justify-center gap-1">
          {clips.map((x, k) => (
            <button key={x.id} onClick={() => setI(k)} aria-label={`Clip ${k + 1}`}
              className={clsx("h-1.5 rounded-full transition-all duration-300", k === i % clips.length ? "w-4 bg-[var(--brand)]" : "w-1.5 bg-[var(--border-strong)]")} />
          ))}
        </div>
      )}
    </div>
  );
}

/** Versión compacta del clip (pantallas no tan altas): miniatura + título, también va cambiando sola. */
function ClipMini({ clips }: { clips: Clip[] }) {
  const { play } = useVideo();
  const [i, setI] = useState(0);
  useEffect(() => {
    if (clips.length < 2) return;
    const t = setInterval(() => setI((x) => (x + 1) % clips.length), 9000);
    return () => clearInterval(t);
  }, [clips.length]);
  if (!clips.length) return null;
  const c = clips[i % clips.length];
  return (
    <button onClick={() => play(c, clips)} aria-label={`Ver video: ${c.titulo}`}
      className="group flex w-full items-center gap-2.5 rounded-2xl border border-line bg-pill p-1.5 pr-2.5 text-left shadow-sm transition-transform duration-300 hover:-translate-y-0.5">
      <span className="relative h-[46px] w-[80px] shrink-0 overflow-hidden rounded-xl bg-s3">
        {c.poster && (
          // eslint-disable-next-line @next/next/no-img-element
          <img key={c.id} src={c.poster} alt="" className="swap-in h-full w-full object-cover transition-transform duration-500 group-hover:scale-110" />
        )}
        <span className="absolute inset-0 grid place-items-center bg-black/15">
          <span className="play-ring grid h-6 w-6 place-items-center rounded-full bg-white/95 text-[#b5582b]"><Play size={11} className="ml-px fill-current" /></span>
        </span>
      </span>
      <span key={c.id} className="swap-in min-w-0">
        <span className="flex items-center gap-1 whitespace-nowrap text-[11px] font-bold leading-none text-mute"><Duo icon={Popcorn} tone="lila" size={13} /> Clip del momento</span>
        <span className="mt-0.5 line-clamp-2 text-[11.5px] font-bold leading-tight text-ink">{c.titulo}</span>
      </span>
    </button>
  );
}

/** Cinna da consejos que cambian solos cada rato. */
function CinnaTip({ tips, mood }: { tips: string[]; mood: Mood }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setI((x) => x + 1), 9000);
    return () => clearInterval(t);
  }, []);
  const tip = tips[i % tips.length];
  return (
    <div className="flex items-end gap-1.5">
      <CinnaBun size={36} mood={mood} className="shrink-0" />
      <div key={tip} className="swap-in relative min-h-[44px] flex-1 rounded-xl rounded-bl-[4px] border border-line bg-pill px-3 py-2 text-[12px] leading-snug text-ink2">
        {tip}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ barra superior */
type Status = {
  state: { running: boolean; step: string | null; started: string | null; last_error: string | null };
  last_refresh: { at: string; secs: number; games: number; players: number; picks: number; news: number } | null;
  current: { season: number; week: number } | null;
  sources: Record<string, number | string> | null;
  stale: boolean; refresh_minutes: number;
};

function TopBar({ onMenu }: { onMenu: () => void }) {
  const { data: st, mutate: refetch } = useApi<Status>("/api/status", {
    refreshInterval: (d) => (d?.state.running ? 2500 : 60000),
  });
  const wasRunning = useRef(false);
  const kicked = useRef(false);

  // al abrir la app: si los datos están viejos, se actualiza solo
  useEffect(() => {
    if (kicked.current) return;
    kicked.current = true;
    post("/api/refresh?scope=auto").then(() => refetch()).catch(() => undefined);
  }, [refetch]);

  // al terminar una actualización, recarga todas las vistas
  useEffect(() => {
    const running = !!st?.state.running;
    if (wasRunning.current && !running) mutate((k) => typeof k === "string" && k !== "/api/status");
    wasRunning.current = running;
  }, [st?.state.running]);

  const running = st?.state.running;
  const last = st?.last_refresh?.at;
  const next = last ? new Date(new Date(last).getTime() + (st?.refresh_minutes ?? 60) * 60000) : null;
  const mins = next ? Math.max(0, Math.round((next.getTime() - Date.now()) / 60000)) : null;

  return (
    <header className="sticky top-0 z-20 border-b border-line bg-page/90 backdrop-blur-md">
      <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-2.5 px-4 py-3 md:flex-nowrap md:px-8">
        <button onClick={onMenu} aria-label="Abrir menú" className="rounded-xl border border-line bg-s1 p-2 text-ink2 md:hidden"><MenuIcon size={18} /></button>
        <Link href="/" className="flex shrink-0 items-center gap-2 md:hidden">
          <CinnaLogo size={30} />
          <Wordmark small />
        </Link>
        <SearchBox />
        <div className="ml-auto flex items-center gap-2">
          <BotonEscanear />
          <div className="flex items-center gap-2 whitespace-nowrap rounded-full border border-line bg-s1 px-3 py-1.5 text-xs">
            {running ? (
              <>
                <RefreshCw size={13} className="spin text-brand" />
                <span className="hidden max-w-[210px] truncate text-ink2 sm:inline">{st?.state.step ?? "Actualizando datos"}…</span>
              </>
            ) : (
              <>
                <span className={clsx("h-2 w-2 rounded-full", st?.stale ? "bg-[var(--warning)]" : "bg-[var(--good)]")} />
                <span className="text-ink2">
                  <span className="hidden sm:inline">Actualizado </span><span className="hidden min-[420px]:inline">{ago(last)}</span>
                  {mins != null && <span className="hidden text-mute lg:inline"> · próxima en {mins} min</span>}
                </span>
              </>
            )}
          </div>
          <button disabled={running}
            onClick={() => post("/api/refresh?scope=quick").then(() => refetch())}
            className="rounded-full border border-line bg-s1 p-2 text-ink2 hover:text-brand disabled:opacity-40" title="Actualizar ahora" aria-label="Actualizar ahora">
            <RefreshCw size={15} />
          </button>
        </div>
      </div>
      {st?.state.last_error && !running && (
        <div className="border-t border-line bg-critical/10 px-4 py-1.5 text-center text-xs text-critical">
          La última actualización falló: {st.state.last_error.slice(0, 140)}
        </div>
      )}
    </header>
  );
}

function SearchBox() {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const { data } = useApi<{ players: { player_id: string; name: string; team: string; position: string }[]; teams: { abbr: string; name: string }[] }>(
    q.length >= 2 ? `/api/search?q=${encodeURIComponent(q)}` : null);
  return (
    <div className="relative order-last w-full min-w-0 md:order-none md:w-auto md:max-w-sm md:flex-1">
      <Search size={15} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-mute" />
      <input value={q} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="Buscar jugador o equipo…" aria-label="Buscar jugador o equipo"
        className="w-full rounded-full border border-line bg-s1 py-2 pl-9 pr-3 text-sm outline-none placeholder:text-mute focus:border-brand focus:ring-4 focus:ring-[var(--brand-soft)]" />
      {open && data && (data.players.length > 0 || data.teams.length > 0) && (
        <div className="absolute left-0 right-0 top-full z-30 mt-1.5 overflow-hidden rounded-2xl border border-line bg-s1 p-1 shadow-2xl">
          {data.players.map((p) => (
            <button key={p.player_id} onMouseDown={() => { router.push(`/jugador/${p.player_id}`); setQ(""); }}
              className="flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-sm hover:bg-s2">
              <span className="font-semibold">{p.name}</span><span className="text-xs text-mute">{p.position} · {p.team}</span>
            </button>
          ))}
          {data.teams.map((t) => (
            <button key={t.abbr} onMouseDown={() => { router.push(`/equipos?t=${t.abbr}`); setQ(""); }}
              className="flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-sm hover:bg-s2">
              <span className="font-semibold">{t.name}</span><span className="text-xs text-mute">Equipo</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function SourceHealth() {
  const { data } = useApi<Status>("/api/status");
  const s = data?.sources;
  if (!s) return null;
  const rows: [string, string | number | undefined][] = [
    ["Partidos ESPN", s.espn_games], ["Lesiones", s.espn_injuries], ["Noticias", s.news],
    ["Props DraftKings", s.props], ["Sleeper", s.sleeper],
  ];
  const ok = rows.filter(([, v]) => v != null && v !== 0 && v !== "0").length;
  return (
    <span className="group relative flex cursor-default items-center gap-1.5 text-[11px] font-bold text-mute" tabIndex={0}>
      <span className={clsx("h-2 w-2 rounded-full", ok === rows.length ? "bg-[var(--good)]" : "bg-[var(--warning)]")} />
      {ok}/{rows.length} fuentes
      <span className="pointer-events-none absolute bottom-full right-0 z-30 mb-2 w-48 rounded-xl border border-line bg-s1 p-2.5 opacity-0 shadow-xl transition-opacity group-hover:opacity-100 group-focus:opacity-100">
        {rows.map(([k, v]) => (
          <span key={k} className="flex justify-between py-0.5 text-xs font-normal">
            <span className="text-ink2">{k}</span><span className="tnum font-bold text-ink">{v ?? "—"}</span>
          </span>
        ))}
      </span>
    </span>
  );
}
