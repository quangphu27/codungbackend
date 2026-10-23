"""
Rich English PowerPoint builder for Teacher Studio.
Layouts: title, content, two_column, table, cards, closing.
Includes decorative shapes, optional web images, tables, and fade animations.
"""
from __future__ import annotations

import hashlib
import io
import urllib.parse
import urllib.request

# Brand palette
NAVY = (0x0F, 0x27, 0x44)
ORANGE = (0xF3, 0x9C, 0x4A)
TEAL = (0x1A, 0x9B, 0x8E)
SKY = (0xE8, 0xF1, 0xFB)
WHITE = (0xFF, 0xFF, 0xFF)
SOFT = (0xF7, 0xFA, 0xFC)
DARK = (0x1E, 0x29, 0x3B)
MUTED = (0x64, 0x74, 0x8B)


def _parse_hex(value, fallback=NAVY):
    text = str(value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return fallback
    try:
        return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return fallback


def derive_palette(primary="#0F2744", accent="#F39C4A") -> dict:
    navy = _parse_hex(primary, NAVY)
    orange = _parse_hex(accent, ORANGE)
    teal = (
        min(255, int(navy[0] * 0.2 + 26)),
        min(255, int(navy[1] * 0.3 + 140)),
        min(255, int(navy[2] * 0.35 + 120)),
    )
    sky = tuple(min(255, int(c + (255 - c) * 0.86)) for c in navy)
    soft = tuple(min(255, int(c + (255 - c) * 0.93)) for c in navy)
    return {
        "navy": navy,
        "orange": orange,
        "teal": teal,
        "sky": sky,
        "soft": soft,
        "white": WHITE,
        "dark": navy,
        "muted": MUTED,
    }


def P(meta, name):
    pal = (meta or {}).get("palette") or {}
    defaults = {
        "navy": NAVY, "orange": ORANGE, "teal": TEAL, "sky": SKY,
        "soft": SOFT, "white": WHITE, "dark": DARK, "muted": MUTED,
    }
    return pal.get(name, defaults[name])


def _rgb(tup):
    from pptx.dml.color import RGBColor
    return RGBColor(*tup)


def _set_run(run, *, size=18, bold=False, color=DARK, name="Calibri"):
    run.font.size = size
    run.font.bold = bold
    run.font.color.rgb = _rgb(color)
    run.font.name = name


def _fill_shape(shape, color, line=False):
    shape.fill.solid()
    shape.fill.fore_color.rgb = _rgb(color)
    if not line:
        shape.line.fill.background()


def _add_rect(slide, left, top, width, height, color, shape_type=None):
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Emu

    st = shape_type or MSO_SHAPE.RECTANGLE
    shp = slide.shapes.add_shape(st, left, top, width, height)
    _fill_shape(shp, color)
    return shp


def _add_textbox(slide, left, top, width, height, text, *, size=18, bold=False, color=DARK, align=None):
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Pt

    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text or ""
    if align == "center":
        p.alignment = PP_ALIGN.CENTER
    elif align == "right":
        p.alignment = PP_ALIGN.RIGHT
    if p.runs:
        _set_run(p.runs[0], size=Pt(size), bold=bold, color=color)
    else:
        run = p.add_run()
        run.text = text or ""
        _set_run(run, size=Pt(size), bold=bold, color=color)
    return box


def _bullet_font_size(items: list, *, base: int = 18, few: int = 24, many: int = 15) -> int:
    """Larger type when few bullets; slightly smaller when dense."""
    n = len(items or [])
    avg = sum(len(str(x)) for x in (items or [])) / max(n, 1)
    if n <= 3 and avg < 70:
        return few
    if n <= 4 and avg < 55:
        return max(base + 2, 20)
    if n >= 6 or avg > 90:
        return many
    return base


def _add_bullets(slide, left, top, width, height, bullets, *, size=None, color=DARK, per_line=True):
    """Add bullets; when per_line=True each bullet is its own shape (for animations)."""
    from pptx.util import Pt

    items = [str(b).strip() for b in (bullets or []) if str(b).strip()] or ["Key point"]
    size = size or _bullet_font_size(items)
    shapes = []

    if not per_line:
        box = slide.shapes.add_textbox(left, top, width, height)
        tf = box.text_frame
        tf.word_wrap = True
        for i, item in enumerate(items[:8]):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = f"●  {item}"
            p.level = 0
            p.space_after = Pt(12 if size >= 20 else 8)
            if p.runs:
                _set_run(p.runs[0], size=Pt(size), color=color)
        return [box]

    # One textbox per bullet for sequential motion effects
    count = max(len(items[:8]), 1)
    line_h = max(int(height / count), int(0.58 * 914400))
    line_h = min(line_h, int(0.92 * 914400))
    for i, item in enumerate(items[:8]):
        box = _add_textbox(
            slide, left, top + i * line_h, width, line_h,
            f"●  {item}", size=size, color=color,
        )
        shapes.append(box)
    return shapes


def _search_query(keyword: str, topic: str = "", title: str = "") -> str:
    """Build a content-related search phrase (English nouns)."""
    parts = []
    for part in (keyword, title, topic):
        t = " ".join(str(part or "").replace("/", " ").split())
        if t:
            parts.append(t)
    q = " ".join(parts[:2]).strip() or "education classroom"
    # keep short for API search
    return " ".join(q.split()[:6])


def _theme_key(text: str) -> str:
    t = (text or "").lower()
    mapping = [
        (("flag", "ceremony", "anthem", "assembly", "chao", "cờ", "patriot", "salute", "line up"), "flag"),
        (("recycl", "waste", "plastic", "bin", "litter", "garbage", "trash"), "recycle"),
        (("tree", "forest", "plant", "nature", "green", "garden", "earth"), "nature"),
        (("water", "ocean", "river", "sea", "lake"), "water"),
        (("energy", "power", "electric", "solar"), "energy"),
        (("prime", "number", "math", "factor", "sieve"), "book"),
        (("school", "class", "student", "teacher", "lesson", "learn"), "school"),
        (("team", "group", "discuss", "together", "community"), "team"),
        (("book", "read", "vocab", "word", "write"), "book"),
        (("home", "house", "family", "daily"), "home"),
    ]
    for keys, theme in mapping:
        if any(k in t for k in keys):
            return theme
    return "learn"


def _make_themed_illustration(keyword: str, topic: str = "", title: str = "", w: int = 960, h: int = 720) -> bytes:
    """Always-on-topic illustration (Pillow) when stock photo is unavailable."""
    from PIL import Image, ImageDraw, ImageFont

    theme = _theme_key(f"{keyword} {topic} {title}")
    palettes = {
        "flag": ((218, 37, 29), (255, 205, 0), (255, 245, 240)),
        "recycle": ((14, 116, 88), (243, 156, 74), (232, 245, 240)),
        "nature": ((34, 120, 70), (120, 180, 90), (236, 248, 236)),
        "water": ((20, 90, 150), (80, 170, 220), (230, 242, 252)),
        "energy": ((180, 100, 20), (250, 190, 60), (255, 248, 230)),
        "school": ((15, 39, 68), (26, 155, 142), (232, 241, 251)),
        "team": ((26, 155, 142), (243, 156, 74), (240, 250, 248)),
        "book": ((15, 39, 68), (90, 120, 180), (238, 242, 250)),
        "home": ((120, 70, 40), (243, 156, 74), (252, 244, 235)),
        "learn": ((15, 39, 68), (26, 155, 142), (232, 241, 251)),
    }
    c1, c2, bg = palettes.get(theme, palettes["learn"])
    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)

    # soft panels
    draw.rounded_rectangle((40, 40, w - 40, h - 40), radius=36, fill=(255, 255, 255))
    draw.rounded_rectangle((40, 40, w - 40, 120), radius=28, fill=c1)

    cx, cy = w // 2, h // 2 + 20
    if theme == "flag":
        # Flag pole + red flag with yellow star-like diamond
        draw.rectangle((cx - 8, cy - 160, cx + 8, cy + 160), fill=(120, 120, 120))
        draw.polygon([(cx + 8, cy - 150), (cx + 200, cy - 90), (cx + 8, cy - 30)], fill=c1)
        draw.polygon([(cx + 70, cy - 110), (cx + 95, cy - 95), (cx + 80, cy - 70), (cx + 60, cy - 85), (cx + 55, cy - 105)], fill=c2)
        # students as simple figures
        for dx in (-160, -90, 90, 160):
            draw.ellipse((cx + dx - 22, cy + 40, cx + dx + 22, cy + 84), fill=c1)
            draw.rectangle((cx + dx - 28, cy + 84, cx + dx + 28, cy + 150), fill=(15, 39, 68))
    elif theme == "recycle":
        # three arcs as recycle mark
        for i, ang in enumerate((0, 120, 240)):
            bbox = (cx - 140, cy - 140, cx + 140, cy + 140)
            draw.arc(bbox, start=ang + 20, end=ang + 100, fill=c1, width=28)
            # arrow head
            import math
            rad = math.radians(ang + 100)
            ax, ay = cx + 140 * math.cos(rad), cy + 140 * math.sin(rad)
            draw.polygon([(ax, ay), (ax - 28, ay - 10), (ax - 8, ay + 28)], fill=c2)
    elif theme == "nature":
        draw.ellipse((cx - 90, cy - 110, cx + 90, cy + 70), fill=c1)
        draw.rectangle((cx - 18, cy + 40, cx + 18, cy + 160), fill=(100, 70, 40))
        draw.ellipse((cx + 40, cy - 40, cx + 150, cy + 70), fill=c2)
    elif theme == "water":
        for i, yy in enumerate((cy - 40, cy + 20, cy + 80)):
            draw.arc((120, yy, w - 120, yy + 90), start=200, end=340, fill=c1 if i % 2 == 0 else c2, width=16)
        draw.ellipse((cx - 60, cy - 150, cx + 60, cy - 30), fill=c2)
    elif theme == "energy":
        draw.polygon([(cx, cy - 150), (cx + 50, cy - 10), (cx + 10, cy - 10), (cx + 70, cy + 150), (cx - 40, cy + 10), (cx + 5, cy + 10)], fill=c2)
    elif theme == "school":
        draw.polygon([(cx, cy - 130), (cx + 160, cy - 40), (cx - 160, cy - 40)], fill=c2)
        draw.rectangle((cx - 120, cy - 40, cx + 120, cy + 130), fill=c1)
        draw.rectangle((cx - 35, cy + 40, cx + 35, cy + 130), fill=(255, 255, 255))
    elif theme == "book":
        draw.rectangle((cx - 150, cy - 100, cx - 10, cy + 120), fill=c1)
        draw.rectangle((cx + 10, cy - 100, cx + 150, cy + 120), fill=c2)
        draw.line((cx, cy - 100, cx, cy + 120), fill=(255, 255, 255), width=8)
    elif theme == "team":
        for dx in (-110, 0, 110):
            draw.ellipse((cx + dx - 45, cy - 90, cx + dx + 45, cy), fill=c1 if dx else c2)
            draw.ellipse((cx + dx - 70, cy + 10, cx + dx + 70, cy + 150), fill=c1 if dx else c2)
    elif theme == "home":
        draw.polygon([(cx, cy - 140), (cx + 150, cy - 20), (cx - 150, cy - 20)], fill=c2)
        draw.rectangle((cx - 110, cy - 20, cx + 110, cy + 140), fill=c1)
        draw.rectangle((cx - 30, cy + 40, cx + 30, cy + 140), fill=(255, 255, 255))
    else:
        draw.ellipse((cx - 100, cy - 80, cx + 100, cy + 120), fill=c1)
        draw.rounded_rectangle((cx - 70, cy - 20, cx + 70, cy + 90), radius=20, fill=(255, 255, 255))

    label = (_search_query(keyword, topic, title) or theme).title()[:28]
    try:
        font = ImageFont.truetype("arial.ttf", 36)
        small = ImageFont.truetype("arial.ttf", 22)
    except Exception:
        font = ImageFont.load_default()
        small = font
    draw.text((70, 62), label, fill=(255, 255, 255), font=font)
    draw.text((70, h - 70), "Experiential Learning", fill=c1, font=small)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _fetch_wikimedia_image(query: str, w: int = 900) -> bytes | None:
    """Fetch a free Commons image matching the query (content-related)."""
    if not query:
        return None
    api = (
        "https://commons.wikimedia.org/w/api.php?"
        + urllib.parse.urlencode({
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrnamespace": "6",
            "gsrsearch": query,
            "gsrlimit": "8",
            "prop": "imageinfo",
            "iiprop": "url|mime",
            "iiurlwidth": str(w),
        })
    )
    headers = {"User-Agent": "EduBridgeTeacherStudio/1.0 (educational; contact@local)"}
    try:
        req = urllib.request.Request(api, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as res:
            payload = json_loads_safe(res.read().decode("utf-8", "ignore"))
        pages = ((payload or {}).get("query") or {}).get("pages") or {}
        for page in pages.values():
            infos = page.get("imageinfo") or []
            if not infos:
                continue
            info = infos[0]
            mime = (info.get("mime") or "").lower()
            if "image" not in mime or "svg" in mime:
                continue
            url = info.get("thumburl") or info.get("url")
            if not url:
                continue
            req2 = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req2, timeout=12) as res2:
                data = res2.read()
                if data and len(data) > 2000:
                    return data
    except Exception:
        return None
    return None


