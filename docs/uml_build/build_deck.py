"""Presentación: CinnaParleys explicada con UML (4 diagramas + 1 de reserva).

Todo se dibuja con figuras nativas de PowerPoint (editables). Paleta y tipografía de la app:
crema / canela / chocolate, tonos pastel por diagrama. Candara (cuerpo y títulos) + Segoe Print (notas a mano).
Uso:  python3.12 build_deck.py  -> ../CinnaParleys_UML.pptx
"""
from __future__ import annotations

import math
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
OUT = HERE.parent / "CinnaParleys_UML.pptx"

# ------------------------------------------------------------------ paleta
CHOCO = "3A2318"      # tinta
DARK = "24170F"       # fondo de portada y cierre
DARK2 = "33231A"
INK2 = "6B4F42"
MUTE = "7E6252"
PAGE = "FFFCF7"
WHITE = "FFFFFF"
CREAM = "FFF3E6"
LINE = "E5D3C0"
CANELA = "B5582B"
CANELA_T = "A8501F"
CARAMEL = "E9A35F"
ROSA = "EF8FA9"
TONE = {  # contorno, relleno pastel, fondo suave
    "canela": ("A8501F", "F6C99C", "FBE7D3"),
    "rosa": ("C0436C", "F9B8CA", "FDE3EA"),
    "cielo": ("2A6FB0", "B5D8F5", "E2EFFB"),
    "menta": ("1F7A4D", "AEE3C4", "DFF3E7"),
    "miel": ("946200", "F7D78A", "FCEFCC"),
    "lila": ("6D4FB8", "D2C4F4", "ECE6FB"),
}
BODY = "Candara"
HAND = "Segoe Print"

L, C, R = PP_ALIGN.LEFT, PP_ALIGN.CENTER, PP_ALIGN.RIGHT
TOP, MID, BOT = MSO_ANCHOR.TOP, MSO_ANCHOR.MIDDLE, MSO_ANCHOR.BOTTOM


def rgb(h: str) -> RGBColor:
    return RGBColor.from_string(h)


# ------------------------------------------------------------------ utilidades de dibujo
def _apply_runs(tf, paras, size, color, bold, font, align, italic=False, space_after=0, line_spacing=None):
    if isinstance(paras, str):
        paras = [paras]
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if space_after:
            p.space_after = Pt(space_after)
        if line_spacing:
            p.line_spacing = line_spacing
        runs = [(para, {})] if isinstance(para, str) else para
        for txt, o in runs:
            r = p.add_run()
            r.text = txt
            f = r.font
            f.name = o.get("font", font)
            f.size = Pt(o.get("size", size))
            f.bold = o.get("bold", bold)
            f.italic = o.get("italic", italic)
            f.color.rgb = rgb(o.get("color", color))


def text(sl, x, y, w, h, paras, size=14, color=CHOCO, bold=False, font=BODY, align=L, anchor=TOP,
         italic=False, space_after=0, line_spacing=None, fill=None, name=None):
    tb = sl.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    if fill:
        tb.fill.solid()
        tb.fill.fore_color.rgb = rgb(fill)
    _apply_runs(tf, paras, size, color, bold, font, align, italic, space_after, line_spacing)
    if name:
        tb.name = name
    return tb


def noeffect(shape):
    etree.SubElement(shape._element.spPr, qn("a:effectLst"))


def shadow(shape, alpha=16, blur=10, dist=3):
    spPr = shape._element.spPr
    eff = etree.SubElement(spPr, qn("a:effectLst"))
    sh = etree.SubElement(eff, qn("a:outerShdw"), blurRad=str(int(Pt(blur))), dist=str(int(Pt(dist))),
                          dir="5400000", algn="t", rotWithShape="0")
    clr = etree.SubElement(sh, qn("a:srgbClr"), val=CHOCO)
    etree.SubElement(clr, qn("a:alpha"), val=str(alpha * 1000))


def box(sl, x, y, w, h, fill=WHITE, line=None, lw=1.0, radius=None, kind=MSO_SHAPE.ROUNDED_RECTANGLE,
        dash=False, txt=None, size=13, color=CHOCO, bold=False, align=C, anchor=MID, font=BODY,
        margin=0.06, shadow_on=False, name=None):
    shp = sl.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    if kind == MSO_SHAPE.ROUNDED_RECTANGLE:
        r = 0.12 if radius is None else radius
        shp.adjustments[0] = min(0.5, r / min(w, h))
    if fill is None:
        shp.fill.background()
    else:
        shp.fill.solid()
        shp.fill.fore_color.rgb = rgb(fill)
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = rgb(line)
        shp.line.width = Pt(lw)
        if dash:
            shp.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    tf = shp.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(margin)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    tf.vertical_anchor = anchor
    if txt is not None:
        _apply_runs(tf, txt, size, color, bold, font, align)
    if shadow_on:
        shadow(shp)
    else:
        noeffect(shp)
    if name:
        shp.name = name
    return shp


def arrow(sl, x1, y1, x2, y2, color=CHOCO, lw=1.5, dash=False, head=None, tail="triangle", name=None, end="med"):
    """Línea recta. tail = punta en (x2,y2); head = punta en (x1,y1). Tipos: triangle, arrow, diamond, oval."""
    cn = sl.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    cn.line.color.rgb = rgb(color)
    cn.line.width = Pt(lw)
    if dash:
        cn.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    ln = cn.line._get_or_add_ln()
    if head:
        etree.SubElement(ln, qn("a:headEnd"), type=head, w=end, len=end)
    if tail:
        etree.SubElement(ln, qn("a:tailEnd"), type=tail, w=end, len=end)
    if name:
        cn.name = name
    return cn


def path(sl, pts, color=CHOCO, lw=1.5, dash=False, tail="triangle"):
    """Polilínea: punta sólo en el último tramo."""
    for i in range(len(pts) - 1):
        last = i == len(pts) - 2
        arrow(sl, *pts[i], *pts[i + 1], color=color, lw=lw, dash=dash, tail=tail if last else None)


def picture(sl, file, x, y, w, h=None):
    return sl.shapes.add_picture(str(ASSETS / file), Inches(x), Inches(y), Inches(w), Inches(h if h else w))


def icon_tile(sl, icon, tone, x, y, size=0.8, bg=None):
    box(sl, x, y, size, size, fill=bg or TONE[tone][2], radius=size * 0.32)
    pad = size * 0.2
    picture(sl, f"{icon}_{tone}.png", x + pad, y + pad, size - 2 * pad)


def ellipse_edge(cx, cy, rx, ry, tx, ty):
    """Punto del borde de una elipse en dirección al punto (tx, ty)."""
    dx, dy = tx - cx, ty - cy
    t = 1 / math.sqrt((dx / rx) ** 2 + (dy / ry) ** 2)
    return cx + dx * t, cy + dy * t


