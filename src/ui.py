"""Presentation layer: a clean, professional design system.

Pure rendering helpers — no business logic. Everything injects standard CSS via
``st.markdown`` so it works on a stock Streamlit install with no extra packages.

The visual language is deliberately understated: a light content canvas, a dark
slate navigation rail, a single indigo accent, generous whitespace and hairline
borders — the look of a modern, premium SaaS dashboard.
"""

from __future__ import annotations

from typing import Iterable, Sequence, Tuple

import streamlit as st

# Brand palette -------------------------------------------------------------
INK = "#0f172a"      # primary text / headings
BODY = "#334155"     # body copy
MUTED = "#64748b"    # secondary text
LINE = "#e7e9ef"     # hairline borders
ACCENT = "#4f46e5"   # single brand accent (indigo)
CANVAS = "#f7f8fa"   # app background

# Semantic tones for KPI tiles and pills: (background, text, accent-bar).
TONES = {
    "indigo": ("#eef2ff", "#4338ca", "#4f46e5"),
    "green":  ("#ecfdf5", "#047857", "#10b981"),
    "amber":  ("#fffbeb", "#b45309", "#f59e0b"),
    "red":    ("#fef2f2", "#b91c1c", "#ef4444"),
    "blue":   ("#eff6ff", "#1d4ed8", "#3b82f6"),
    "slate":  ("#f1f5f9", "#475569", "#94a3b8"),
}

PRIORITY_EMOJI = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🟢",
    "none": "⚪",
}

_PRIORITY_TONE = {
    "critical": "red", "high": "amber", "medium": "blue", "low": "green", "none": "slate",
}