def json_loads_safe(text: str):
    import json
    try:
        return json.loads(text)
    except Exception:
        return None


def _related_image_bytes(keyword: str, topic: str = "", title: str = "") -> bytes:
    """Prefer Vietnam-related Commons photos matching content; else themed illustration."""
    query = _search_query(keyword, topic, title)
    theme = _theme_key(f"{query} {topic} {title}")
    theme_queries = {
        "flag": "vietnam school flag raising ceremony students red flag yellow star",
        "recycle": "vietnam students recycling plastic bottles",
        "nature": "vietnam school green trees garden",
        "water": "vietnam river clean water",
        "energy": "vietnam solar energy school",
        "school": "vietnamese students classroom school",
        "team": "vietnamese students teamwork school",
        "book": "vietnam classroom chalkboard students",
        "home": "vietnam family home daily life",
        "learn": "vietnamese students school experiential learning",
    }
    vn_theme = theme_queries.get(theme, "vietnamese students school")
    candidates = [
        f"{query} Vietnam",
        f"{query} Việt Nam",
        vn_theme,
        f"Vietnam {query}",
        query,
    ]
    seen = set()
    for q in candidates:
        key = (q or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        img = _fetch_wikimedia_image(q)
        if img:
            return img
    return _make_themed_illustration(keyword, topic, title)


def _add_image_or_art(slide, left, top, width, height, keyword: str, topic: str, title: str = "", meta=None):
    """Place a content-related photo or themed illustration."""
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches

    img = _related_image_bytes(keyword or topic or title, topic, title)
    try:
        stream = io.BytesIO(img)
        slide.shapes.add_picture(stream, left, top, width=width, height=height)
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top + height - Inches(0.12), width, Inches(0.12))
        _fill_shape(bar, P(meta, "orange"))
        return
    except Exception:
        panel = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
        _fill_shape(panel, P(meta, "sky"))
        _add_textbox(
            slide, left + Inches(0.2), top + height / 2 - Inches(0.3), width - Inches(0.4), Inches(0.6),
            (keyword or topic or "Topic")[:28], size=16, bold=True, color=P(meta, "navy"), align="center",
        )