def actor(sl, cx, top, label, color=CHOCO, label_lines=None, scale=1.0):
    """Monito UML (actor)."""
    hd = 0.3 * scale
    head = sl.shapes.add_shape(MSO_SHAPE.OVAL, Inches(cx - hd / 2), Inches(top), Inches(hd), Inches(hd))
    head.fill.solid()
    head.fill.fore_color.rgb = rgb("FFF8F0")
    head.line.color.rgb = rgb(color)
    head.line.width = Pt(1.75)
    noeffect(head)
    neck = top + hd
    hip = neck + 0.42 * scale
    arrow(sl, cx, neck, cx, hip, color=color, lw=1.75, tail=None)
    arrow(sl, cx - 0.27 * scale, neck + 0.13 * scale, cx + 0.27 * scale, neck + 0.13 * scale, color=color, lw=1.75, tail=None)
    arrow(sl, cx, hip, cx - 0.22 * scale, hip + 0.33 * scale, color=color, lw=1.75, tail=None)
    arrow(sl, cx, hip, cx + 0.22 * scale, hip + 0.33 * scale, color=color, lw=1.75, tail=None)
    bottom = hip + 0.33 * scale
    lines = label_lines or [label]
    text(sl, cx - 0.85, bottom + 0.06, 1.7, 0.25 * len(lines) + 0.05,
         [[(lines[0], {"bold": True})]] + lines[1:], size=13, color=color, align=C)
    return bottom


def start_node(sl, cx, cy, d=0.28):
    s = sl.shapes.add_shape(MSO_SHAPE.OVAL, Inches(cx - d / 2), Inches(cy - d / 2), Inches(d), Inches(d))
    s.fill.solid()
    s.fill.fore_color.rgb = rgb(CHOCO)
    s.line.fill.background()
    noeffect(s)


def end_node(sl, cx, cy, d=0.36):
    o = sl.shapes.add_shape(MSO_SHAPE.OVAL, Inches(cx - d / 2), Inches(cy - d / 2), Inches(d), Inches(d))
    o.fill.solid()
    o.fill.fore_color.rgb = rgb(WHITE)
    o.line.color.rgb = rgb(CHOCO)
    o.line.width = Pt(1.75)
    noeffect(o)
    start_node(sl, cx, cy, d * 0.56)


def diamond(sl, cx, cy, w, h, fill=WHITE, line=CHOCO, lw=1.5):
    return box(sl, cx - w / 2, cy - h / 2, w, h, fill=fill, line=line, lw=lw, kind=MSO_SHAPE.DIAMOND)


def bar(sl, x, y, w, h):
    return box(sl, x, y, w, h, fill=CHOCO, kind=MSO_SHAPE.RECTANGLE)


def notes(sl, txt):
    sl.notes_slide.notes_text_frame.text = txt


# ------------------------------------------------------------------ marco de diapositivas
prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]
SW = 13.333


def new_slide(bg=PAGE):
    sl = prs.slides.add_slide(BLANK)
    sl.background.fill.solid()
    sl.background.fill.fore_color.rgb = rgb(bg)
    return sl


def header(sl, kicker, title, tone="canela"):
    text(sl, 0.6, 0.32, 9.5, 0.42, kicker, size=15, color=TONE[tone][0], font=HAND, name="Kicker")
    text(sl, 0.6, 0.72, 12.1, 0.75, title, size=34, bold=True, color=CHOCO, name="Título")


def page_number(sl, n, dark=False):
    text(sl, 12.13, 7.0, 0.6, 0.3, str(n), size=11, color="A88F80" if dark else MUTE, align=R)


def canvas(sl, x, y, w, h):
    return box(sl, x, y, w, h, fill=WHITE, line=LINE, lw=1, radius=0.18, shadow_on=True, name="Lienzo")


def side_panel(sl, tone, items, takeaway, x=9.6, y=1.65, w=3.13, h=5.3, glyphs=None):
    """Panel 'Cómo leerlo' + 'Lo que nos dice'. items = [(término, explicación)]; glyphs = funciones de dibujo."""
    ink, _, soft = TONE[tone]
    box(sl, x, y, w, h, fill=soft, radius=0.18, name="Panel")
    text(sl, x + 0.25, y + 0.22, w - 0.5, 0.35, "Cómo leerlo", size=18, bold=True, color=ink)
    yy = y + 0.7
    for i, (term, expl) in enumerate(items):
        gx = x + 0.25
        if glyphs and i < len(glyphs) and glyphs[i]:
            glyphs[i](sl, gx, yy)
            tx = gx + 0.55
        else:
            tx = gx
        tb = text(sl, tx, yy - 0.02, x + w - 0.22 - tx, 0.62,
                  [[(term, {"bold": True, "color": ink}), (" " + expl, {})]], size=13, color=CHOCO, line_spacing=0.95)
        yy += 0.68
    ty = y + h - 1.55
    box(sl, x + 0.18, ty, w - 0.36, 1.37, fill=WHITE, radius=0.14)
    text(sl, x + 0.35, ty + 0.12, w - 0.7, 0.3, "Lo que nos dice", size=14, bold=True, color=ink)
    text(sl, x + 0.35, ty + 0.45, w - 0.7, 0.85, takeaway, size=13, color=CHOCO, line_spacing=0.95)


# glifos pequeños para las leyendas
def g_actor(sl, x, y):
    cx = x + 0.2
    head = sl.shapes.add_shape(MSO_SHAPE.OVAL, Inches(cx - 0.07), Inches(y), Inches(0.14), Inches(0.14))
    head.fill.background()
    head.line.color.rgb = rgb(CHOCO)
    head.line.width = Pt(1.25)
    noeffect(head)
    arrow(sl, cx, y + 0.14, cx, y + 0.32, lw=1.25, tail=None)
    arrow(sl, cx - 0.12, y + 0.2, cx + 0.12, y + 0.2, lw=1.25, tail=None)
    arrow(sl, cx, y + 0.32, cx - 0.1, y + 0.46, lw=1.25, tail=None)
    arrow(sl, cx, y + 0.32, cx + 0.1, y + 0.46, lw=1.25, tail=None)


def g_oval(sl, x, y):
    box(sl, x, y + 0.08, 0.42, 0.26, fill="FFF8F0", line=CHOCO, lw=1.25, kind=MSO_SHAPE.OVAL)


def g_line(sl, x, y):
    arrow(sl, x, y + 0.22, x + 0.42, y + 0.22, lw=1.5, tail=None)


def g_dash(sl, x, y):
    arrow(sl, x, y + 0.22, x + 0.42, y + 0.22, lw=1.5, dash=True, tail="arrow")


def g_class(sl, x, y):
    box(sl, x, y + 0.04, 0.42, 0.36, fill=WHITE, line=CHOCO, lw=1.25, kind=MSO_SHAPE.RECTANGLE)
    box(sl, x, y + 0.04, 0.42, 0.12, fill=TONE["canela"][1], line=CHOCO, lw=1.25, kind=MSO_SHAPE.RECTANGLE)


