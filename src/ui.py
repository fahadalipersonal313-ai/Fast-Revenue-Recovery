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
ACCENT = "#ea580c"   # single brand accent (indigo)
CANVAS = "#f7f8fa"   # app background

# Semantic tones for KPI tiles and pills: (background, text, accent-bar).
TONES = {
    "indigo": ("#fff7ed", "#c2410c", "#ea580c"),
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
  background:linear-gradient(135deg,#fb923c,#ea580c); box-shadow:0 0 0 4px rgba(79,70,229,.18); }

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
  background:#ea580c !important; color:#ffffff !important; border:none !important;
  box-shadow:0 1px 2px rgba(79,70,229,.35) !important; }
section[data-testid="stSidebar"] button[kind="primary"]:hover {
  background:#c2410c !important; color:#ffffff !important; }
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
  background:#ea580c !important; border-color:#ea580c !important; color:#ffffff !important;
  box-shadow:0 1px 2px rgba(79,70,229,.25); }
button[kind="primary"] *, button[kind="primaryFormSubmit"] * { color:#ffffff !important; }
button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover {
  background:#c2410c !important; border-color:#c2410c !important; }

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
  border-color:#ea580c !important; box-shadow:0 0 0 3px rgba(79,70,229,.14) !important; }

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
.stTabs [aria-selected="true"] { color:#ea580c !important; }
.stTabs [data-baseweb="tab-highlight"] { background:#ea580c; }

/* ---------------- Alerts (softer) ---------------- */
[data-testid="stAlert"] { border-radius:12px; border:1px solid #e7e9ef; }

/* ================= Premium polish — applies everywhere ================= */
/* Entrance fade-up for top-level content blocks */
@keyframes rrd-in { from { opacity:0; transform:translateY(8px); }
                   to   { opacity:1; transform:translateY(0); } }
[data-testid="stMain"] [data-testid="stVerticalBlock"] > [data-testid="stMarkdownContainer"],
[data-testid="stMain"] [data-testid="stMetric"],
[data-testid="stMain"] [data-testid="stDataFrame"],
[data-testid="stMain"] [data-testid="stExpander"],
[data-testid="stMain"] [data-testid="stTabs"],
[data-testid="stMain"] [data-testid="stAlert"] {
  animation: rrd-in .35s ease both; }

/* Premium tabs: pill-style active state with gradient underline */
.stTabs [data-baseweb="tab-list"] { gap:6px; border-bottom:1px solid #e7e9ef; padding-bottom:0; }
.stTabs [data-baseweb="tab"] {
  border-radius:10px 10px 0 0 !important; padding:.55rem 1.05rem !important;
  font-weight:600; color:#64748b; transition:color .15s ease, background .15s ease; }
.stTabs [data-baseweb="tab"]:hover { color:#0f172a; background:rgba(79,70,229,.04); }
.stTabs [aria-selected="true"] {
  color:#ea580c !important; background:linear-gradient(180deg, rgba(79,70,229,.08), rgba(79,70,229,0));
}
.stTabs [data-baseweb="tab-highlight"] {
  background:linear-gradient(90deg,#ea580c,#f97316) !important; height:3px !important;
  border-radius:3px 3px 0 0; }

/* KPI cards: hover-lift depth */
[data-testid="stMain"] [data-testid="stMetric"] {
  transition:transform .2s ease, box-shadow .2s ease; }
[data-testid="stMain"] [data-testid="stMetric"]:hover {
  transform:translateY(-2px);
  box-shadow:0 14px 24px -10px rgba(15,23,42,.14), 0 4px 8px rgba(16,24,40,.04); }

/* DataFrames / tables: rounded edges, subtle hairline */
[data-testid="stDataFrame"], [data-testid="stDataEditor"] {
  border-radius:12px !important; overflow:hidden;
  box-shadow:0 1px 3px rgba(16,24,40,.05); }

/* Expanders: lift on hover */
[data-testid="stExpander"] details { transition:box-shadow .2s ease; }
[data-testid="stExpander"] details:hover { box-shadow:0 8px 18px -10px rgba(15,23,42,.18); }

/* Inline "go to page" link buttons rendered via st.button — distinguished
   from primary CTA buttons by the .rrd-link-wrap parent. */
.rrd-link-wrap .stButton>button {
  background:linear-gradient(180deg, #fff7ed 0%, #ffedd5 100%) !important;
  border:1px solid #fed7aa !important; color:#c2410c !important;
  font-weight:700 !important; box-shadow:0 1px 2px rgba(79,70,229,.10) !important; }
.rrd-link-wrap .stButton>button:hover {
  background:linear-gradient(180deg, #ffedd5 0%, #fed7aa 100%) !important;
  border-color:#fdba74 !important; transform:translateY(-1px); }

/* ================= Custom components ================= */
.rrd-head { margin:0 0 .2rem; position:relative; padding-left:18px; }
.rrd-head::before {
  content:""; position:absolute; left:0; top:5px; bottom:30px; width:4px; border-radius:4px;
  background:linear-gradient(180deg,#ea580c,#ec4899); }
.rrd-head h1 { font-size:1.85rem; margin:0; display:flex; align-items:center; gap:.55rem; line-height:1.15;
  letter-spacing:-.022em;
  background:linear-gradient(135deg,#0f172a 30%, #ea580c 130%);
  -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent; }
.rrd-head .ic { font-size:1.55rem; -webkit-text-fill-color:initial; }
.rrd-head p { color:#64748b; margin:.5rem 0 0; font-size:.97rem; max-width:760px; line-height:1.55; }
.rrd-rule { height:1px; background:linear-gradient(90deg,#e7e9ef,transparent);
  border:0; margin:1.1rem 0 1.5rem; }

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


def link_button(label: str, page_label: str, *, key: str,
                use_container_width: bool = False) -> bool:
    """Premium inline "go to page" button — distinct visual treatment from
    primary CTAs (soft lavender gradient, indigo text). Caller is responsible
    for handling the click → ``_goto(page_label)`` since that lives in app.py
    and we don't want a UI module importing from app. Returns ``True`` when
    clicked.

    Usage in a page::

        if ui.link_button("Open Invoices", "🧾 Invoices", key="...") :
            _goto("🧾 Invoices")
    """
    st.markdown("<div class='rrd-link-wrap'>", unsafe_allow_html=True)
    clicked = st.button(f"➜  {label}", key=key,
                        use_container_width=use_container_width)
    st.markdown("</div>", unsafe_allow_html=True)
    return clicked


def welcome_styles() -> None:
    """Premium onboarding styles — gradient hero with animated orbs, glass
    pipeline cards with depth and hover lift, big rounded buttons. Scoped
    via the .rrd-hero / .rrd-pipe* / .rrd-wsec / .rrd-ai-* class families
    so it doesn't leak into the rest of the app."""
    st.markdown(
        """
<style>
/* ===================== Hero ===================== */
.rrd-hero {
  position:relative; overflow:hidden; border-radius:28px;
  padding:60px 56px 70px; margin:-.3rem 0 2.6rem;
  background:
    radial-gradient(1100px 380px at 12% -10%, rgba(129,140,248,.30), transparent 60%),
    radial-gradient(900px 340px at 92% 10%, rgba(236,72,153,.20), transparent 60%),
    linear-gradient(135deg, #7c2d12 0%, #ea580c 50%, #f59e0b 100%);
  color:#ffffff; box-shadow:0 30px 60px -22px rgba(15,23,42,.45),
                            0 8px 22px -8px rgba(79,70,229,.35);
}
.rrd-hero-inner { position:relative; z-index:2; max-width:780px; }
.rrd-hero-eyebrow {
  display:inline-block; font-size:.74rem; font-weight:700; letter-spacing:.18em;
  text-transform:uppercase; color:#fdba74; padding:6px 14px; border-radius:999px;
  background:rgba(129,140,248,.16); border:1px solid rgba(165,180,252,.30);
  margin-bottom:1.1rem; animation:rrd-fade-up .55s ease both; }
.rrd-hero-title {
  font-size:3.05rem; line-height:1.08; font-weight:800; letter-spacing:-.025em;
  margin:0 0 1.05rem; color:#ffffff;
  background:linear-gradient(135deg,#ffffff 30%,#fed7aa 100%);
  -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent;
  animation:rrd-fade-up .65s .05s ease both; }
.rrd-hero-sub {
  font-size:1.08rem; line-height:1.6; color:#cbd5e1; max-width:680px; margin:0;
  animation:rrd-fade-up .75s .1s ease both; }
.rrd-hero-sub strong { color:#ffffff; }

/* Floating gradient orbs for depth */
.rrd-hero-orb { position:absolute; border-radius:50%; filter:blur(50px); opacity:.55;
  pointer-events:none; z-index:1; }
.rrd-orb-1 { width:260px; height:260px; top:-70px; right:8%;
  background:radial-gradient(circle, #fb923c 0%, transparent 70%);
  animation:rrd-float-a 9s ease-in-out infinite; }
.rrd-orb-2 { width:180px; height:180px; bottom:-40px; right:24%;
  background:radial-gradient(circle, #ec4899 0%, transparent 70%);
  animation:rrd-float-b 11s ease-in-out infinite; }
.rrd-orb-3 { width:120px; height:120px; top:35%; right:2%;
  background:radial-gradient(circle, #22d3ee 0%, transparent 70%);
  animation:rrd-float-a 13s ease-in-out infinite reverse; }

@keyframes rrd-float-a { 0%,100%{transform:translate(0,0)} 50%{transform:translate(-20px,18px)} }
@keyframes rrd-float-b { 0%,100%{transform:translate(0,0)} 50%{transform:translate(22px,-14px)} }
@keyframes rrd-fade-up { from{opacity:0;transform:translateY(14px)} to{opacity:1;transform:translateY(0)} }

/* ===================== Section header ===================== */
.rrd-wsec { display:flex; align-items:center; gap:18px; margin:2.6rem 0 1.4rem; flex-wrap:wrap; }
.rrd-wsec-num {
  width:46px; height:46px; border-radius:14px; display:grid; place-items:center;
  font-weight:800; font-size:1.25rem;
  background:linear-gradient(135deg,#ea580c,#f97316); color:#ffffff;
  box-shadow:0 10px 22px -8px rgba(79,70,229,.55), inset 0 1px 0 rgba(255,255,255,.25); }
.rrd-wsec-head { font-size:1.6rem; font-weight:800; color:#0f172a; letter-spacing:-.018em;
  line-height:1.1; }
.rrd-wsec-sub { color:#64748b; font-size:.97rem; flex-basis:100%; padding-left:64px;
  margin-top:-6px; }

/* ===================== Pipeline cards (3D-ish glass) ===================== */
.rrd-pipes { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
  gap:22px; margin:.6rem 0 1.2rem; perspective:1200px; }
.rrd-pipe {
  position:relative; background:#ffffff; border-radius:22px; padding:28px 26px 24px;
  border:1px solid #e7e9ef; overflow:hidden;
  box-shadow:0 30px 50px -28px rgba(15,23,42,.30),
             0 10px 22px -12px rgba(79,70,229,.18),
             inset 0 1px 0 #ffffff;
  transform-style:preserve-3d; transition:transform .35s cubic-bezier(.22,1,.36,1),
                                          box-shadow .35s ease;
  animation:rrd-fade-up .6s ease both; }
.rrd-pipe:hover {
  transform:translateY(-8px) rotateX(2deg);
  box-shadow:0 50px 80px -32px rgba(15,23,42,.40),
             0 18px 40px -16px rgba(79,70,229,.32); }
.rrd-pipe::before {
  content:""; position:absolute; inset:0 0 auto 0; height:5px;
  background:linear-gradient(90deg, var(--c1, #ea580c), var(--c2, #f97316)); }
.rrd-pipe-1 { --c1:#ea580c; --c2:#f97316; }
.rrd-pipe-2 { --c1:#06b6d4; --c2:#3b82f6; }
.rrd-pipe-3 { --c1:#ec4899; --c2:#f59e0b; }

.rrd-pipe-glyph {
  font-size:2.2rem; width:64px; height:64px; border-radius:18px; display:grid; place-items:center;
  background:linear-gradient(135deg, var(--c1) 0%, var(--c2) 100%);
  box-shadow:0 14px 28px -10px color-mix(in srgb, var(--c1) 60%, transparent),
             inset 0 1px 0 rgba(255,255,255,.30);
  margin-bottom:1.1rem; }
.rrd-pipe-step {
  font-size:.72rem; font-weight:700; letter-spacing:.12em; text-transform:uppercase;
  color:#94a3b8; margin-bottom:.4rem; }
.rrd-pipe h3 { font-size:1.2rem; font-weight:800; color:#0f172a; margin:0 0 .55rem;
  letter-spacing:-.015em; }
.rrd-pipe p { color:#475569; font-size:.94rem; line-height:1.55; margin:0 0 1.05rem; }
.rrd-pipe-tag {
  display:inline-block; font-size:.74rem; font-weight:600;
  color:#c2410c; background:#fff7ed; padding:5px 11px; border-radius:999px;
  border:1px solid #fed7aa; }

/* ===================== Status row (email/AI on/off) ===================== */
.rrd-status-row { display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin:-.4rem 0 1rem; }
.rrd-badge { display:inline-flex; align-items:center; gap:6px; padding:7px 14px;
  border-radius:999px; font-weight:700; font-size:.82rem; letter-spacing:.01em; }
.rrd-badge-ok { background:#dcfce7; color:#15803d; border:1px solid #86efac; }
.rrd-badge-todo { background:#fef3c7; color:#a16207; border:1px solid #fcd34d; }
.rrd-status-mail { color:#64748b; font-size:.9rem; }

/* ===================== Numbered steps (email setup) ===================== */
.rrd-steps { display:flex; flex-direction:column; gap:14px; margin:.4rem 0 1.2rem; }
.rrd-step { display:flex; gap:16px; align-items:flex-start;
  background:#fbfbfe; border:1px solid #e7e9ef; border-radius:14px; padding:14px 16px; }
.rrd-step-dot {
  width:30px; height:30px; border-radius:50%; display:grid; place-items:center; flex:0 0 auto;
  background:linear-gradient(135deg,#ea580c,#f97316); color:#ffffff; font-weight:800; font-size:.92rem;
  box-shadow:0 6px 14px -4px rgba(79,70,229,.45); }
.rrd-step-body { color:#334155; font-size:.95rem; line-height:1.55; }
.rrd-step-body strong { color:#0f172a; }
.rrd-step-body a { color:#ea580c; font-weight:600; }

/* ===================== AI cards ===================== */
.rrd-ai-cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:18px;
  margin:.4rem 0 1.4rem; }
.rrd-ai-card { background:linear-gradient(180deg,#ffffff 0%,#fafbff 100%);
  border:1px solid #e7e9ef; border-radius:18px; padding:22px 20px;
  box-shadow:0 10px 22px -12px rgba(15,23,42,.10); transition:transform .25s ease; }
.rrd-ai-card:hover { transform:translateY(-3px); }
.rrd-ai-ic { font-size:1.7rem; width:48px; height:48px; border-radius:14px; display:grid; place-items:center;
  background:linear-gradient(135deg,#fff7ed,#fce7f3); margin-bottom:.7rem; }
.rrd-ai-card h4 { margin:0 0 .35rem; font-size:1.02rem; font-weight:800; color:#0f172a; }
.rrd-ai-card p { margin:0; color:#475569; font-size:.9rem; line-height:1.55; }

/* ===================== Finish ===================== */
.rrd-finish { margin-top:2rem; height:1px;
  background:linear-gradient(90deg,transparent,#e7e9ef,transparent); }
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
