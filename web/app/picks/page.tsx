"use client";

import { Target } from "@phosphor-icons/react";
import clsx from "clsx";
import { Crown, Flame, Gem, ShieldCheck } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState, useTransition } from "react";
import { GameCard, Pick, useApi } from "@/lib/api";
import { PickCard } from "@/components/pick-card";
import { CombinarPartidos, TiraPartidos } from "@/components/partidos-picks";
import { Empty, Loading, Segmented, PageHeader, useProgresivo } from "@/components/ui";

type Tier = "segura" | "valor" | "arriesgada" | "todas";
type Kind = "todos" | "ou" | "alt" | "td" | "game" | "mercado";

type BtSel = { n: number; hit: number | null; roi?: number } | null | undefined;
type Bt = { seasons?: { test: number; cur: number }; super_test?: BtSel; super_cur?: BtSel; elite_solo_test?: BtSel; elite_solo_cur?: BtSel };

const pc = (x?: number | null) => (x == null ? "—" : `${Math.round(x * 100)}%`);
const roiTxt = (x: BtSel) => (x?.roi != null ? ` (retorno ${x.roi >= 0 ? "+" : ""}${Math.round(x.roi * 100)}%)` : "");

function info(bt?: Bt): Record<string, { icon: typeof ShieldCheck; title: string; text: string }> {
  const ss = bt?.seasons;
  const hist = (a: BtSel, b: BtSel) => (a && ss
    ? ` Acertaron ${pc(a.hit)} en ${ss.test}${roiTxt(a)}${b?.n ? ` y ${pc(b.hit)} en ${ss.cur}${roiTxt(b)}` : ""} contra líneas de cierre.`
    : "");
  return {
    segura: { icon: ShieldCheck, title: "Seguras", text: `En Más/Menos son los Súper élite: Cinna y el meta-modelo coinciden con más fuerza.${hist(bt?.super_test, bt?.super_cur)} En escaleras y TDs son las muy probables (aciertan ~90%), pero la casa las paga poco: sirven de base para parlays, solas no ganan a la larga. En «Mercados» (puntos y touchdowns del partido) son los escalones que pasan ~8 de cada 10 veces; todas sus líneas están en la pestaña Mercados de cada partido.` },
    valor: { icon: Gem, title: "Valor", text: `Picks Élite de Más/Menos: Cinna y el meta-modelo (entrenado con apuestas reales) van del mismo lado.${hist(bt?.elite_solo_test, bt?.elite_solo_cur)} Para ganarle a -110 basta 52.4%.` },
    arriesgada: { icon: Flame, title: "Arriesgadas", text: "Pagan mucho pero fallan seguido: TDs, techos altos, underdogs y tiempo extra. En el backtest no mostraron ventaja a la larga: juégalas con poco." },
  };
}