# Effects/transitions known to work in both Microsoft PowerPoint and WPS Office
_EFFECTS = ["fade", "fly(fromLeft)", "fly(fromBottom)", "fade"]
_TRANSITIONS = [
    "<p:fade/>",
    '<p:push dir="l"/>',
    '<p:wipe dir="r"/>',
    '<p:fade/>',
    '<p:push dir="u"/>',
    '<p:wipe dir="d"/>',
]


def _insert_after_csld(sld, element):
    """Keep OOXML order: cSld → clrMapOvr? → transition → timing (WPS/PPT friendly)."""
    from pptx.oxml.ns import qn
    children = list(sld)
    insert_at = len(children)
    for i, child in enumerate(children):
        tag = child.tag
        if tag == qn("p:cSld") or tag.endswith("}cSld"):
            insert_at = i + 1
        elif tag == qn("p:clrMapOvr") or tag.endswith("}clrMapOvr"):
            insert_at = i + 1
    sld.insert(insert_at, element)


def _add_slide_transition(slide, index: int = 0):
    """Slide transition compatible with PowerPoint + WPS."""
    try:
        from pptx.oxml.ns import qn
        from lxml import etree
    except Exception:
        return
    effect = _TRANSITIONS[index % len(_TRANSITIONS)]
    xml = (
        '<p:transition xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        f'spd="med" advClick="1">{effect}</p:transition>'
    )
    try:
        node = etree.fromstring(xml)
        sld = slide._element
        for old in sld.findall(qn("p:timing")):
            # keep timing; remove old transitions only
            pass
        for old in sld.findall(qn("p:transition")):
            sld.remove(old)
        _insert_after_csld(sld, node)
    except Exception:
        pass


