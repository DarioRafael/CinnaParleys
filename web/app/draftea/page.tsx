"use client";

import { NotePencil } from "@phosphor-icons/react";
import clsx from "clsx";
import { ChevronDown, ClipboardPaste, Layers, Plus, Search, Trash2, Wand2, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { mutate } from "swr";
import { american, kickoffLabel, pct, post, useApi } from "@/lib/api";
import { EvChip } from "@/components/pick-card";
import { useTeams } from "@/components/teams";
import { Empty, Headshot, SectionTitle, TeamLogo, PageHeader } from "@/components/ui";
import { DrafteaParlays, EscalonesPanel } from "@/components/escalones";

/* ------------------------------------------------------------------ tipos */
type Opt = { stat: string; label: string; unit?: string; line: number | null; line_src?: string | null; proj?: number | null; proj_label?: string };
type TeamOpt = { mercado: "spread" | "total" | "ml" | "team_total"; label: string; line: number | null; line_src?: string | null };
type CatPlayer = {
  player_id: string; name: string; team: string; opp: string; position: string; game_id: string; kickoff: string;
  headshot?: string | null; status?: string; p_play?: number; backup_qb?: boolean; opts: Opt[];
};
type CatTeam = { team: string; opp: string; is_home: boolean; game_id: string; kickoff: string; opts: TeamOpt[] };
type Catalog = { players: CatPlayer[]; teams: CatTeam[] };

type Row = {
  ok: boolean; error?: string; raw?: string; line_id?: string; tipo?: string; player_id?: string; name?: string;
  team?: string; mercado?: string; stat?: string; label?: string; line?: number | null; side?: string;
  odds?: number | null; p_side?: number; ev?: number | null; proj?: number | null; unit?: string; headshot?: string;
  title?: string; opp?: string; game_id?: string; kickoff?: string;
  soft?: { consensus: number; ventaja: number; texto: string } | null;
};
type Sel = { kind: "player"; p: CatPlayer } | { kind: "team"; t: CatTeam };

const norm = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const NO_SIDE = new Set(["tds", "tds2", "ml", "spread"]);
/** Línea inicial: la de la casa; si ninguna casa la tiene, la proyección de Cinna redondeada a .5 */
const defaultLine = (o: { line: number | null; proj?: number | null }) =>
  o.line != null ? String(o.line) : o.proj != null && o.proj > 1 ? String(Math.floor(o.proj) + 0.5) : "";

/* ------------------------------------------------------------------ página */
export default function DrafteaPage() {
  const { data: cat } = useApi<Catalog>("/api/draftea/catalogo", { revalidateOnFocus: false });
  const { data, mutate: refetch } = useApi<{ lines: Row[]; payouts: Record<string, number> }>("/api/draftea");
  const [sel, setSel] = useState<Sel | null>(null);
  const games = useMemo(() => {
    const m = new Map<string, { game_id: string; partido: string; kickoff: string }>();
    for (const t of cat?.teams ?? []) {
      if (!m.has(t.game_id)) m.set(t.game_id, { game_id: t.game_id, partido: t.is_home ? `${t.opp} @ ${t.team}` : `${t.team} @ ${t.opp}`, kickoff: t.kickoff });
    }
    return Array.from(m.values()).sort((a, b) => a.kickoff.localeCompare(b.kickoff));
  }, [cat]);

  const refresh = () => {
    refetch();
    mutate((k) => typeof k === "string" && k.startsWith("/api/parlays"));
  };
  const del = async (id?: string) => {
    await fetch(`/api/draftea${id ? `?line_id=${id}` : ""}`, { method: "DELETE" });
    refresh();
  };

  return (
    <div className="space-y-6">
      <PageHeader duo={NotePencil} tone="menta" kicker="a jugar" title="Draftea">
        <p>
          Busca al jugador o al equipo, elige qué quieres apostar y la línea (ya viene puesta la del mercado). Cinna te da
          la probabilidad real y si la línea está <b>blanda</b>. Draftea no publica sus momios en internet, pero sus líneas suelen
          ser casi iguales a las de <b>Playdoit</b>, que Cinna sí lee cada hora.
        </p>
        <p>
          <b>Regla de Draftea:</b> en un parlay sólo cabe <b>una Más/Menos de jugador por partido</b>; lo demás son escalones fijos
          (<b>X+</b>, p. ej. 192+, 202+, 212+ yds). Abajo tienes hasta dónde subir con cada jugador y parlays que ya respetan la regla.
        </p>
      </PageHeader>

      {games.length > 0 && <DrafteaParlays games={games} />}
      {games.length > 0 && <EscalonesPanel games={games} />}

      <Builder cat={cat} sel={sel} setSel={setSel} onSaved={refresh} />

      <MyLines rows={data?.lines ?? []} onDelete={del} />

      <PasteBox onSaved={refresh} />
      <Payouts initial={data?.payouts} onSaved={refetch} />
    </div>
  );
}

/* ------------------------------------------------------------------ buscador + constructor */
function Builder({ cat, sel, setSel, onSaved }: { cat?: Catalog; sel: Sel | null; setSel: (s: Sel | null) => void; onSaved: () => void }) {
  const teams = useTeams();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const h = (e: MouseEvent) => { if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  const results = useMemo(() => {
    const t = norm(q.trim());
    if (!cat || t.length < 1) return [] as Sel[];
    const ps: Sel[] = cat.players
      .filter((p) => norm(p.name).includes(t) || norm(p.name).split(" ").some((w) => w.startsWith(t)))
      .sort((a, b) => Number(norm(b.name).startsWith(t)) - Number(norm(a.name).startsWith(t)))
      .slice(0, 8).map((p) => ({ kind: "player", p }));
    const ts: Sel[] = cat.teams
      .filter((x) => {
        const m = teams[x.team];
        return norm(x.team).startsWith(t) || (m && (norm(m.name).includes(t) || norm(m.nick ?? "").includes(t)));
      })
      .slice(0, 4).map((x) => ({ kind: "team", t: x }));
    return [...ts, ...ps];
  }, [q, cat, teams]);

  const choose = (s: Sel) => { setSel(s); setQ(""); setOpen(false); };

  return (
    <div className="card p-5">
      <SectionTitle>1. Arma tu línea</SectionTitle>
      <div ref={boxRef} className="relative">
        <div className="flex items-center gap-2 rounded-xl border border-line bg-s2 px-3 focus-within:border-accent">
          <Search size={16} className="text-mute" />
          <input
            value={q} autoComplete="off"
            onChange={(e) => { setQ(e.target.value); setOpen(true); setHi(0); }}
            onFocus={() => setOpen(true)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => Math.min(h + 1, results.length - 1)); }
              else if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)); }
              else if (e.key === "Enter" && results[hi]) { e.preventDefault(); choose(results[hi]); }
              else if (e.key === "Escape") setOpen(false);
            }}
            placeholder={cat ? "Escribe un jugador (p. ej. Barkley) o un equipo (p. ej. Eagles)…" : "Cargando jugadores…"}
            className="h-11 w-full bg-transparent text-sm outline-none placeholder:text-mute"
          />
          {q && <button onClick={() => setQ("")} className="text-mute hover:text-ink"><X size={15} /></button>}
        </div>
        {open && results.length > 0 && (
          <div className="absolute z-20 mt-1 max-h-96 w-full overflow-auto rounded-xl border border-line bg-s1 p-1 shadow-xl">
            {results.map((r, i) => (
              <button key={r.kind === "player" ? r.p.player_id : r.t.team} onMouseEnter={() => setHi(i)} onClick={() => choose(r)}
                className={clsx("flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left", i === hi ? "bg-s2" : "")}>
                {r.kind === "player" ? (
                  <>
                    <Headshot src={r.p.headshot} name={r.p.name} size={32} />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{r.p.name}</div>
                      <div className="truncate text-xs text-mute">{r.p.position} · {r.p.team} vs {r.p.opp} · {kickoffLabel(r.p.kickoff)}</div>
                    </div>
                    {r.p.status && r.p.status !== "Disponible" && <span className="text-[11px] text-warning">{r.p.status}</span>}
                  </>
                ) : (
                  <>
                    <TeamLogo team={teams[r.t.team] ?? { abbr: r.t.team }} size={32} />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{teams[r.t.team]?.name ?? r.t.team}</div>
                      <div className="truncate text-xs text-mute">Equipo · {r.t.is_home ? "vs" : "@"} {r.t.opp} · {kickoffLabel(r.t.kickoff)}</div>
                    </div>
                    <span className="text-[11px] text-mute">spread · total · ganador</span>
                  </>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {sel ? <Editor key={sel.kind === "player" ? sel.p.player_id : sel.t.team} sel={sel} onClose={() => setSel(null)} onSaved={onSaved} />
        : <p className="mt-3 text-xs text-mute">Tip: escribe sólo una parte del nombre. Salen los jugadores y equipos de su partido más cercano.</p>}
    </div>
  );
}

function Editor({ sel, onClose, onSaved }: { sel: Sel; onClose: () => void; onSaved: () => void }) {
  const teams = useTeams();
  const opts = sel.kind === "player" ? sel.p.opts : sel.t.opts;
  const keyOf = (o: Opt | TeamOpt) => ("stat" in o ? o.stat : o.mercado);
  const [k, setK] = useState<string>(keyOf(opts[0]));
  const cur = opts.find((o) => keyOf(o) === k) ?? opts[0];
  const [line, setLine] = useState<string>(defaultLine(cur));
  const [side, setSide] = useState<"over" | "under" | "step" | null>(null);
  const [odds, setOdds] = useState("");
  const [res, setRes] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => { setLine(defaultLine(cur)); setSide(null); setMsg(""); }, [k]); // eslint-disable-line react-hooks/exhaustive-deps

  const item = useMemo(() => {
    const ln = line === "" ? null : Number(line.replace(",", "."));
    if (sel.kind === "player") {
      if (side === "step" && ln != null) {
        return { tipo: "jugador", player_id: sel.p.player_id, game_id: sel.p.game_id, stat: k, line: Math.round(ln) - 0.5, side: "over", escalon: Math.round(ln), odds: odds || null };
      }
      return { tipo: "jugador", player_id: sel.p.player_id, game_id: sel.p.game_id, stat: k, line: ln, side, odds: odds || null };
    }
    return { tipo: "equipo", game_id: sel.t.game_id, team: sel.t.team, mercado: k, line: ln, side, odds: odds || null };
  }, [sel, k, line, side, odds]);

  // evaluación en vivo (con una pequeña espera para no disparar en cada tecla)
  useEffect(() => {
    const t = setTimeout(async () => {
      try {
        const r = await post<{ rows: Row[] }>("/api/draftea/evaluar", { items: [item], save: false });
        setRes(r.rows[0]);
      } catch { setRes(null); }
    }, 250);
    return () => clearTimeout(t);
  }, [item]);

  const add = async () => {
    setBusy(true);
    try {
      const r = await post<{ rows: Row[]; saved: number }>("/api/draftea/evaluar", { items: [{ ...item, side: item.side ?? res?.side }], save: true });
      if (r.saved) { setMsg("Agregada a tus líneas"); onSaved(); } else setMsg(r.rows[0]?.error ?? "No se pudo agregar");
    } finally { setBusy(false); }
  };

  const title = sel.kind === "player" ? sel.p.name : (teams[sel.t.team]?.name ?? sel.t.team);
  const sub = sel.kind === "player"
    ? `${sel.p.position} · ${sel.p.team} vs ${sel.p.opp} · ${kickoffLabel(sel.p.kickoff)}`
    : `${sel.t.is_home ? "vs" : "@"} ${sel.t.opp} · ${kickoffLabel(sel.t.kickoff)}`;
  const needSide = !NO_SIDE.has(k);
  const shownSide = side ?? (res?.ok ? (res.side as "over" | "under") : null);
  const canStep = sel.kind === "player" && !(k === "tds" || k === "tds2");

  return (
    <div className="mt-4 rounded-xl border border-line bg-s2/40 p-4">
      <div className="flex items-center gap-3">
        {sel.kind === "player" ? <Headshot src={sel.p.headshot} name={sel.p.name} size={44} /> : <TeamLogo team={teams[sel.t.team] ?? { abbr: sel.t.team }} size={44} />}
        <div className="min-w-0 flex-1">
          <div className="text-base font-semibold">{title}</div>
          <div className="text-xs text-mute">{sub}</div>
        </div>
        <button onClick={onClose} className="rounded-md p-1.5 text-mute hover:bg-s2 hover:text-ink" title="Cambiar"><X size={16} /></button>
      </div>

      <div className="mt-4 text-[11px] font-semibold uppercase tracking-wider text-mute">¿Qué quieres apostar?</div>
      <div className="mt-2 flex flex-wrap gap-2">
        {opts.map((o) => {
          const kk = keyOf(o);
          return (
            <button key={kk} onClick={() => setK(kk)}
              className={clsx("rounded-lg border px-3 py-1.5 text-left text-sm", kk === k ? "border-accent bg-accent-soft text-ink" : "border-line text-ink2 hover:text-ink")}>
              {o.label}
              {o.line != null && !(kk === "tds" || kk === "tds2") && <span className="ml-1.5 text-xs text-mute tnum">{kk === "spread" && o.line > 0 ? "+" : ""}{o.line}</span>}
            </button>
          );
        })}
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-[auto_auto_1fr]">
        {!(k === "tds" || k === "tds2" || k === "ml") && (
          <label className="text-xs text-mute">
            {k === "spread" ? `Hándicap de ${sel.kind === "team" ? sel.t.team : ""}` : "Línea"}
            <div className="mt-1 flex items-center gap-1">
              <button onClick={() => setLine((v) => String(Math.round((Number(v || 0) - 0.5) * 10) / 10))} className="h-9 w-9 rounded-lg border border-line text-ink2 hover:text-ink">−</button>
              <input value={line} onChange={(e) => setLine(e.target.value)} inputMode="decimal"
                className="h-9 w-24 rounded-lg border border-line bg-s1 px-2 text-center text-sm text-ink outline-none focus:border-accent tnum" />
              <button onClick={() => setLine((v) => String(Math.round((Number(v || 0) + 0.5) * 10) / 10))} className="h-9 w-9 rounded-lg border border-line text-ink2 hover:text-ink">+</button>
            </div>
            {cur.line_src && <div className="mt-1 text-[11px]">Línea de {cur.line_src}: <span className="tnum">{cur.line}</span></div>}
          </label>
        )}
        {needSide && (
          <div className="text-xs text-mute">
            Lado
            <div className="mt-1 flex w-fit overflow-hidden rounded-lg border border-line">
              {(["over", "under"] as const).map((sd) => (
                <button key={sd} onClick={() => setSide(sd)}
                  className={clsx("h-9 px-4 text-sm", shownSide === sd ? "bg-accent text-on-accent" : "text-ink2 hover:text-ink")}>
                  {sd === "over" ? "Más" : "Menos"}
                </button>
              ))}
              {canStep && (
                <button onClick={() => { setSide("step"); setLine((v) => String(Math.ceil(Number(v || 0)))); }} title="Escalón fijo de Draftea: X o más"
                  className={clsx("h-9 px-4 text-sm", shownSide === "step" ? "bg-accent text-on-accent" : "text-ink2 hover:text-ink")}>
                  X+
                </button>
              )}
            </div>
            {!side && <div className="mt-1 text-[11px]">Sin elegir: Cinna propone el mejor lado</div>}
            {side === "step" && <div className="mt-1 text-[11px]">Escalón: escribe el número de Draftea (p. ej. 212 = 212 o más)</div>}
          </div>
        )}
        <label className="text-xs text-mute">
          Momio en Draftea (opcional)
          <input value={odds} onChange={(e) => setOdds(e.target.value)} placeholder="1.80x o -110"
            className="mt-1 block h-9 w-40 rounded-lg border border-line bg-s1 px-2 text-sm text-ink outline-none placeholder:text-mute focus:border-accent tnum" />
        </label>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4 rounded-xl bg-s1 px-4 py-3">
        {res?.ok ? (
          <>
            <div>
              <div className={clsx("text-2xl font-bold tnum", (res.p_side ?? 0) >= 0.58 ? "text-good" : (res.p_side ?? 0) < 0.5 ? "text-critical" : "")}>{pct(res.p_side)}</div>
              <div className="text-[11px] text-mute">probabilidad</div>
            </div>
            <div className="min-w-0 flex-1 text-sm">
              <div className="font-semibold">{res.title}</div>
              <div className="text-xs text-mute">
                {res.proj != null && (k === "tds" || k === "tds2" ? null : `Proyección de Cinna: ${res.proj} ${res.unit ?? ""}`)}
                {res.soft && <span className={clsx("ml-2", res.soft.ventaja > 0 ? "text-good" : res.soft.ventaja < 0 ? "text-critical" : "")}>{res.soft.texto}</span>}
              </div>
            </div>
            <EvChip ev={res.ev} />
          </>
        ) : (
          <div className="text-sm text-mute">{res?.error ?? "Calculando…"}</div>
        )}
        <button disabled={busy || !res?.ok} onClick={add}
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3.5 py-2 text-sm font-semibold text-on-accent disabled:opacity-50">
          <Plus size={15} /> Agregar a mis líneas
        </button>
        {msg && <span className="text-xs text-good">{msg}</span>}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ mis líneas */
function MyLines({ rows, onDelete }: { rows: Row[]; onDelete: (id?: string) => void }) {
  const teams = useTeams();
  const ok = rows.filter((r) => r.ok);
  const [joint, setJoint] = useState<number | null>(null);
  useEffect(() => {
    if (ok.length < 2) { setJoint(null); return; }
    post<{ p_joint: number }>("/api/parlay", {
      legs: ok.map((r) => ({ game_id: r.game_id, player_id: r.tipo === "equipo" ? null : r.player_id,
        team: r.tipo === "equipo" ? r.team : null, market: r.tipo === "equipo" ? r.mercado : r.stat,
        kind: r.tipo === "equipo" ? r.mercado : r.stat === "tds" ? ((r.line ?? 0.5) < 1 ? "td" : "td2") : "ou", line: r.line,
        side: r.tipo === "equipo" && (r.mercado === "ml" || r.mercado === "spread") ? r.team : r.side, prob: r.p_side, title: r.title })),
    }).then((x) => setJoint(x.p_joint)).catch(() => setJoint(null));
  }, [JSON.stringify(ok.map((r) => [r.line_id, r.p_side]))]); // eslint-disable-line react-hooks/exhaustive-deps
  const pay = ok.every((r) => r.odds != null) && ok.length >= 2
    ? ok.reduce((acc, r) => acc * (r.odds! > 0 ? 1 + r.odds! / 100 : 1 + 100 / -r.odds!), 1) : null;

  return (
    <section>
      <SectionTitle right={rows.length ? <button onClick={() => onDelete()} className="text-xs text-mute hover:text-critical">Borrar todas</button> : null}>
        2. Mis líneas de Draftea
      </SectionTitle>
      {rows.length ? (
        <>
          <div className="card divide-y divide-[var(--border)]">
            {rows.map((r, i) => (
              <div key={r.line_id ?? i} className="flex flex-wrap items-center gap-3 px-4 py-3">
                {r.tipo === "equipo"
                  ? <TeamLogo team={teams[r.team ?? ""] ?? { abbr: r.team }} size={36} />
                  : <Headshot src={r.headshot} name={r.name} size={36} />}
                <div className="min-w-0 flex-1">
                  {r.ok ? (
                    <>
                      <div className="truncate text-sm font-semibold">{r.title}</div>
                      <div className="truncate text-xs text-mute">
                        {r.label}{r.proj != null && r.stat !== "tds" ? ` · proyección ${r.proj} ${r.unit ?? ""}` : ""}
                        {r.odds != null ? ` · Draftea ${american(r.odds)}` : ""}
                      </div>
                      {r.soft && <div className={clsx("mt-0.5 text-xs", r.soft.ventaja > 0 ? "text-good" : r.soft.ventaja < 0 ? "text-critical" : "text-mute")}>{r.soft.texto}</div>}
                    </>
                  ) : (
                    <>
                      <div className="truncate text-sm text-ink2">{r.raw ?? r.title}</div>
                      <div className="text-xs text-critical">{r.error}</div>
                    </>
                  )}
                </div>
                {r.ok && (
                  <>
                    <EvChip ev={r.ev} />
                    <div className="w-16 text-right">
                      <div className={clsx("text-lg font-bold tnum", (r.p_side ?? 0) >= 0.58 ? "text-good" : (r.p_side ?? 0) < 0.5 ? "text-critical" : "")}>{pct(r.p_side)}</div>
                      <div className="text-[10px] text-mute">{r.tipo === "equipo" && (r.mercado === "ml" || r.mercado === "spread") ? r.team : r.side === "over" ? "Más" : "Menos"}</div>
                    </div>
                  </>
                )}
                {r.line_id && (
                  <button onClick={() => onDelete(r.line_id)} className="rounded-md p-1.5 text-mute hover:bg-s2 hover:text-critical"><Trash2 size={15} /></button>
                )}
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-4 text-sm">
            {joint != null && (
              <span className="inline-flex items-center gap-1.5 text-ink2"><Layers size={15} className="text-mute" />
                Si juegas todas juntas: <b className="text-ink tnum">{pct(joint, 1)}</b>{pay ? <> · paga <b className="text-ink tnum">{pay.toFixed(2)}x</b> · VE <b className={clsx("tnum", joint * pay - 1 >= 0 ? "text-good" : "text-critical")}>{((joint * pay - 1) * 100).toFixed(1)}%</b></> : null}
              </span>
            )}
            <Link href="/parlays?draftea=1" className="ml-auto text-accent hover:underline">Que Cinna arme parlays con mis líneas →</Link>
          </div>
        </>
      ) : <Empty>Aún no agregas líneas. Busca un jugador o equipo arriba.</Empty>}
    </section>
  );
}

/* ------------------------------------------------------------------ pegar texto (opcional) */
function PasteBox({ onSaved }: { onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [rows, setRows] = useState<Row[] | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (save: boolean) => {
    setBusy(true);
    try {
      const r = await post<{ rows: Row[] }>("/api/draftea/parse", { text, save });
      setRows(r.rows);
      if (save) { onSaved(); setText(""); }
    } finally { setBusy(false); }
  };
  return (
    <div className="card">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 px-5 py-3.5 text-left text-sm font-semibold">
        <ClipboardPaste size={15} className="text-mute" /> ¿Muchas líneas? Pégalas como texto
        <ChevronDown size={15} className={clsx("ml-auto text-mute transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="border-t border-line p-5">
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={5}
            placeholder={"Saquon Barkley yardas por tierra 70.5 menos\nJalen Hurts yardas de pase más 215.5 1.87x\nDK Metcalf anota TD +160"}
            className="w-full resize-y rounded-xl border border-line bg-s2 px-3 py-2.5 font-mono text-sm outline-none placeholder:text-mute focus:border-accent" />
          <div className="mt-3 flex gap-2">
            <button disabled={!text.trim() || busy} onClick={() => run(false)} className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3.5 py-2 text-sm text-ink2 hover:text-ink disabled:opacity-50"><Wand2 size={15} /> Revisar</button>
            <button disabled={!text.trim() || busy} onClick={() => run(true)} className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3.5 py-2 text-sm font-semibold text-on-accent disabled:opacity-50"><Plus size={15} /> Agregar todas</button>
          </div>
          {rows && (
            <ul className="mt-3 space-y-1 text-sm">
              {rows.map((r, i) => (
                <li key={i} className="flex justify-between gap-3">
                  <span className={r.ok ? "text-ink" : "text-critical"}>{r.ok ? r.title : `${r.raw} — ${r.error}`}</span>
                  {r.ok && <span className="tnum">{pct(r.p_side)}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ pagos fijos (opcional) */
function Payouts({ initial, onSaved }: { initial?: Record<string, number>; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [pay, setPay] = useState<Record<string, string>>({});
  useEffect(() => {
    if (initial) setPay(Object.fromEntries(Object.entries(initial).map(([k, v]) => [k, String(v)])));
  }, [initial]);
  const save = async () => {
    const r = await post<{ payouts: Record<string, number> }>("/api/draftea/payouts", { payouts: pay });
    setPay(Object.fromEntries(Object.entries(r.payouts).map(([k, v]) => [k, String(v)])));
    onSaved();
  };
  return (
    <div className="card">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 px-5 py-3.5 text-left text-sm font-semibold">
        Pagos fijos por número de picks (sólo si Draftea te paga así)
        <ChevronDown size={15} className={clsx("ml-auto text-mute transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="border-t border-line p-5">
          <p className="mb-3 text-xs text-mute">Normalmente Draftea paga por momio de cada pick (1.80x × 1.75x…): en ese caso déjalo vacío y pon el momio en cada línea.</p>
          <div className="grid grid-cols-4 gap-2">
            {[2, 3, 4, 5, 6, 7, 8].map((n) => (
              <label key={n} className="text-xs text-mute">
                {n} picks
                <input value={pay[String(n)] ?? ""} onChange={(e) => setPay({ ...pay, [String(n)]: e.target.value })} inputMode="decimal" placeholder="x"
                  className="mt-1 block w-full rounded-lg border border-line bg-s2 px-2 py-1.5 text-sm text-ink outline-none focus:border-accent tnum" />
              </label>
            ))}
          </div>
          <button onClick={save} className="mt-3 rounded-lg border border-line px-3 py-1.5 text-sm text-ink2 hover:text-ink">Guardar pagos</button>
        </div>
      )}
    </div>
  );
}