function PicksInner() {
  const sp = useSearchParams();
  const [tier, setTierRaw] = useState<Tier>((sp.get("tier") as Tier) ?? "segura");
  const [kind, setKindRaw] = useState<Kind>("todos");
  const [sort, setSortRaw] = useState<"confidence" | "prob" | "edge">("confidence");
  const [eliteOnly, setEliteRaw] = useState(sp.get("elite") === "1");
  // los filtros cambian "en segundo plano": el botón responde al instante y la lista se redibuja después
  const [pending, startTransition] = useTransition();
  const setTier = (v: Tier) => startTransition(() => setTierRaw(v));
  const setKind = (v: Kind) => startTransition(() => setKindRaw(v));
  const setSort = (v: "confidence" | "prob" | "edge") => startTransition(() => setSortRaw(v));
  const setEliteOnly = (f: (x: boolean) => boolean) => startTransition(() => setEliteRaw(f));
  const { data, isLoading } = useApi<{ picks: Pick[]; counts: Record<string, number>; bt?: Bt }>("/api/picks?limit=500");
  const { data: wk } = useApi<{ games: GameCard[] }>("/api/week");
  const [sel, setSelRaw] = useState<string[]>(sp.get("partido") ? [sp.get("partido") as string] : []);
  const toggle = (id: string) => startTransition(() => setSelRaw((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id])));
  const juegos = useMemo(() => (wk?.games ?? []).filter((g) => g.status === "pre"), [wk]);
  const conteo = useMemo(() => {
    const c: Record<string, number> = {};
    for (const p of data?.picks ?? []) if (p.tier) c[p.game_id] = (c[p.game_id] ?? 0) + 1;
    return c;
  }, [data]);
  const nElite = (data?.picks ?? []).filter((p) => p.elite && (!sel.length || sel.includes(p.game_id))).length;

  const list = useMemo(() => {
    let l = data?.picks ?? [];
    if (sel.length) l = l.filter((p) => sel.includes(p.game_id));
    if (eliteOnly) l = l.filter((p) => p.elite);
    else if (tier !== "todas") l = l.filter((p) => p.tier === tier);
    if (kind === "game") l = l.filter((p) => p.type === "game" && !p.extra);
    else if (kind === "td") l = l.filter((p) => p.kind === "td" || p.kind === "td2");
    else if (kind !== "todos") l = l.filter((p) => p.kind === kind);
    const key = (p: Pick) => (p.super_elite ? 2 : p.elite ? 1 : 0);
    return [...l].sort((a, b) => key(b) - key(a) || (sort === "edge" ? (b.edge ?? -1) - (a.edge ?? -1) : sort === "prob" ? b.prob - a.prob : b.confidence - a.confidence));
  }, [data, tier, kind, sort, eliteOnly, sel]);

  const prog = useProgresivo(list.length, `${tier}|${kind}|${sort}|${eliteOnly}|${sel.join(",")}`);
  if (isLoading && !data) return <Loading label="Buscando las mejores apuestas…" />;
  const c = data?.counts ?? {};
  const infoBox = tier !== "todas" ? info(data?.bt)[tier] : null;

  return (
    <div className="space-y-5">
      <PageHeader duo={Target} tone="rosa" kicker="la jornada" title="Picks">
        <p>Cada línea de 8 casas evaluada por Cinna (modelo + mercado + expertos), con el mejor precio disponible y su valor esperado. Si la línea de Draftea es distinta, usa la calculadora del jugador. Touchdowns, goles de campo, puntos y primera mitad de cada partido están en su pestaña <b>Mercados</b>.</p>
      </PageHeader>
      {juegos.length > 0 && (
        <section className="space-y-2">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2 className="font-display text-[17px] font-bold tracking-tight text-ink">Partidos de la jornada</h2>
            <span className="text-xs text-mute">Elige uno o varios para ver sólo sus picks y armar un súper pick entre ellos. La flecha abre el partido.</span>
          </div>
          <TiraPartidos juegos={juegos} sel={sel} onToggle={toggle} conteo={conteo} />
        </section>
      )}
      {sel.length > 0 && <CombinarPartidos sel={sel} juegos={juegos} onClear={() => startTransition(() => setSelRaw([]))} />}
      <div className="flex flex-wrap items-center gap-3">
        <Segmented value={tier} onChange={setTier} options={[
          { value: "segura", label: "Seguras", count: c.segura ?? 0 },
          { value: "valor", label: "Valor", count: c.valor ?? 0 },
          { value: "arriesgada", label: "Arriesgadas", count: c.arriesgada ?? 0 },
          { value: "todas", label: "Todas" },
        ]} />
        <Segmented value={kind} onChange={setKind} options={[
          { value: "todos", label: "Todo" }, { value: "ou", label: "Más/Menos" }, { value: "alt", label: "Al menos X" },
          { value: "td", label: "Touchdowns" }, { value: "game", label: "Partido" },
          { value: "mercado", label: "Mercados", count: (data?.picks ?? []).filter((p) => p.extra).length },
        ]} />
        <button onClick={() => setEliteOnly((x) => !x)}
          className={clsx("inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-semibold",
            eliteOnly ? "border-warning bg-[var(--warning)]/15 text-warning" : "border-line text-ink2 hover:text-ink")}>
          <Crown size={15} /> Solo Élite <span className="rounded-md bg-page/60 px-1.5 text-[11px] tnum">{nElite}</span>
        </button>
        <select value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}
          className="rounded-lg border border-line bg-s1 px-3 py-2 text-sm text-ink2 outline-none">
          <option value="confidence">Ordenar: confianza</option>
          <option value="prob">Ordenar: probabilidad</option>
          <option value="edge">Ordenar: ventaja vs línea</option>
        </select>
      </div>
      {infoBox && (
        <div className="card flex items-start gap-3 px-4 py-3">
          <infoBox.icon size={18} className="mt-0.5 shrink-0 text-ink2" />
          <div className="text-sm text-ink2"><b className="text-ink">{infoBox.title}:</b> {infoBox.text}</div>
        </div>
      )}
      {list.length ? (
        <div className={clsx("transition-opacity duration-150", pending && "opacity-60")}>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
            {list.slice(0, prog.n).map((p) => <div key={p.pick_id} className="cv-auto"><PickCard p={p} /></div>)}
          </div>
          {prog.hayMas && <div ref={prog.ref} className="py-6 text-center text-xs font-semibold text-mute">Cargando más picks…</div>}
        </div>
      ) : (
        <Empty>No hay picks con este filtro todavía. Las casas publican las props de cada jugador unos días antes del partido.</Empty>
      )}
    </div>
  );
}

export default function PicksPage() {
  return <Suspense fallback={<Loading />}><PicksInner /></Suspense>;
}