def _add_element_animations(slide, shape_ids: list[int], *, click: bool = True):
    """
    Element entrance animations for PowerPoint + WPS.
    Uses standard fade / fly-in only (widely supported).
    First item auto; following items on click (classroom pacing).
    """
    if not shape_ids:
        return
    try:
        from pptx.oxml.ns import qn
        from lxml import etree
    except Exception:
        return

    children = []
    uid = 3
    for i, sid in enumerate(shape_ids[:10]):
        effect = _EFFECTS[i % len(_EFFECTS)]
        # WPS handles clickEffect + withEffect reliably for fade/fly
        if i == 0:
            node_type = "withEffect"
            cond = '<p:cond delay="0"/>'
        elif click:
            node_type = "clickEffect"
            cond = '<p:cond delay="0"/>'
        else:
            node_type = "withEffect"
            cond = f'<p:cond delay="{300 * i}"/>'
        children.append(
            f"""
            <p:par>
              <p:cTn id="{uid}" fill="hold" nodeType="{node_type}">
                <p:stCondLst>{cond}</p:stCondLst>
                <p:childTnLst>
                  <p:animEffect transition="in" filter="{effect}">
                    <p:cBhvr>
                      <p:cTn id="{uid + 100}" dur="650" fill="hold"/>
                      <p:tgtEl><p:spTgt spid="{sid}"/></p:tgtEl>
                    </p:cBhvr>
                  </p:animEffect>
                </p:childTnLst>
              </p:cTn>
            </p:par>
            """
        )
        uid += 1

    timing_xml = f"""
    <p:timing xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
      <p:tnLst>
        <p:par>
          <p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot">
            <p:childTnLst>
              <p:seq concurrent="1" nextAc="seek">
                <p:cTn id="2" dur="indefinite" nodeType="mainSeq">
                  <p:childTnLst>
                    {''.join(children)}
                  </p:childTnLst>
                </p:cTn>
                <p:prevCondLst>
                  <p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond>
                </p:prevCondLst>
                <p:nextCondLst>
                  <p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond>
                </p:nextCondLst>
              </p:seq>
            </p:childTnLst>
          </p:cTn>
        </p:par>
      </p:tnLst>
    </p:timing>
    """
    try:
        timing = etree.fromstring(timing_xml)
        sld = slide._element
        for old in sld.findall(qn("p:timing")):
            sld.remove(old)
        sld.append(timing)
    except Exception:
        pass