def g_comp(sl, x, y):
    arrow(sl, x + 0.42, y + 0.22, x, y + 0.22, lw=1.5, tail="diamond", end="lg")


def g_aggr(sl, x, y):
    arrow(sl, x + 0.42, y + 0.22, x + 0.12, y + 0.22, lw=1.5, tail=None)
    box(sl, x, y + 0.14, 0.16, 0.16, fill=WHITE, line=CHOCO, lw=1.25, kind=MSO_SHAPE.DIAMOND)


def g_mult(sl, x, y):
    text(sl, x, y + 0.08, 0.5, 0.3, "2..*", size=12, bold=True, color=CHOCO)


def g_state(sl, x, y):
    box(sl, x, y + 0.06, 0.42, 0.3, fill=TONE["lila"][2], line=CHOCO, lw=1.25, radius=0.1)


def g_loop(sl, x, y):
    path(sl, [(x + 0.08, y + 0.38), (x + 0.08, y + 0.1), (x + 0.36, y + 0.1), (x + 0.36, y + 0.38)], lw=1.4)


def g_startend(sl, x, y):
    start_node(sl, x + 0.1, y + 0.22, 0.18)
    end_node(sl, x + 0.34, y + 0.22, 0.22)


def g_arrow(sl, x, y):
    arrow(sl, x, y + 0.22, x + 0.42, y + 0.22, lw=1.5)


# ================================================================== 1. PORTADA
sl = new_slide(DARK)
box(sl, 8.55, 1.15, 4.3, 4.3, fill=DARK2, kind=MSO_SHAPE.OVAL)
picture(sl, "cinna.png", 9.0, 1.45, 3.4)
for icon, tone, x, y in [("Target", "rosa", 8.35, 1.0), ("Ticket", "miel", 12.0, 2.15), ("Popcorn", "lila", 8.25, 4.55),
                         ("Football", "canela", 11.75, 4.85)]:
    icon_tile(sl, icon, tone, x, y, size=0.82)
picture(sl, "logo.png", 0.75, 1.35, 1.05)
text(sl, 1.95, 1.62, 6, 0.5, "presentación de la app", size=20, color=CARAMEL, font=HAND)
text(sl, 0.75, 2.55, 7.6, 1.2, [[("Cinna", {"color": CREAM}), ("Parleys", {"color": CARAMEL})]], size=66, bold=True)
text(sl, 0.75, 3.8, 7.6, 0.6, "La app explicada con UML", size=32, color="F6C99C", bold=True)
text(sl, 0.75, 4.5, 7.4, 0.9, "Cuatro diagramas sencillos y uno de reserva para entender quién la usa, con qué datos "
     "trabaja y cómo piensa.", size=18, color="D7C2B3")
text(sl, 0.75, 6.55, 6, 0.4, "Noviembre 2026", size=14, color="A88F80")
notes(sl, "Hoy vamos a explicar CinnaParleys, nuestra app de picks y parlays de la NFL, usando UML. "
          "Escogimos los diagramas más sencillos: cuatro principales y uno de reserva por si preguntan cómo cambia un partido con el tiempo.")

# ================================================================== 2. ¿QUÉ ES?
sl = new_slide()
header(sl, "para empezar", "¿Qué es CinnaParleys?")
text(sl, 0.6, 1.7, 5.3, 1.5, "Una app que corre en tu computadora, analiza la NFL con datos gratuitos y te ayuda a armar "
     "picks y parlays para Draftea y Playdoit, siempre con su probabilidad real.", size=17, color=INK2, line_spacing=1.05)
stats = [("20 000", "simulaciones por partido"), ("8", "casas de apuestas comparadas"), ("$0", "en APIs de pago")]
for i, (num, lab) in enumerate(stats):
    x = 0.6 + i * 1.8
    box(sl, x, 3.35, 1.62, 1.3, fill=WHITE, line=LINE, radius=0.16, shadow_on=True)
    text(sl, x + 0.15, 3.47, 1.32, 0.6, num, size=30, bold=True, color=CANELA_T)
    text(sl, x + 0.15, 4.05, 1.35, 0.55, lab, size=12, color=INK2, line_spacing=0.95)
feats = [("Target", "rosa", "Picks", "Cada línea de 8 casas con su probabilidad y su valor."),
         ("Ticket", "miel", "Parlays", "Combina patas con las correlaciones reales del partido."),
         ("Popcorn", "lila", "Videos", "Clips y jugadas de ESPN dentro de la misma app."),
         ("ChatsCircle", "cielo", "Claude", "Pregúntale el partido a un asistente que ve los datos.")]