def inject_theme() -> None:
    """Inject the global stylesheet. Idempotent — safe to call every render."""
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"], .stApp, input, textarea, button, select {
  font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
}
.stApp { background:#f7f8fa; }

/* Comfortable, centred content column — premium apps are not edge-to-edge */
.block-container { padding-top:2.4rem; padding-bottom:4rem; max-width:1180px; }

h1,h2,h3,h4 { color:#0f172a; font-weight:700; letter-spacing:-.021em; }

/* Quieten Streamlit chrome (keep header present so the sidebar toggle works) */
header[data-testid="stHeader"] { background:transparent; }
#MainMenu, [data-testid="stToolbar"] [data-testid="stDeployButton"] { display:none; }
footer { visibility:hidden; }

/* ---------------- Sidebar (dark navigation rail, Shopify/Linear style) ---------------- */
section[data-testid="stSidebar"] { background:#0f172a; border-right:1px solid #0b1220; }
section[data-testid="stSidebar"] * { color:#cbd5e1; }
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] strong { color:#ffffff; }
section[data-testid="stSidebar"] .block-container { padding-top:1.2rem; padding-bottom:1rem; }

.rrd-brand { font-weight:800; font-size:1.02rem; color:#ffffff; letter-spacing:-.01em;
  display:flex; align-items:center; gap:.55rem; margin:.1rem 0 .15rem; padding:0 .3rem; }
.rrd-brand .dot { width:9px; height:9px; border-radius:50%;
  background:linear-gradient(135deg,#818cf8,#4f46e5); box-shadow:0 0 0 4px rgba(79,70,229,.18); }

.rrd-side-workspace {
  font-size:.78rem; color:#94a3b8; padding:0 .3rem; margin:.1rem 0 .9rem;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }

.rrd-nav-group {
  font-size:.66rem; font-weight:700; letter-spacing:.1em; text-transform:uppercase;
  color:#64748b; padding:0 .55rem; margin:.95rem 0 .25rem; }

.rrd-side-bottom { margin-top:1.1rem; padding-top:.8rem; border-top:1px solid #1e293b; }

/* Sidebar buttons: flat, transparent nav items; active state = solid indigo */
section[data-testid="stSidebar"] .stButton>button {
  background:transparent !important; border:none !important; color:#cbd5e1 !important;
  text-align:left !important; padding:.42rem .65rem !important; border-radius:8px !important;
  font-weight:500 !important; font-size:.92rem !important; box-shadow:none !important;
  justify-content:flex-start !important; min-height:auto !important;
  transition:background .12s ease, color .12s ease; }
section[data-testid="stSidebar"] .stButton>button:hover {
  background:#1e293b !important; color:#ffffff !important; border:none !important; }
section[data-testid="stSidebar"] button[kind="primary"] {
  background:#4f46e5 !important; color:#ffffff !important; border:none !important;
  box-shadow:0 1px 2px rgba(79,70,229,.35) !important; }
section[data-testid="stSidebar"] button[kind="primary"]:hover {
  background:#4338ca !important; color:#ffffff !important; }
section[data-testid="stSidebar"] button[kind="primary"] * { color:#ffffff !important; }

/* Sidebar metric: plain, no card */
section[data-testid="stSidebar"] [data-testid="stMetric"] { background:transparent; border:none; padding:0 .25rem; }
section[data-testid="stSidebar"] [data-testid="stMetricValue"] { color:#ffffff; font-size:1.25rem; }
section[data-testid="stSidebar"] [data-testid="stMetricLabel"] { font-size:.72rem; color:#94a3b8; }

/* ---------------- Buttons (flat, premium) ---------------- */
.stButton>button, .stDownloadButton>button, .stFormSubmitButton>button {
  border-radius:9px; font-weight:600; border:1px solid #e2e5ec; background:#ffffff; color:#0f172a;
  padding:.5rem 1.05rem; box-shadow:0 1px 2px rgba(16,24,40,.05); transition:.12s ease; }
.stButton>button:hover, .stDownloadButton>button:hover, .stFormSubmitButton>button:hover {
  border-color:#cdd3df; background:#fbfbfe; }
button[kind="primary"], button[kind="primaryFormSubmit"] {
  background:#4f46e5 !important; border-color:#4f46e5 !important; color:#ffffff !important;
  box-shadow:0 1px 2px rgba(79,70,229,.25); }
button[kind="primary"] *, button[kind="primaryFormSubmit"] * { color:#ffffff !important; }
button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover {
  background:#4338ca !important; border-color:#4338ca !important; }

/* ---------------- Inputs (every field gets a clear, clickable border) ---------------- */
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"]>div,
[data-baseweb="base-input"], [data-testid="stNumberInput"] [data-baseweb="input"],
[data-testid="stDateInput"] [data-baseweb="input"], [data-testid="stTimeInput"] [data-baseweb="input"] {
  border:1.5px solid #cdd3df !important; border-radius:8px !important;
  background:#ffffff !important; box-shadow:0 1px 2px rgba(16,24,40,.04) !important;
  transition:border-color .12s ease, box-shadow .12s ease; }

[data-baseweb="input"]:hover, [data-baseweb="textarea"]:hover, [data-baseweb="select"]>div:hover {
  border-color:#aab2c5 !important; }

/* Focus state: brand-accent ring so the active field is unmistakable */
[data-baseweb="input"]:has(input:focus), [data-baseweb="textarea"]:has(textarea:focus),
[data-baseweb="select"]>div:has(input:focus) {
  border-color:#4f46e5 !important; box-shadow:0 0 0 3px rgba(79,70,229,.14) !important; }

/* Remove the default inner border so the outer wrapper's border is the only one shown */
input, textarea, [data-baseweb="select"] input { border:none !important; box-shadow:none !important; background:transparent !important; }

/* Multiselect, file uploader and the data editor grid also need a visible boundary */
[data-testid="stMultiSelect"] [data-baseweb="select"]>div {
  border:1.5px solid #cdd3df !important; border-radius:8px !important; }
[data-testid="stFileUploaderDropzone"] {
  border:1.5px dashed #cdd3df !important; border-radius:10px !important; background:#fbfbfe !important; }
[data-testid="stDataFrame"], [data-testid="stDataEditor"] {
  border:1.5px solid #cdd3df !important; border-radius:10px !important; overflow:hidden; }

/* ---------------- Native metric → card (main area only) ---------------- */
[data-testid="stMetric"] { background:#ffffff; border:1px solid #e7e9ef; border-radius:14px;
  padding:14px 16px; box-shadow:0 1px 2px rgba(16,24,40,.04); }
[data-testid="stMetricValue"] { font-weight:700; color:#0f172a; }
[data-testid="stMetricLabel"] { color:#64748b; }

/* ---------------- Expanders as cards ---------------- */
[data-testid="stExpander"] details { border:1px solid #e7e9ef !important; border-radius:12px !important;
  background:#ffffff; box-shadow:0 1px 2px rgba(16,24,40,.03); }
[data-testid="stExpander"] summary { font-weight:600; color:#0f172a; }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius:14px; }

/* ---------------- Tabs ---------------- */
.stTabs [data-baseweb="tab"] { font-weight:600; color:#64748b; }
.stTabs [aria-selected="true"] { color:#4f46e5 !important; }
.stTabs [data-baseweb="tab-highlight"] { background:#4f46e5; }

/* ---------------- Alerts (softer) ---------------- */
[data-testid="stAlert"] { border-radius:12px; border:1px solid #e7e9ef; }

/* ================= Custom components ================= */
.rrd-head { margin:0 0 .2rem; }
.rrd-head h1 { font-size:1.7rem; margin:0; display:flex; align-items:center; gap:.55rem; line-height:1.2; }
.rrd-head .ic { font-size:1.45rem; }
.rrd-head p { color:#64748b; margin:.4rem 0 0; font-size:.96rem; max-width:760px; }
.rrd-rule { height:1px; background:#e7e9ef; border:0; margin:1.1rem 0 1.5rem; }

.rrd-sec { font-size:.74rem; font-weight:700; letter-spacing:.07em; text-transform:uppercase;
  color:#94a3b8; margin:1.6rem 0 .7rem; }
.rrd-sec .cap { text-transform:none; letter-spacing:0; font-weight:500; color:#94a3b8; margin-left:.5rem; }

.rrd-kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(176px,1fr)); gap:14px; }
.rrd-kpi { background:#ffffff; border:1px solid #e7e9ef; border-radius:14px; padding:16px 18px;
  box-shadow:0 1px 2px rgba(16,24,40,.04); position:relative; overflow:hidden; }
.rrd-kpi::before { content:""; position:absolute; left:0; top:0; bottom:0; width:3px; background:var(--bar); }
.rrd-kpi .lab { font-size:.72rem; font-weight:600; letter-spacing:.04em; text-transform:uppercase; color:#94a3b8; }
.rrd-kpi .val { font-size:1.55rem; font-weight:800; color:#0f172a; margin-top:7px; line-height:1.05; }
.rrd-kpi .sub { font-size:.79rem; color:#64748b; margin-top:5px; }

.rrd-pill { display:inline-flex; align-items:center; gap:6px; padding:3px 11px; border-radius:999px;
  font-size:.73rem; font-weight:700; letter-spacing:.01em; }
.rrd-pill .dot { width:7px; height:7px; border-radius:50%; }

.rrd-empty { background:#ffffff; border:1px dashed #d6dae3; border-radius:16px; padding:40px 28px;
  text-align:center; margin:.4rem 0 1rem; }
.rrd-empty .ic { font-size:2rem; }
.rrd-empty h3 { margin:.6rem 0 .3rem; font-size:1.12rem; color:#0f172a; }
.rrd-empty p { color:#64748b; margin:0 auto; max-width:460px; font-size:.92rem; line-height:1.5; }

.rrd-check { display:flex; align-items:center; gap:11px; padding:9px 12px; border:1px solid #e7e9ef;
  border-radius:11px; background:#ffffff; margin:7px 0; }
.rrd-check .mk { width:22px; height:22px; border-radius:50%; display:grid; place-items:center;
  font-size:.78rem; font-weight:800; flex:0 0 auto; }
.rrd-check .mk.on { background:#10b981; color:#ffffff; }
.rrd-check .mk.off { background:#eef0f4; color:#94a3b8; border:1px solid #e2e5ec; }
.rrd-check .lb { font-weight:600; color:#334155; font-size:.92rem; }
.rrd-check.done .lb { color:#94a3b8; }

.rrd-auth { text-align:center; margin:2.4rem 0 1.2rem; }
.rrd-auth .brand { font-weight:800; font-size:1.7rem; color:#0f172a; letter-spacing:-.02em; }
.rrd-auth .tag { color:#64748b; font-size:.95rem; margin-top:.4rem; }
</style>
        """,
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str = "", icon: str = "") -> None:
    """Clean page title block with an optional one-line subtitle and hairline."""
    ic = f'<span class="ic">{icon}</span>' if icon else ""
    sub = f"<p>{subtitle}</p>" if subtitle else ""
    st.markdown(
        f'<div class="rrd-head"><h1>{ic}{title}</h1>{sub}</div><hr class="rrd-rule"/>',
        unsafe_allow_html=True,
    )


def section(title: str, caption: str = "") -> None:
    """Small uppercase section label."""
    cap = f'<span class="cap">{caption}</span>' if caption else ""
    st.markdown(f'<div class="rrd-sec">{title}{cap}</div>', unsafe_allow_html=True)


def kpi_cards(cards: Sequence[dict]) -> None:
    """Render KPI tiles. Each card: {label, value, sub?, accent?}."""
    html = ['<div class="rrd-kpis">']
    for c in cards:
        _, _, bar = TONES.get(c.get("accent", "slate"), TONES["slate"])
        sub = f'<div class="sub">{c["sub"]}</div>' if c.get("sub") else ""
        html.append(
            f'<div class="rrd-kpi" style="--bar:{bar}">'
            f'<div class="lab">{c["label"]}</div>'
            f'<div class="val">{c["value"]}</div>{sub}</div>'
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def status_pill(label: str, tone: str = "slate") -> str:
    """Return HTML for an inline status pill."""
    bg, fg, bar = TONES.get(tone, TONES["slate"])
    return (f'<span class="rrd-pill" style="background:{bg};color:{fg}">'
            f'<span class="dot" style="background:{bar}"></span>{label}</span>')


def priority_chip(priority: str) -> str:
    """Return HTML for a priority pill (kept for the Approval Queue)."""
    tone = _PRIORITY_TONE.get(priority, "slate")
    return status_pill(priority.upper(), tone)


def empty_state(title: str, body: str = "", icon: str = "📂") -> None:
    """Premium empty/onboarding state."""
    st.markdown(
        f'<div class="rrd-empty"><div class="ic">{icon}</div>'
        f'<h3>{title}</h3><p>{body}</p></div>',
        unsafe_allow_html=True,
    )


def checklist(items: Iterable[Tuple[str, bool]]) -> None:
    """Render a getting-started checklist. Each item = (label, done)."""
    rows = []
    for label, done in items:
        mk = '<span class="mk on">✓</span>' if done else '<span class="mk off"></span>'
        cls = "rrd-check done" if done else "rrd-check"
        rows.append(f'<div class="{cls}">{mk}<span class="lb">{label}</span></div>')
    st.markdown("".join(rows), unsafe_allow_html=True)