def _ids_of(shapes) -> list[int]:
    out = []
    for shape in shapes or []:
        try:
            out.append(shape.shape_id)
        except Exception:
            pass
    return out


def _footer(slide, prs, page: int, total: int, topic: str, meta=None):
    from pptx.util import Inches

    bar = _add_rect(slide, 0, Inches(7.15), prs.slide_width, Inches(0.35), P(meta, "orange"))
    _add_textbox(
        slide, Inches(0.4), Inches(7.18), Inches(9), Inches(0.3),
        f"Hoạt động trải nghiệm  ·  {topic[:50]}",
        size=10, color=P(meta, "white"),
    )
    _add_textbox(
        slide, Inches(11.2), Inches(7.18), Inches(1.8), Inches(0.3),
        f"{page} / {total}",
        size=10, color=P(meta, "white"), align="right",
    )


def _layout_title(slide, prs, data, meta):
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches

    _add_rect(slide, 0, 0, prs.slide_width, prs.slide_height, P(meta, "navy"))
    _add_rect(slide, Inches(8.2), 0, Inches(5.2), prs.slide_height, P(meta, "teal"))
    accent = slide.shapes.add_shape(MSO_SHAPE.RIGHT_TRIANGLE, Inches(7.2), 0, Inches(1.2), prs.slide_height)
    _fill_shape(accent, P(meta, "teal"))
    _add_rect(slide, 0, Inches(6.9), Inches(8.2), Inches(0.6), P(meta, "orange"))

    title = data.get("title") or meta.get("topic") or "Lesson"
    subtitle = data.get("subtitle") or meta.get("subject") or "Hoạt động trải nghiệm"
    title_size = 40 if len(title) < 42 else (32 if len(title) < 70 else 26)
    t1 = _add_textbox(slide, Inches(0.7), Inches(1.7), Inches(6.8), Inches(2.2), title, size=title_size, bold=True, color=P(meta, "white"))
    t2 = _add_textbox(slide, Inches(0.7), Inches(4.1), Inches(6.8), Inches(0.9), subtitle, size=20, color=P(meta, "sky"))
    meta_line = f"{meta.get('grade', '')}  ·  {meta.get('subject', '')}"
    t3 = _add_textbox(slide, Inches(0.7), Inches(5.2), Inches(6.8), Inches(0.5), meta_line, size=15, color=P(meta, "orange"))
    bullets = data.get("bullets") or []
    anim = [t1, t2, t3]
    if bullets:
        anim.extend(_add_bullets(slide, Inches(0.7), Inches(5.7), Inches(6.8), Inches(1.0), bullets[:3], size=14, color=P(meta, "sky")))
    _add_image_or_art(
        slide, Inches(8.6), Inches(1.3), Inches(4.2), Inches(4.5),
        data.get("image_keyword") or meta.get("topic"), meta.get("topic"),
        title=data.get("title") or "",
        meta=meta,
    )
    return anim