for i, (icon, tone, t, d) in enumerate(feats):
    x = 6.35 + (i % 2) * 3.24
    y = 1.7 + (i // 2) * 1.5
    box(sl, x, y, 3.06, 1.32, fill=WHITE, line=LINE, radius=0.16, shadow_on=True)
    icon_tile(sl, icon, tone, x + 0.2, y + 0.26, size=0.8)
    text(sl, x + 1.15, y + 0.2, 1.8, 0.35, t, size=16, bold=True, color=CHOCO)
    text(sl, x + 1.15, y + 0.55, 1.8, 0.7, d, size=12.5, color=INK2, line_spacing=0.95)
text(sl, 0.6, 4.95, 6, 0.4, "cómo está armada", size=16, color=CANELA_T, font=HAND)
arq = [("Browser", "cielo", "Tú", "en el navegador"), ("AppWindow", "rosa", "Web", "Next.js · puerto 3100"),
       ("PlugsConnected", "miel", "API", "FastAPI · puerto 8765"), ("CookingPot", "canela", "Motor Cinna", "Python + SQLite"),
       ("CloudArrowDown", "lila", "Fuentes", "ESPN, casas y Kalshi")]
bw, gap = 2.15, 0.345
for i, (icon, tone, t, d) in enumerate(arq):
    x = 0.6 + i * (bw + gap)
    box(sl, x, 5.45, bw, 1.0, fill=WHITE, line=LINE, radius=0.16, shadow_on=True)
    icon_tile(sl, icon, tone, x + 0.13, 5.64, size=0.64)
    text(sl, x + 0.88, 5.58, bw - 0.94, 0.32, t, size=14, bold=True, color=CHOCO)
    text(sl, x + 0.88, 5.9, bw - 0.94, 0.5, d, size=11, color=INK2, line_spacing=0.95)
    if i < len(arq) - 1:
        arrow(sl, x + bw + 0.07, 5.95, x + bw + gap - 0.07, 5.95, color=CANELA, lw=2)
page_number(sl, 2)
notes(sl, "CinnaParleys es local: no depende de servicios de paga. Lee datos gratis de ESPN, de 8 casas y de Kalshi, "
          "simula cada partido 20 mil veces y te dice qué tan probable es cada apuesta. Abajo está cómo se conecta: "
          "tu navegador habla con la web, la web con la API, y la API con el motor que hace los cálculos.")

# ================================================================== 3. TABLA UML
sl = new_slide()
header(sl, "lo que dice el libro", "UML en una tabla: áreas, vistas y diagramas")
rows = [
    ("estructural", "vista estática", "diagrama de clases", "clase, asociación, generalización, dependencia, realización, interfaz", "2", "canela"),
    ("", "vista de casos de uso", "diagrama de casos de uso", "caso de uso, actor, asociación, extensión, inclusión, generalización de casos de uso", "1", "rosa"),
    ("", "vista de implementación", "diagrama de componentes", "componente, interfaz, dependencia, realización", "", None),
    ("", "vista de despliegue", "diagrama de despliegue", "nodo, componente, dependencia, localización", "", None),
    ("dinámica", "vista de máquina de estados", "diagrama de estados", "estado, evento, transición, acción", "Extra", "lila"),
    ("", "vista de actividad", "diagrama de actividad", "estado, actividad, transición de terminación, división, unión", "3", "menta"),
    ("", "vista de interacción", "diagrama de secuencia", "interacción, objeto, mensaje, activación", "4", "cielo"),
    ("", "vista de interacción", "diagrama de colaboración", "colaboración, interacción, rol de colaboración, mensaje", "", None),
    ("gestión del modelo", "vista de gestión del modelo", "diagrama de clases", "paquete, subsistema, modelo", "", None),
]
cols = [1.7, 2.45, 2.45, 4.38, 1.15]
gf = sl.shapes.add_table(len(rows) + 1, len(cols), Inches(0.6), Inches(1.62), Inches(sum(cols)), Inches(0.42 * (len(rows) + 1)))
tbl = gf.table
tblPr = tbl._tbl.tblPr
tblPr.set("bandRow", "0")
tblPr.set("firstRow", "0")
for j, w in enumerate(cols):
    tbl.columns[j].width = Inches(w)


def cell(c, txt, size=12, color=CHOCO, bold=False, fill=WHITE, align=L):
    c.fill.solid()
    c.fill.fore_color.rgb = rgb(fill)
    c.margin_left = c.margin_right = Inches(0.08)
    c.margin_top = c.margin_bottom = Inches(0.03)
    c.vertical_anchor = MID
    tf = c.text_frame
    tf.word_wrap = True
    tf.paragraphs[0].text = ""
    _apply_runs(tf, txt, size, color, bold, BODY, align)


for j, h in enumerate(["Área", "Vista", "Diagrama", "Conceptos principales", "En la app"]):
    cell(tbl.cell(0, j), h, size=13, color=CREAM, bold=True, fill=CHOCO, align=C if j == 4 else L)
for i, (area, vista, diag, conc, uso, tone) in enumerate(rows, start=1):
    bg = TONE[tone][2] if tone else WHITE
    cell(tbl.cell(i, 1), vista, fill=bg)
    cell(tbl.cell(i, 2), diag, fill=bg, bold=bool(tone), color=TONE[tone][0] if tone else CHOCO)
    cell(tbl.cell(i, 3), conc, size=11.5, fill=bg, color=CHOCO if tone else INK2)
    cell(tbl.cell(i, 4), uso, size=14, fill=bg, bold=True, color=TONE[tone][0] if tone else CHOCO, align=C)
for (r0, r1, name) in [(1, 4, "estructural"), (5, 8, "dinámica"), (9, 9, "gestión del modelo")]:
    c0 = tbl.cell(r0, 0)
    if r1 > r0:
        c0.merge(tbl.cell(r1, 0))
    cell(c0, name, size=13, bold=True, fill="F7EDE1", color=CANELA_T)
for i in range(len(rows) + 1):
    tbl.rows[i].height = Inches(0.47)
text(sl, 0.6, 6.85, 12.1, 0.35, "Basado en la tabla de áreas, vistas y diagramas del manual de referencia de UML. "
     "En color: los cinco que usamos para explicar la app.", size=11, color=MUTE)
page_number(sl, 3)
notes(sl, "UML organiza sus diagramas en tres áreas. La estructural describe lo que existe (clases, casos de uso, "
          "componentes, despliegue). La dinámica describe cómo se comporta el sistema en el tiempo (estados, actividad, "
          "interacción). Y la gestión del modelo organiza todo en paquetes. En color están los cinco que elegimos.")

# ================================================================== 4. LOS ELEGIDOS
sl = new_slide()
header(sl, "cuatro + uno de reserva", "Elegimos los más sencillos")
cards = [
    ("1", "UsersThree", "rosa", "Casos de uso", "Estructural · vista de casos de uso", "¿Quién usa la app y para qué?",
     "Armar un parlay, ver videos, preguntarle a Claude."),
    ("2", "TreeStructure", "canela", "Clases", "Estructural · vista estática", "¿Con qué información trabaja?",
     "Partido, Pick, Parlay, Jugador."),
    ("3", "FlowArrow", "menta", "Actividad", "Dinámica · vista de actividad", "¿Qué pasos sigue para calcular?",
     "La actualización de cada hora."),
    ("4", "ArrowsLeftRight", "cielo", "Secuencia", "Dinámica · vista de interacción", "¿Quién le habla a quién?",
     "Pedir el súper parlay."),
    ("Extra", "ArrowsClockwise", "lila", "Estados", "Dinámica · máquina de estados", "¿Cómo cambia algo con el tiempo?",
     "La vida de un partido."),
]
cw, cg = 2.25, 0.22
for i, (num, icon, tone, name, vista, q, ej) in enumerate(cards):
    ink, fill, soft = TONE[tone]
    x = 0.6 + i * (cw + cg)
    extra = num == "Extra"
    box(sl, x, 1.75, cw, 4.95, fill=WHITE, line=ink if extra else LINE, lw=1.5 if extra else 1, dash=extra,
        radius=0.2, shadow_on=not extra)
    box(sl, x, 1.75, cw, 1.45, fill=soft, radius=0.2)
    box(sl, x, 2.9, cw, 0.3, fill=soft, kind=MSO_SHAPE.RECTANGLE)
    icon_tile(sl, icon, tone, x + 0.25, 2.05, size=0.95, bg=WHITE)
    box(sl, x + cw - (1.2 if extra else 0.55), 2.05, 1.0 if extra else 0.38, 0.38, fill=ink, radius=0.19,
        txt=[[("de reserva" if extra else num, {"bold": True, "color": WHITE, "size": 11 if extra else 15})]])
    text(sl, x + 0.25, 3.35, cw - 0.4, 0.45, name, size=21, bold=True, color=CHOCO)
    text(sl, x + 0.25, 3.82, cw - 0.4, 0.55, vista, size=12, color=MUTE, line_spacing=0.95)
    text(sl, x + 0.25, 4.45, cw - 0.4, 0.3, "responde", size=13, color=ink, font=HAND)
    text(sl, x + 0.25, 4.78, cw - 0.4, 0.75, q, size=15, bold=True, color=CHOCO, line_spacing=0.95)
    text(sl, x + 0.25, 5.62, cw - 0.4, 0.95, [[("Ejemplo: ", {"bold": True, "color": ink}), (ej, {})]], size=12.5,
         color=INK2, line_spacing=0.95)
page_number(sl, 4)
notes(sl, "De los nueve diagramas escogimos los más fáciles de leer. Casos de uso y clases explican qué hace la app y "
          "con qué datos; actividad y secuencia explican cómo trabaja por dentro. El de estados lo dejamos de reserva "
          "por si preguntan qué le pasa a un partido desde que se programa hasta que se califica.")

# ================================================================== 5. CASOS DE USO
sl = new_slide()
header(sl, "diagrama 1 · estructural · vista de casos de uso", "Casos de uso: quién usa la app y para qué", "rosa")
canvas(sl, 0.6, 1.65, 8.75, 5.3)
box(sl, 2.3, 1.88, 5.25, 4.88, fill="FFF8F0", line=CANELA, lw=1.25, radius=0.16, name="Sistema")
text(sl, 2.48, 1.95, 3, 0.3, "CinnaParleys", size=14, bold=True, color=CANELA_T)
left = ["Ver semana y pronósticos", "Consultar picks", "Armar un parlay", "Revisar líneas de Draftea",
        "Registrar mi apuesta", "Ver videos y jugadas", "Preguntarle a Claude"]
lx, lw_, lh = 2.5, 2.55, 0.5
lcy = [2.62 + i * 0.6 for i in range(len(left))]
for t, cy in zip(left, lcy):
    box(sl, lx, cy - lh / 2, lw_, lh, fill=TONE["rosa"][2], line=TONE["rosa"][0], lw=1.25, kind=MSO_SHAPE.OVAL,
        txt=t, size=12.5, margin=0.02)
rx, rw, rh = 5.42, 1.98, 0.64
r1 = (rx + rw / 2, 2.62)
r2 = (rx + rw / 2, 4.12)
box(sl, rx, r1[1] - rh / 2, rw, rh, fill=TONE["cielo"][2], line=TONE["cielo"][0], lw=1.25, kind=MSO_SHAPE.OVAL,
    txt="Actualizar datos (cada hora)", size=12, margin=0.02)
box(sl, rx, r2[1] - rh / 2, rw, rh, fill=TONE["menta"][2], line=TONE["menta"][0], lw=1.25, kind=MSO_SHAPE.OVAL,
    txt="Calcular probabilidad real", size=12, margin=0.02)
# «include»
for cy, ly in [(lcy[2], 3.5), (lcy[3], 4.5)]:
    sx, sy = lx + lw_, cy
    ex, ey = ellipse_edge(*r2, rw / 2, rh / 2, sx, sy)
    arrow(sl, sx, sy, ex, ey, dash=True, tail="arrow", lw=1.25)
    text(sl, 5.62, ly, 1.2, 0.26, "«include»", size=11, italic=True, color=TONE["menta"][0])
# actores
bottom = actor(sl, 1.35, 3.62, "Apostador (tú)", label_lines=["Apostador", "(tú)"])
hand = (1.62, 3.62 + 0.3 + 0.13)
for cy in lcy:
    arrow(sl, hand[0] + 0.02, hand[1] + 0.1, lx, cy, tail=None, lw=1.1, color=INK2)
actor(sl, 8.45, 1.98, "Fuentes gratis", label_lines=["Fuentes gratis", "ESPN, casas, Kalshi"])
arrow(sl, rx + rw, r1[1], 8.15, 2.42, tail=None, lw=1.1, color=INK2)
actor(sl, 8.45, 5.08, "Claude")
arrow(sl, lx + lw_, lcy[6], 8.15, 5.55, tail=None, lw=1.1, color=INK2)
side_panel(sl, "rosa", [("Monito:", "actor, alguien de fuera que usa la app."),
                        ("Óvalo:", "caso de uso, algo que se logra."),
                        ("Línea:", "quién participa en cada caso."),
                        ("«include»:", "paso que siempre se reutiliza.")],
           "Tú decides y Cinna calcula: la probabilidad real se reutiliza en los parlays y en tus líneas de Draftea.",
           glyphs=[g_actor, g_oval, g_line, g_dash])
page_number(sl, 5)
notes(sl, "El rectángulo es la app. Afuera están los actores: tú como apostador, las fuentes gratuitas de donde salen "
          "los datos y Claude, el asistente. Cada óvalo es algo que se logra con la app. Armar un parlay y revisar "
          "líneas de Draftea incluyen siempre el mismo paso: calcular la probabilidad real. Por eso va con «include».")

# ================================================================== 6. CLASES
sl = new_slide()
header(sl, "diagrama 2 · estructural · vista estática", "Clases: con qué información trabaja", "canela")
canvas(sl, 0.6, 1.65, 8.75, 5.3)
CW = 2.3
XS = [0.82, 3.85, 6.88]
Y1, Y2 = 1.92, 4.62
HDR, LH = 0.4, 0.255
classes = {
    "Equipo": (0, Y1, ["abreviatura: texto", "nombre: texto", "ranking: número"], ["fuerza()"]),
    "Partido": (1, Y1, ["kickoff: fecha", "estado: pre/en vivo/final", "marcador: texto"], ["simular(20 000)", "calificar()"]),
    "Pick": (2, Y1, ["mercado: texto", "línea: número", "probabilidad: %", "nivel: segura/valor/riesgo"], ["valorEsperado()"]),
    "Jugador": (0, Y2, ["nombre: texto", "posición: QB/RB/WR/TE", "probJugar: %"], ["proyección()"]),
    "Video": (1, Y2, ["título: texto", "duración: segundos", "mp4: enlace"], ["reproducir()"]),
    "Parlay": (2, Y2, ["patas: Pick [2..*]", "probConjunta: %", "pago: x veces"], ["evaluar()"]),
}


def class_h(a, m):
    return HDR + len(a) * LH + 0.1 + len(m) * LH + 0.1


row_h = {Y1: max(class_h(a, m) for (_, y, a, m) in classes.values() if y == Y1),
         Y2: max(class_h(a, m) for (_, y, a, m) in classes.values() if y == Y2)}
geo = {}
for name, (col, y, attrs, meths) in classes.items():
    x = XS[col]
    h = row_h[y]
    geo[name] = (x, y, CW, h)
    box(sl, x, y, CW, h, fill=WHITE, line=CHOCO, lw=1.25, kind=MSO_SHAPE.RECTANGLE, shadow_on=True)
    box(sl, x, y, CW, HDR, fill=TONE["canela"][1], line=CHOCO, lw=1.25, kind=MSO_SHAPE.RECTANGLE,
        txt=[[(name, {"bold": True})]], size=14)
    ya = y + HDR + 0.05
    text(sl, x + 0.1, ya, CW - 0.15, len(attrs) * LH, attrs, size=12, color=CHOCO, line_spacing=0.92)
    ym = y + HDR + len(attrs) * LH + 0.1
    arrow(sl, x, ym, x + CW, ym, tail=None, lw=1.0, color=CHOCO)
    text(sl, x + 0.1, ym + 0.04, CW - 0.15, len(meths) * LH, meths, size=12, color=TONE["canela"][0], line_spacing=0.92)


def lab(x, y, t, w=0.9, align=C, italic=False, size=11.5, color=INK2, bold=False):
    text(sl, x, y, w, 0.24, t, size=size, color=color, align=align, italic=italic, bold=bold)


# Equipo — Partido
yl = Y1 + 0.75
arrow(sl, XS[0] + CW, yl, XS[1], yl, tail=None, lw=1.25)
lab(XS[0] + CW - 0.05, yl - 0.28, "juega", w=0.85, italic=True)
lab(XS[0] + CW + 0.04, yl + 0.04, "2", w=0.3, align=L, bold=True, color=CHOCO)
lab(XS[1] - 0.34, yl + 0.04, "*", w=0.3, align=R, bold=True, color=CHOCO)
# Partido ◆— Pick (composición: rombo relleno del lado de Partido)
arrow(sl, XS[2], yl, XS[1] + CW, yl, tail="diamond", lw=1.25, end="lg")
lab(XS[1] + CW + 0.02, yl - 0.28, "genera", w=0.85, italic=True)
lab(XS[2] - 0.34, yl + 0.04, "*", w=0.3, align=R, bold=True, color=CHOCO)
# Equipo — Jugador
xv = XS[0] + CW / 2
arrow(sl, xv, Y1 + row_h[Y1], xv, Y2, tail=None, lw=1.25)
lab(xv + 0.08, Y1 + row_h[Y1] + 0.18, "tiene", w=0.7, align=L, italic=True)
lab(xv - 0.38, Y1 + row_h[Y1] + 0.02, "1", w=0.3, align=R, bold=True, color=CHOCO)
lab(xv - 0.48, Y2 - 0.27, "1..*", w=0.4, align=R, bold=True, color=CHOCO)
# Partido — Video
xv = XS[1] + CW / 2
arrow(sl, xv, Y1 + row_h[Y1], xv, Y2, tail=None, lw=1.25)
lab(xv + 0.08, Y1 + row_h[Y1] + 0.18, "muestra", w=0.8, align=L, italic=True)
lab(xv - 0.48, Y1 + row_h[Y1] + 0.02, "0..1", w=0.4, align=R, bold=True, color=CHOCO)
lab(xv - 0.38, Y2 - 0.27, "*", w=0.3, align=R, bold=True, color=CHOCO)
# Pick — Parlay (agregación: rombo hueco del lado de Parlay)
xv = XS[2] + CW / 2
arrow(sl, xv, Y1 + row_h[Y1], xv, Y2 - 0.22, tail=None, lw=1.25)
box(sl, xv - 0.1, Y2 - 0.24, 0.2, 0.24, fill=WHITE, line=CHOCO, lw=1.25, kind=MSO_SHAPE.DIAMOND)
lab(xv + 0.08, Y1 + row_h[Y1] + 0.18, "forma", w=0.8, align=L, italic=True)
lab(xv - 0.48, Y1 + row_h[Y1] + 0.02, "2..*", w=0.4, align=R, bold=True, color=CHOCO)
# Video — Jugador
y2l = Y2 + 0.75
arrow(sl, XS[0] + CW, y2l, XS[1], y2l, tail=None, lw=1.25)
lab(XS[0] + CW - 0.05, y2l - 0.28, "etiqueta", w=0.85, italic=True)
lab(XS[0] + CW + 0.04, y2l + 0.04, "*", w=0.3, align=L, bold=True, color=CHOCO)
lab(XS[1] - 0.34, y2l + 0.04, "*", w=0.3, align=R, bold=True, color=CHOCO)
side_panel(sl, "canela", [("Caja:", "clase con su nombre, sus datos y lo que sabe hacer."),
                          ("Rombo relleno:", "composición, los picks viven dentro del partido."),
                          ("Rombo hueco:", "agregación, un parlay junta picks que ya existen."),
                          ("2..*:", "multiplicidad, cuántos hay de cada lado.")],
           "Todo gira alrededor del Partido: de él salen los picks y de los picks se arman los parlays.",
           glyphs=[g_class, g_comp, g_aggr, g_mult])
page_number(sl, 6)
notes(sl, "Cada caja es un tipo de información que maneja la app. Un partido lo juegan dos equipos y genera muchos "
          "picks; el rombo relleno dice que esos picks no existen sin su partido. Un parlay junta dos o más picks; el "
          "rombo hueco dice que esos picks existen por su cuenta. Los videos se etiquetan con jugadores y partidos.")

# ================================================================== 7. ACTIVIDAD
sl = new_slide()
header(sl, "diagrama 3 · dinámica · vista de actividad", "Actividad: cómo se hornea cada actualización", "menta")
canvas(sl, 0.6, 1.65, 12.13, 4.65)
M = TONE["menta"]


def act(x, y, w, h, t, size=13):
    return box(sl, x, y, w, h, fill=M[2], line=M[0], lw=1.25, radius=0.18, txt=t, size=size, margin=0.08)


start_node(sl, 1.0, 2.75)
arrow(sl, 1.14, 2.75, 1.45, 2.75)
act(1.45, 2.4, 2.1, 0.7, "Bajar calendario y marcadores (ESPN)")
bar(sl, 3.9, 1.95, 0.09, 1.61)
arrow(sl, 3.55, 2.75, 3.9, 2.75)
par = [("Líneas de 8 casas", 2.17), ("Lesiones y noticias", 2.755), ("Clima del estadio", 3.34)]
for t, cy in par:
    act(4.3, cy - 0.21, 1.85, 0.42, t, size=12.5)
    arrow(sl, 3.99, cy, 4.3, cy)
    arrow(sl, 6.15, cy, 6.45, cy)
bar(sl, 6.45, 1.95, 0.09, 1.61)
arrow(sl, 6.54, 2.75, 6.85, 2.75)
act(6.85, 2.4, 2.4, 0.7, "Simular 20 000 escenarios por partido")
arrow(sl, 9.25, 2.75, 9.6, 2.75)
act(9.6, 2.4, 2.8, 0.7, "Calcular la probabilidad de cada pick")
dcx, dcy = 11.0, 4.75
arrow(sl, dcx, 3.1, dcx, dcy - 0.4)
diamond(sl, dcx, dcy, 0.8, 0.8)
text(sl, 11.48, 4.42, 1.15, 0.6, "¿valor esperado ≥ 0?", size=12, italic=True, color=CHOCO, line_spacing=0.95)
act(7.1, 4.4, 3.0, 0.7, "Clasificar: Segura · Valor · Arriesgada")
arrow(sl, dcx - 0.4, dcy, 10.1, dcy)
text(sl, 10.18, 4.45, 0.4, 0.26, "[sí]", size=12, bold=True, color=M[0])
act(7.1, 5.45, 3.0, 0.6, "Guardar sin recomendar")
path(sl, [(dcx, dcy + 0.4), (dcx, 5.75), (10.1, 5.75)])
text(sl, 11.08, 5.28, 0.5, 0.26, "[no]", size=12, bold=True, color=M[0])
mcx, mcy = 6.55, 5.25
path(sl, [(7.1, 4.75), (mcx, 4.75), (mcx, mcy - 0.25)])
path(sl, [(7.1, 5.75), (mcx, 5.75), (mcx, mcy + 0.25)])
diamond(sl, mcx, mcy, 0.5, 0.5)
arrow(sl, mcx - 0.25, mcy, 5.85, mcy)
act(2.85, 4.9, 3.0, 0.7, "Mostrar en la app y avisar cambios")
arrow(sl, 2.85, mcy, 2.33, mcy)
end_node(sl, 2.15, mcy)
# leyenda
ly = 6.48
legend = [(lambda x: start_node(sl, x + 0.12, ly + 0.2, 0.22), "inicio"),
          (lambda x: box(sl, x, ly + 0.04, 0.42, 0.32, fill=M[2], line=M[0], lw=1.25, radius=0.08), "acción"),
          (lambda x: diamond(sl, x + 0.2, ly + 0.2, 0.36, 0.36), "decisión / unión de caminos"),
          (lambda x: bar(sl, x + 0.16, ly + 0.02, 0.08, 0.38), "división y unión (en paralelo)"),
          (lambda x: end_node(sl, x + 0.16, ly + 0.2, 0.28), "fin")]
lx0 = 0.7
for (draw, t), w in zip(legend, [0.6, 0.7, 2.25, 2.45, 0.45]):
    draw(lx0)
    text(sl, lx0 + 0.55, ly + 0.07, w, 0.3, t, size=12, color=INK2)
    lx0 += 0.55 + w + 0.35
text(sl, 0.95, 3.95, 3.1, 0.6, "Corre sola cada hora (cada 10 min en día de partido).", size=13, italic=True,
     color=M[0], line_spacing=0.95)
page_number(sl, 7)
notes(sl, "Esto pasa solo, cada hora. Primero baja el calendario y los marcadores. Luego, en paralelo (la barra negra "
          "divide y une caminos), lee las líneas de las casas, las lesiones y noticias, y el clima. Con todo eso simula "
          "20 mil veces cada partido y calcula la probabilidad de cada pick. Si tiene valor, lo clasifica como Segura, "
          "Valor o Arriesgada; si no, lo guarda sin recomendarlo. Al final lo muestra y avisa qué cambió.")

# ================================================================== 8. SECUENCIA
sl = new_slide()
header(sl, "diagrama 4 · dinámica · vista de interacción", "Secuencia: qué pasa cuando pides el súper parlay", "cielo")
canvas(sl, 0.6, 1.65, 12.13, 4.65)
K = TONE["cielo"]
LX = [1.65, 4.1, 6.55, 9.0, 11.45]
heads = [("Tú", "rosa"), ("Web · Next.js", "cielo"), ("API · FastAPI", "miel"), ("Motor Cinna", "canela"), ("Base de datos", "menta")]
for x, (t, tone) in zip(LX, heads):
    box(sl, x - 1.0, 1.85, 2.0, 0.52, fill=TONE[tone][2], line=TONE[tone][0], lw=1.25, radius=0.1,
        txt=[[(t, {"bold": True})]], size=13.5)
    arrow(sl, x, 2.37, x, 6.15, dash=True, tail=None, lw=1.0, color=MUTE)
Y = [2.78, 3.15, 3.52, 3.89, 4.26, 4.6, 5.25, 5.62, 5.99]
AW = 0.08
acts = [(1, Y[0], Y[8]), (2, Y[1], Y[7]), (3, Y[2], Y[6]), (4, Y[3], Y[4])]
for li, a, b in acts:
    box(sl, LX[li] - AW, a, AW * 2, b - a, fill=K[2], line=K[0], lw=1.0, kind=MSO_SHAPE.RECTANGLE)


def msg(i, frm, to, t, ret=False, label_w=2.2):
    y = Y[i]
    d = 1 if to > frm else -1
    x1 = LX[frm] + (d * AW if frm != 0 else 0)
    x2 = LX[to] - (d * AW if to != 0 else 0)
    arrow(sl, x1, y, x2, y, dash=ret, tail="arrow" if ret else "triangle", lw=1.4, color=CHOCO)
    mx = (x1 + x2) / 2
    text(sl, mx - label_w / 2, y - 0.27, label_w, 0.25, t, size=12, color=CHOCO, align=C)


msg(0, 0, 1, "1. abre Parlays")
msg(1, 1, 2, "2. GET /api/super_parlay")
msg(2, 2, 3, "3. build(semáforo)")
msg(3, 3, 4, "4. lee picks y simulaciones")
msg(4, 4, 3, "5. datos", ret=True)
# 6. mensaje a sí mismo
sx = LX[3] + AW
path(sl, [(sx, Y[5]), (sx + 0.45, Y[5]), (sx + 0.45, Y[5] + 0.33), (sx, Y[5] + 0.33)], lw=1.4)
text(sl, sx + 0.55, Y[5] - 0.03, 2.1, 0.45, [[("6. revisa cada pata", {"bold": False})], "rival · Kalshi · salud · clima"],
     size=11.5, color=CHOCO, fill=WHITE, line_spacing=0.9)
msg(6, 3, 2, "7. parlays + semáforo", ret=True)
msg(7, 2, 1, "8. JSON", ret=True)
msg(8, 1, 0, "9. muestra los parlays", ret=True)
ly = 6.48
legend = [(lambda x: arrow(sl, x, ly + 0.2, x + 0.45, ly + 0.2, lw=1.4), "mensaje (llamada)"),
          (lambda x: arrow(sl, x, ly + 0.2, x + 0.45, ly + 0.2, lw=1.4, dash=True, tail="arrow"), "respuesta"),
          (lambda x: box(sl, x + 0.15, ly + 0.02, 0.16, 0.38, fill=K[2], line=K[0], lw=1.0, kind=MSO_SHAPE.RECTANGLE), "activación (está trabajando)"),
          (lambda x: arrow(sl, x + 0.22, ly + 0.0, x + 0.22, ly + 0.42, dash=True, tail=None, lw=1.0, color=MUTE), "línea de vida")]
lx0 = 0.7
for (draw, t), w in zip(legend, [1.45, 0.85, 2.3, 1.1]):
    draw(lx0)
    text(sl, lx0 + 0.6, ly + 0.07, w, 0.3, t, size=12, color=INK2)
    lx0 += 0.6 + w + 0.35
page_number(sl, 8)
notes(sl, "Se lee de arriba hacia abajo, como una conversación. Tú abres Parlays; la web le pide a la API el súper "
          "parlay; la API le pide al motor que lo arme; el motor lee de la base de datos los picks y las simulaciones, "
          "revisa cada pata (rival, Kalshi, salud y clima) y regresa los parlays con su semáforo. Las flechas punteadas "
          "son las respuestas y los rectángulos delgados indican quién está trabajando en cada momento. Todo pasa en tu PC, en menos de un segundo.")

# ================================================================== 9. ESTADOS (reserva)
sl = new_slide()
header(sl, "extra · dinámica · máquina de estados", "Estados: la vida de un partido", "lila")
box(sl, 10.55, 0.82, 2.18, 0.48, fill=TONE["lila"][0], radius=0.24,
    txt=[[("diagrama de reserva", {"bold": True, "color": WHITE})]], size=13)
canvas(sl, 0.6, 1.65, 8.75, 5.3)
V = TONE["lila"]


def state(x, y, name, sub, w=1.75, h=0.82):
    box(sl, x, y, w, h, fill=V[2], line=V[0], lw=1.4, radius=0.2,
        txt=[[(name, {"bold": True, "size": 14})], [(sub, {"size": 11, "color": INK2})]], size=14, margin=0.05)


R1y, R2y = 2.6, 5.2
S1x, S2x, S3x = 1.45, 4.25, 7.1
SW_ = 1.75
SH = 0.82
start_node(sl, 1.0, R1y + SH / 2)
arrow(sl, 1.14, R1y + SH / 2, S1x, R1y + SH / 2)
state(S1x, R1y, "Programado", "aún sin líneas")
state(S2x, R1y, "Analizado", "con picks y parlays")
state(S3x, R1y, "En vivo", "se está jugando")
state(S3x, R2y, "Final", "ya terminó")
state(S2x, R2y, "Calificado", "aciertos guardados")
cy1 = R1y + SH / 2
arrow(sl, S1x + SW_, cy1, S2x, cy1)
text(sl, S1x + SW_ - 0.05, cy1 - 0.3, 1.2, 0.26, "llegan líneas", size=12, italic=True, color=CHOCO, align=C)
arrow(sl, S2x + SW_, cy1, S3x, cy1)
text(sl, S2x + SW_ - 0.05, cy1 - 0.3, 1.2, 0.26, "kickoff", size=12, italic=True, color=CHOCO, align=C)
xm = S3x + SW_ / 2
arrow(sl, xm, R1y + SH, xm, R2y)
text(sl, xm + 0.1, 4.05, 0.9, 0.26, "termina", size=12, italic=True, color=CHOCO)
cy2 = R2y + SH / 2
arrow(sl, S3x, cy2, S2x + SW_, cy2)
text(sl, S2x + SW_ - 0.05, cy2 - 0.3, 1.2, 0.26, "se califica", size=12, italic=True, color=CHOCO, align=C)
arrow(sl, S2x, cy2, 3.35, cy2)
end_node(sl, 3.15, cy2)
# bucles (se repite sin cambiar de estado)
for sx, t in [(S2x, "cada hora / recalcula"), (S3x, "cada 2 min / marcador")]:
    path(sl, [(sx + 0.45, R1y), (sx + 0.45, R1y - 0.4), (sx + 1.3, R1y - 0.4), (sx + 1.3, R1y)], lw=1.4)
    text(sl, sx - 0.15, R1y - 0.7, 2.05, 0.26, t, size=12, italic=True, color=V[0], align=C)
# partido atrasado: Analizado -> Final
arrow(sl, S2x + 1.45, R1y + SH, S3x + 0.3, R2y)
text(sl, 4.0, 4.05, 2.2, 0.55, ["[PC apagada]", "se pone al día solo"], size=12, italic=True, color=V[0], align=R,
     line_spacing=0.95)
side_panel(sl, "lila", [("Caja redondeada:", "estado en el que está el partido."),
                        ("Flecha con texto:", "evento que lo hace cambiar."),
                        ("Flecha que regresa:", "se repite sin cambiar de estado."),
                        ("Inicio y fin:", "el punto negro y el punto con anillo.")],
           "Si un partido terminó con la PC apagada, no se queda atorado: la app lo pone al día y lo califica.",
           glyphs=[g_state, g_arrow, g_loop, g_startend])
page_number(sl, 9)
notes(sl, "Este es el de reserva. Un partido empieza programado; cuando llegan las líneas, Cinna lo analiza y lo "
          "recalcula cada hora. En el kickoff pasa a en vivo y se actualiza cada dos minutos. Al terminar queda final y "
          "luego se califica. La flecha diagonal es un caso real que arreglamos: si la PC estaba apagada cuando terminó, "
          "la siguiente actualización lo pone al día y no se queda como pendiente.")

# ================================================================== 10. CIERRE
sl = new_slide(DARK)
text(sl, 0.75, 0.55, 8, 0.45, "en resumen", size=20, color=CARAMEL, font=HAND)
text(sl, 0.75, 1.0, 9, 0.8, "Cinco preguntas, una app", size=40, bold=True, color=CREAM)
resumen = [("UsersThree", "rosa", "¿Quién la usa y para qué?", "Casos de uso"),
           ("TreeStructure", "canela", "¿Con qué información trabaja?", "Clases"),
           ("FlowArrow", "menta", "¿Qué pasos sigue para calcular?", "Actividad"),
           ("ArrowsLeftRight", "cielo", "¿Quién le habla a quién?", "Secuencia"),
           ("ArrowsClockwise", "lila", "¿Cómo cambia un partido?", "Estados (reserva)")]
for i, (icon, tone, q, d) in enumerate(resumen):
    y = 2.1 + i * 0.92
    box(sl, 0.75, y, 8.1, 0.76, fill=DARK2, radius=0.16)
    icon_tile(sl, icon, tone, 0.9, y + 0.08, size=0.6)
    text(sl, 1.75, y + 0.08, 4.4, 0.6, q, size=17, color=CREAM, anchor=MID)
    box(sl, 6.25, y + 0.16, 2.45, 0.44, fill=TONE[tone][2], radius=0.22,
        txt=[[(d, {"bold": True, "color": TONE[tone][0]})]], size=14)
box(sl, 9.35, 1.75, 3.4, 3.4, fill=DARK2, kind=MSO_SHAPE.OVAL)
picture(sl, "cinna.png", 9.65, 2.0, 2.8)
text(sl, 9.2, 5.35, 3.7, 0.6, "¿Preguntas?", size=30, color=CARAMEL, font=HAND, align=C)
text(sl, 9.2, 6.0, 3.7, 0.4, "CinnaParleys · picks horneados con cariño", size=13, color="A88F80", align=C)
page_number(sl, 10, dark=True)
notes(sl, "En resumen: cada diagrama responde una pregunta distinta sobre la app. Con estos cinco se entiende qué hace, "
          "con qué datos, cómo calcula, cómo se comunican sus partes y cómo cambia un partido con el tiempo.")

prs.core_properties.title = "CinnaParleys explicada con UML"
prs.core_properties.subject = "Diagramas UML de la app CinnaParleys"
prs.save(OUT)
print("guardado:", OUT)