def _layout_content(slide, prs, data, meta, page, total):
    from pptx.util import Inches

    _add_rect(slide, 0, 0, prs.slide_width, prs.slide_height, P(meta, "soft"))
    _add_rect(slide, 0, 0, prs.slide_width, Inches(1.15), P(meta, "navy"))
    _add_rect(slide, 0, Inches(1.15), Inches(0.18), Inches(6.0), P(meta, "orange"))
    title_box = _add_textbox(slide, Inches(0.55), Inches(0.28), Inches(8.5), Inches(0.7), data.get("title") or "Content", size=26, bold=True, color=P(meta, "white"))
    bullets = data.get("bullets") or data.get("left_bullets") or []
    fs = _bullet_font_size(bullets, base=19, few=24, many=16)
    bullet_shapes = _add_bullets(slide, Inches(0.6), Inches(1.5), Inches(7.0), Inches(5.2), bullets, size=fs, color=P(meta, "navy"))
    _add_image_or_art(
        slide, Inches(8.0), Inches(1.55), Inches(4.8), Inches(5.0),
        data.get("image_keyword") or meta.get("topic"), meta.get("topic"),
        title=data.get("title") or "",
        meta=meta,
    )
    _footer(slide, prs, page, total, meta.get("topic", ""), meta)
    return [title_box, *bullet_shapes]


def _layout_two_column(slide, prs, data, meta, page, total):
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches

    _add_rect(slide, 0, 0, prs.slide_width, prs.slide_height, P(meta, "soft"))
    _add_rect(slide, 0, 0, prs.slide_width, Inches(1.15), P(meta, "navy"))
    title_box = _add_textbox(slide, Inches(0.55), Inches(0.28), Inches(12), Inches(0.7), data.get("title") or "Compare", size=26, bold=True, color=P(meta, "white"))

    left = data.get("left_bullets") or (data.get("bullets") or [])[:4]
    right = data.get("right_bullets") or (data.get("bullets") or [])[4:8] or left
    c1 = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.5), Inches(1.45), Inches(5.9), Inches(5.3))
    _fill_shape(c1, P(meta, "white"))
    c1.line.color.rgb = _rgb(P(meta, "sky"))
    c2 = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(6.9), Inches(1.45), Inches(5.9), Inches(5.3))
    _fill_shape(c2, P(meta, "white"))
    c2.line.color.rgb = _rgb(P(meta, "sky"))
    _add_rect(slide, Inches(0.5), Inches(1.45), Inches(5.9), Inches(0.15), P(meta, "teal"))
    _add_rect(slide, Inches(6.9), Inches(1.45), Inches(5.9), Inches(0.15), P(meta, "orange"))
    h1 = _add_textbox(slide, Inches(0.75), Inches(1.75), Inches(5.4), Inches(0.4), data.get("left_title") or "Overview", size=17, bold=True, color=P(meta, "teal"))
    h2 = _add_textbox(slide, Inches(7.15), Inches(1.75), Inches(5.4), Inches(0.4), data.get("right_title") or "Practice", size=17, bold=True, color=P(meta, "orange"))
    fs_l = _bullet_font_size(left, base=17, few=21, many=14)
    fs_r = _bullet_font_size(right, base=17, few=21, many=14)
    left_shapes = _add_bullets(slide, Inches(0.75), Inches(2.3), Inches(5.4), Inches(4.1), left, size=fs_l, color=P(meta, "navy"))
    right_shapes = _add_bullets(slide, Inches(7.15), Inches(2.3), Inches(5.4), Inches(4.1), right, size=fs_r, color=P(meta, "navy"))
    _footer(slide, prs, page, total, meta.get("topic", ""), meta)
    return [title_box, h1, *left_shapes, h2, *right_shapes]


def _layout_table(slide, prs, data, meta, page, total):
    from pptx.util import Inches, Pt

    _add_rect(slide, 0, 0, prs.slide_width, prs.slide_height, P(meta, "soft"))
    _add_rect(slide, 0, 0, prs.slide_width, Inches(1.15), P(meta, "navy"))
    title_box = _add_textbox(slide, Inches(0.55), Inches(0.28), Inches(12), Inches(0.7), data.get("title") or "Summary Table", size=26, bold=True, color=P(meta, "white"))

    table_data = data.get("table") or {}
    headers = table_data.get("headers") or ["Item", "Details", "Notes"]
    rows = table_data.get("rows") or []
    if not rows:
        bullets = data.get("bullets") or ["Point A", "Point B", "Point C"]
        rows = [[f"{i+1}", b[:80], "Apply in class"] for i, b in enumerate(bullets[:6])]

    cols = max(len(headers), 2)
    n_rows = 1 + min(len(rows), 7)
    body_size = 15 if n_rows <= 5 else 12
    table_shape = slide.shapes.add_table(n_rows, cols, Inches(0.6), Inches(1.55), Inches(12.1), Inches(5.0)).table

    for c, h in enumerate(headers[:cols]):
        cell = table_shape.cell(0, c)
        cell.text = str(h)
        for p in cell.text_frame.paragraphs:
            for r in p.runs:
                _set_run(r, size=Pt(14), bold=True, color=P(meta, "white"))
        cell.fill.solid()
        cell.fill.fore_color.rgb = _rgb(P(meta, "navy"))

    for r_idx, row in enumerate(rows[: n_rows - 1], start=1):
        for c in range(cols):
            cell = table_shape.cell(r_idx, c)
            val = row[c] if c < len(row) else ""
            cell.text = str(val)
            for p in cell.text_frame.paragraphs:
                for run in p.runs:
                    _set_run(run, size=Pt(body_size), color=P(meta, "navy"))
            cell.fill.solid()
            cell.fill.fore_color.rgb = _rgb(P(meta, "white") if r_idx % 2 else P(meta, "sky"))

    _footer(slide, prs, page, total, meta.get("topic", ""), meta)
    return [title_box]


def _layout_cards(slide, prs, data, meta, page, total):
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches

    _add_rect(slide, 0, 0, prs.slide_width, prs.slide_height, P(meta, "soft"))
    _add_rect(slide, 0, 0, prs.slide_width, Inches(1.15), P(meta, "navy"))
    title_box = _add_textbox(slide, Inches(0.55), Inches(0.28), Inches(12), Inches(0.7), data.get("title") or "Key Ideas", size=26, bold=True, color=P(meta, "white"))

    bullets = data.get("bullets") or ["Idea 1", "Idea 2", "Idea 3"]
    cards_n = min(max(len(bullets), 3), 4)
    # pad if fewer than 3
    while len(bullets) < cards_n:
        bullets.append("Add classroom example")
    colors = [P(meta, "teal"), P(meta, "orange"), P(meta, "navy"), P(meta, "teal")]
    width = Inches(2.9) if cards_n == 4 else Inches(3.8)
    gap = Inches(0.28) if cards_n == 4 else Inches(0.35)
    start = Inches(0.5)
    anim = [title_box]
    text_size = 18 if cards_n <= 3 and max(len(str(b)) for b in bullets[:cards_n]) < 80 else 14
    for i, text in enumerate(bullets[:cards_n]):
        left = start + i * (width + gap)
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, Inches(1.6), width, Inches(4.9))
        _fill_shape(card, P(meta, "white"))
        top = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, Inches(1.6), width, Inches(0.85))
        _fill_shape(top, colors[i % len(colors)])
        num = _add_textbox(slide, left + Inches(0.15), Inches(1.75), width - Inches(0.3), Inches(0.5), f"0{i+1}", size=20, bold=True, color=P(meta, "white"), align="center")
        body = _add_textbox(slide, left + Inches(0.2), Inches(2.7), width - Inches(0.4), Inches(3.4), str(text), size=text_size, bold=True, color=P(meta, "navy"), align="center")
        anim.extend([card, num, body])
    _footer(slide, prs, page, total, meta.get("topic", ""), meta)
    return anim


def _layout_closing(slide, prs, data, meta):
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches

    _add_rect(slide, 0, 0, prs.slide_width, prs.slide_height, P(meta, "navy"))
    circ = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(10.5), Inches(-1.2), Inches(4), Inches(4))
    _fill_shape(circ, P(meta, "teal"))
    circ2 = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(-1.5), Inches(5.2), Inches(3.5), Inches(3.5))
    _fill_shape(circ2, P(meta, "orange"))
    title = data.get("title") or "Cảm ơn"
    title_size = 42 if len(title) < 28 else 32
    t1 = _add_textbox(slide, Inches(1), Inches(2.2), Inches(11), Inches(1.2), title, size=title_size, bold=True, color=P(meta, "white"), align="center")
    bullets = data.get("bullets") or ["Questions welcome", "See you next lesson"]
    t2 = _add_textbox(slide, Inches(1.5), Inches(3.7), Inches(10), Inches(1.6), "\n".join(f"●  {b}" for b in bullets[:4]), size=18, color=P(meta, "sky"), align="center")
    t3 = _add_textbox(slide, Inches(2), Inches(5.6), Inches(9), Inches(0.5), meta.get("topic", ""), size=14, color=P(meta, "orange"), align="center")
    return [t1, t2, t3]


def build_rich_pptx_bytes(deck: dict) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    meta = {
        "grade": deck.get("grade") or "",
        "subject": deck.get("subject") or "Hoạt động trải nghiệm",
        "topic": deck.get("topic") or deck.get("title") or "Lesson",
        "language": deck.get("language") or "vi",
        "palette": derive_palette(deck.get("theme_color"), deck.get("theme_accent")),
    }
    slides = list(deck.get("slides") or [])
    if not slides:
        slides = [{"layout": "title", "title": meta["topic"], "subtitle": meta["subject"], "bullets": []}]

    total = len(slides)
    for idx, raw in enumerate(slides):
        data = dict(raw or {})
        layout = (data.get("layout") or "").lower().strip()
        if not layout:
            if idx == 0:
                layout = "title"
            elif idx == total - 1:
                layout = "closing"
            elif data.get("table"):
                layout = "table"
            elif data.get("left_bullets") or data.get("right_bullets"):
                layout = "two_column"
            elif len(data.get("bullets") or []) <= 4 and idx % 4 == 2:
                layout = "cards"
            else:
                layout = "content"
        data["layout"] = layout

        slide = prs.slides.add_slide(blank)
        page = idx + 1
        anim_shapes = []
        if layout == "title":
            anim_shapes = _layout_title(slide, prs, data, meta) or []
        elif layout == "two_column":
            anim_shapes = _layout_two_column(slide, prs, data, meta, page, total) or []
        elif layout == "table":
            anim_shapes = _layout_table(slide, prs, data, meta, page, total) or []
        elif layout == "cards":
            anim_shapes = _layout_cards(slide, prs, data, meta, page, total) or []
        elif layout == "closing":
            anim_shapes = _layout_closing(slide, prs, data, meta) or []
        else:
            anim_shapes = _layout_content(slide, prs, data, meta, page, total) or []

        notes = data.get("notes") or ""
        if notes:
            slide.notes_slide.notes_text_frame.text = str(notes)

        _add_slide_transition(slide, idx)
        _add_element_animations(slide, _ids_of(anim_shapes), click=True)

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
