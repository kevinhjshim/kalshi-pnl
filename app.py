"""Kalshi PnL Dashboard — track realized profits/losses per month and year."""

from __future__ import annotations

import base64
import concurrent.futures
import json
import os
import re
import time

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as crypto_padding

KALSHI_API_BASE       = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_API_PATH_PREFIX = "/trade-api/v2"
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

# ── Theme definitions ─────────────────────────────────────────────────────────
THEMES: dict[str, dict] = {
    "Dark": {
        "bg":      "#050506",
        "surface": "#08080B",
        "card":    "#0F0F14",
        "border":  "rgba(255,255,255,0.06)",
        "border2": "rgba(255,255,255,0.11)",
        "text":    "#EDEDEF",
        "muted":   "#8A8F98",
        "soft":    "#C4C9D4",
        "accent":  "#5E6AD2",
        "profit":  "#2DD4A2",
        "loss":    "#F87171",
        "line":    "#67E8F9",
        "warn":    "#F59E0B",
    },
    "Light": {
        "bg":      "#FAFAF9",
        "surface": "#F4F4F1",
        "card":    "#FFFFFF",
        "border":  "rgba(0,0,0,0.07)",
        "border2": "rgba(0,0,0,0.13)",
        "text":    "#1A1A22",
        "muted":   "#6B7080",
        "soft":    "#383A47",
        "accent":  "#5E6AD2",
        "profit":  "#059669",
        "loss":    "#DC2626",
        "line":    "#0EA5E9",
        "warn":    "#D97706",
    },
}


def build_css(T: dict) -> str:
    is_dark = T["bg"] == "#050506"

    # Shadows scale with theme — heavy on dark (depth), featherlight on light
    if is_dark:
        card_shadow   = f"0 0 0 1px {T['border']}, 0 2px 16px rgba(0,0,0,0.28)"
        conn_shadow   = f"0 0 0 1px {T['border']}, 0 4px 28px rgba(0,0,0,0.35)"
        info_shadow   = f"0 2px 12px rgba(0,0,0,0.20)"
        metric_shadow = f"0 0 0 1px {T['border']}, 0 2px 16px rgba(0,0,0,0.22)"
        hdr_icons_css = ""  # icons are white — fine on dark
    else:
        card_shadow   = f"0 0 0 1px {T['border']}, 0 2px 8px rgba(0,0,0,0.06)"
        conn_shadow   = f"0 0 0 1px rgba(0,0,0,0.10), 0 2px 12px rgba(0,0,0,0.07)"
        info_shadow   = f"0 1px 4px rgba(0,0,0,0.06)"
        metric_shadow = f"0 0 0 1px {T['border']}, 0 2px 8px rgba(0,0,0,0.06)"
        # light bg — force Streamlit's top-bar icons to be dark
        hdr_icons_css = f"""
[data-testid="stHeader"] button svg {{ fill: {T['muted']} !important; }}
[data-testid="stHeader"] button {{ color: {T['muted']} !important; }}
[data-testid="stHeader"] a svg {{ fill: {T['muted']} !important; }}
"""

    # Radial gradient for dark; flat for light
    if is_dark:
        page_bg = (
            f"radial-gradient(ellipse at 50% 0%, #0D0D1A 0%, {T['bg']} 55%, #020203 100%)"
        )
        blob_css = f"""
@keyframes blob1 {{
    0%, 100% {{ transform: translateX(-50%) translateY(0px) scale(1); }}
    40%  {{ transform: translateX(-50%) translateY(-50px) scale(1.04); }}
    70%  {{ transform: translateX(-50%) translateY(22px) scale(0.97); }}
}}
@keyframes blob2 {{
    0%, 100% {{ transform: translateX(0px) translateY(0px) scale(1); }}
    50%  {{ transform: translateX(-38px) translateY(-32px) scale(1.05); }}
}}
@keyframes blob3 {{
    0%, 100% {{ transform: translateX(0px) translateY(0px) scale(1); }}
    60%  {{ transform: translateX(28px) translateY(28px) scale(0.96); }}
}}
.bg-blob-1 {{
    position: fixed; top: -28%; left: 50%;
    width: 1100px; height: 750px; border-radius: 50%;
    background: radial-gradient(ellipse, {T['accent']}1A 0%, transparent 70%);
    filter: blur(110px); pointer-events: none; z-index: 0;
    animation: blob1 14s ease-in-out infinite;
}}
.bg-blob-2 {{
    position: fixed; top: 25%; left: -18%;
    width: 650px; height: 520px; border-radius: 50%;
    background: radial-gradient(ellipse, rgba(110,70,210,0.10) 0%, transparent 70%);
    filter: blur(130px); pointer-events: none; z-index: 0;
    animation: blob2 19s ease-in-out infinite 3s;
}}
.bg-blob-3 {{
    position: fixed; bottom: -18%; right: -12%;
    width: 540px; height: 460px; border-radius: 50%;
    background: radial-gradient(ellipse, rgba(50,110,220,0.08) 0%, transparent 70%);
    filter: blur(120px); pointer-events: none; z-index: 0;
    animation: blob3 22s ease-in-out infinite 6s;
}}
"""
    else:
        page_bg = T["bg"]
        blob_css = ""

    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@300;400;500&display=swap');

{blob_css}

/* ── Keyframes ── */
@keyframes shimmer {{
    from {{ background-position: -200% center; }}
    to   {{ background-position:  200% center; }}
}}

/* ── Selection ── */
::selection {{ background: {T['accent']}44; color: {T['text']}; }}

{hdr_icons_css}

/* ── Base ── */
html, body, .stApp, [data-testid="stAppViewContainer"] {{
    background: {page_bg} !important;
    color: {T['text']};
    font-family: 'Inter', system-ui, sans-serif;
}}
[data-testid="stHeader"] {{
    background: {T['bg']}F0 !important;
    backdrop-filter: blur(16px) !important;
    -webkit-backdrop-filter: blur(16px) !important;
    border-bottom: 1px solid {T['border']};
}}
p, li, span, div {{ font-family: 'Inter', system-ui, sans-serif; }}

/* ── Sidebar ── */
[data-testid="stSidebar"] {{
    background: {T['surface']} !important;
    border-right: 1px solid {T['border']};
}}
[data-testid="stSidebar"] * {{ color: {T['text']}; }}
[data-testid="collapsedControl"] {{
    background: {T['surface']} !important;
    border-right: 1px solid {T['border']};
}}

/* ── Buttons ── */
.stButton > button {{
    background: rgba(255,255,255,0.04) !important;
    color: {T['soft']} !important;
    border: 1px solid {T['border2']} !important;
    border-radius: 8px !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    letter-spacing: 0 !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.06) !important;
    transition: all 0.2s cubic-bezier(0.16,1,0.3,1) !important;
}}
.stButton > button:hover {{
    background: rgba(255,255,255,0.08) !important;
    color: {T['text']} !important;
    transform: translateY(-1px) !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.09),
                0 4px 16px rgba(0,0,0,0.25) !important;
}}
.stButton > button:active {{
    transform: scale(0.98) translateY(0px) !important;
}}
.stButton > button[kind="primary"] {{
    background: {T['accent']} !important;
    border: 1px solid {T['accent']}CC !important;
    color: #FFFFFF !important;
    font-weight: 600 !important;
    box-shadow: 0 0 0 1px {T['accent']}88,
                0 4px 14px {T['accent']}44,
                inset 0 1px 0 rgba(255,255,255,0.20) !important;
}}
.stButton > button[kind="primary"]:hover {{
    background: #6872D9 !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 0 0 1px {T['accent']}AA,
                0 6px 22px {T['accent']}55,
                inset 0 1px 0 rgba(255,255,255,0.25) !important;
}}

/* ── Inputs ── */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea {{
    background-color: {T['card']} !important;
    border: 1px solid {T['border2']} !important;
    border-radius: 8px !important;
    color: {T['text']} !important;
    -webkit-text-fill-color: {T['text']} !important;
    caret-color: {T['text']} !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.82rem !important;
    box-shadow: inset 0 1px 3px rgba(0,0,0,0.12) !important;
    transition: border-color 0.18s ease, box-shadow 0.18s ease !important;
}}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {{
    border-color: {T['accent']} !important;
    box-shadow: 0 0 0 3px {T['accent']}22,
                inset 0 1px 3px rgba(0,0,0,0.12) !important;
    outline: none !important;
}}
input:-webkit-autofill, input:-webkit-autofill:hover,
input:-webkit-autofill:focus, textarea:-webkit-autofill {{
    -webkit-box-shadow: 0 0 0 1000px {T['card']} inset !important;
    -webkit-text-fill-color: {T['text']} !important;
    caret-color: {T['text']} !important;
}}
input::-webkit-credentials-auto-fill-button,
input::-webkit-strong-password-auto-fill-button,
input::-webkit-contacts-auto-fill-button {{
    visibility: hidden; pointer-events: none;
}}
[data-testid="InputInstructions"] {{ display: none !important; }}
.stTextInput label p, .stTextArea label p,
[data-testid="stWidgetLabel"] p {{
    color: {T['muted']} !important;
    font-size: 0.68rem !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important;
    letter-spacing: 0.06em !important;
    text-transform: uppercase !important;
}}
.stTextInput input::placeholder, .stTextArea textarea::placeholder {{
    color: {T['muted']}88 !important;
}}

/* ── Selectbox ── */
.stSelectbox > div > div {{
    background: {T['card']} !important;
    border: 1px solid {T['border2']} !important;
    border-radius: 8px !important;
    color: {T['text']} !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.82rem !important;
}}

/* ── Radio ── */
.stRadio label p {{
    color: {T['soft']} !important;
    font-size: 0.82rem !important;
    font-family: 'Inter', sans-serif !important;
}}
.stRadio [role="radiogroup"] label {{
    display: flex !important;
    align-items: center !important;
    gap: 6px !important;
    cursor: pointer;
}}
.stRadio [role="radiogroup"] label p {{
    margin: 0 !important;
    line-height: 1 !important;
    padding-top: 0 !important;
}}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {{
    background: transparent;
    border-bottom: 1px solid {T['border']};
    gap: 0;
}}
.stTabs [data-baseweb="tab"] {{
    background: transparent;
    color: {T['muted']};
    border-bottom: 2px solid transparent;
    padding: 10px 16px;
    font-family: 'Inter', sans-serif;
    font-size: 0.8rem;
    font-weight: 500;
    letter-spacing: 0;
    transition: color 0.15s ease;
}}
.stTabs [data-baseweb="tab"]:hover {{
    color: {T['soft']} !important;
    background: rgba(255,255,255,0.03) !important;
}}
.stTabs [aria-selected="true"] {{
    background: transparent !important;
    color: {T['text']} !important;
    border-bottom-color: {T['accent']} !important;
}}
.stTabs [data-baseweb="tab-panel"] {{ padding-top: 20px; }}

/* ── Expanders ── */
[data-testid="stExpander"] {{
    background: {T['card']};
    border: 1px solid {T['border']};
    border-radius: 10px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.15);
}}
[data-testid="stExpander"] summary {{
    color: {T['soft']};
    font-size: 0.85rem;
    font-family: 'Inter', sans-serif;
}}

/* ── Metric card (default + hover) ── */
.metric-card {{
    box-shadow: {metric_shadow} !important;
    transition: transform 0.25s cubic-bezier(0.16,1,0.3,1),
                box-shadow 0.25s cubic-bezier(0.16,1,0.3,1) !important;
    cursor: default;
}}
.metric-card:hover {{
    transform: translateY(-3px) !important;
    box-shadow: 0 0 0 1px {T['border2']},
                0 12px 32px rgba(0,0,0,{"0.45" if is_dark else "0.10"}),
                0 0 60px {T['accent']}{"0E" if is_dark else "0A"} !important;
}}

/* ── Divider ── */
hr {{ border-color: {T['border']} !important; margin: 14px 0; }}

/* ── Code ── */
code {{
    background: {T['card']} !important;
    color: {T['accent']} !important;
    border: 1px solid {T['border']} !important;
    border-radius: 4px;
    padding: 2px 6px;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.78rem;
}}

/* ── Alerts ── */
[data-testid="stAlert"] {{
    background: {T['card']} !important;
    border: 1px solid {T['border2']} !important;
    border-radius: 8px;
    color: {T['soft']} !important;
    font-family: 'Inter', sans-serif !important;
}}

/* ── Loading spinner ── */
.stSpinner > div {{ border-top-color: {T['accent']} !important; }}

/* ── Connect card ── */
.connect-card {{
    background: {T['card']};
    border: 1px solid {"rgba(255,255,255,0.09)" if is_dark else "rgba(0,0,0,0.10)"};
    border-radius: 12px;
    padding: 28px 30px 26px;
    box-shadow: {conn_shadow};
    position: relative;
    overflow: hidden;
}}
.connect-card::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0; height: 1px;
    background: linear-gradient(to right, transparent, {T['accent']}55, transparent);
}}

/* ── Security / preview cards ── */
.info-card {{
    background: {T['card']};
    border: 1px solid {"rgba(255,255,255,0.07)" if is_dark else "rgba(0,0,0,0.08)"};
    border-radius: 12px;
    padding: 22px 24px;
    box-shadow: {info_shadow};
    position: relative;
    overflow: hidden;
}}

/* ── Scrollbar ── */
::-webkit-scrollbar {{ width: 4px; height: 4px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: {T['border2']}; border-radius: 2px; }}
::-webkit-scrollbar-thumb:hover {{ background: {T['muted']}; }}

/* ── Streamlit decoration bar (hide rainbow strip) ── */
[data-testid="stDecoration"] {{ display: none !important; }}

/* ── Spinner / status widget ── */
.stSpinner > div {{
    border-color: {T['border2']} {T['border']} {T['border']} !important;
    border-top-color: {T['accent']} !important;
    width: 18px !important; height: 18px !important;
}}
[data-testid="stStatusWidget"],
[data-testid="stSpinner"] > div > div {{
    background: {T['surface']} !important;
    border: 1px solid {T['border']} !important;
    border-radius: 10px !important;
    box-shadow: 0 4px 20px rgba(0,0,0,{"0.35" if is_dark else "0.10"}) !important;
    color: {T['muted']} !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.8rem !important;
}}
[data-testid="stStatusWidget"] * {{
    color: {T['muted']} !important;
    font-family: 'Inter', sans-serif !important;
}}
/* Progress bar under spinner */
[data-testid="stProgressBar"] > div {{
    background: {T['accent']} !important;
    border-radius: 2px !important;
}}
</style>
"""


# ── Background blobs (dark theme only) ───────────────────────────────────────

def render_bg_blobs(T: dict) -> str:
    if T["bg"] != "#050506":
        return ""
    return (
        '<div style="position:fixed;inset:0;pointer-events:none;z-index:0;overflow:hidden">'
        '<div class="bg-blob-1"></div>'
        '<div class="bg-blob-2"></div>'
        '<div class="bg-blob-3"></div>'
        '</div>'
    )


# ── Settings persistence ──────────────────────────────────────────────────────

def load_settings() -> dict:
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"keywords": [], "theme": "Dark"}


def save_settings(data: dict) -> None:
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ── Auth ──────────────────────────────────────────────────────────────────────

def rsa_headers(key_id: str, private_key_pem: str, method: str, path: str) -> dict:
    ts = str(int(time.time() * 1000))
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode() if isinstance(private_key_pem, str) else private_key_pem,
        password=None,
    )
    message = (ts + method.upper() + path.split("?")[0]).encode()
    sig = private_key.sign(
        message,
        crypto_padding.PSS(
            mgf=crypto_padding.MGF1(hashes.SHA256()),
            salt_length=crypto_padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "Content-Type": "application/json",
    }


def email_login(email: str, password: str) -> tuple[str | None, str | None]:
    try:
        resp = requests.post(
            f"{KALSHI_API_BASE}/login",
            json={"email": email, "password": password},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json().get("token"), None
        return None, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return None, str(e)


def make_headers(creds: dict, method: str, path: str) -> dict:
    if creds["type"] == "rsa":
        return rsa_headers(creds["key_id"], creds["private_key_pem"], method, path)
    return {"Authorization": f"Bearer {creds['token']}", "Content-Type": "application/json"}


# ── API ───────────────────────────────────────────────────────────────────────

def _get(path: str, creds: dict, params: dict | None = None) -> requests.Response:
    return requests.get(
        KALSHI_API_BASE + path,
        headers=make_headers(creds, "GET", KALSHI_API_PATH_PREFIX + path),
        params=params,
        timeout=20,
    )


@st.cache_data(ttl=300, show_spinner="Fetching your trades…")
def fetch_all_settlements(creds_key: str, creds: dict) -> tuple[list, str | None]:
    settlements, cursor = [], None
    while True:
        params: dict = {"limit": 1000}
        if cursor:
            params["cursor"] = cursor
        try:
            resp = _get("/portfolio/settlements", creds, params)
        except Exception as e:
            return [], str(e)
        if resp.status_code != 200:
            return [], f"HTTP {resp.status_code}: {resp.text[:300]}"
        data = resp.json()
        batch = data.get("settlements", [])
        settlements.extend(batch)
        cursor = data.get("cursor")
        if not cursor or not batch:
            break
    return settlements, None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_market_titles(creds_key: str, creds: dict, tickers: tuple) -> dict:
    title_map: dict = {}
    tickers_list = list(tickers)

    # Batch fetch — try both repeated-param and comma-separated formats
    for i in range(0, len(tickers_list), 100):
        batch = tickers_list[i : i + 100]
        for params in (
            [("ticker", t) for t in batch] + [("limit", "100")],   # REST standard
            {"tickers": ",".join(batch), "limit": 100},             # comma-separated
        ):
            try:
                resp = _get("/markets", creds, params)
                if resp.status_code == 200:
                    for m in resp.json().get("markets", []):
                        raw = m.get("title") or m.get("subtitle") or ""
                        if raw:
                            title_map[m["ticker"]] = normalize_market_title(
                                raw, m["ticker"]
                            )
                    if title_map:   # if we got any hits, the format worked
                        break
            except Exception:
                pass

    # Parallel individual fallback for remaining tickers (no hard limit)
    missing = [t for t in tickers_list if t not in title_map]

    def _fetch_one(ticker_str: str) -> tuple[str, str | None]:
        try:
            resp = _get(f"/markets/{ticker_str}", creds)
            if resp.status_code == 200:
                m = resp.json().get("market", {})
                raw = m.get("title") or m.get("subtitle") or ""
                if raw:
                    return ticker_str, normalize_market_title(raw, ticker_str)
        except Exception:
            pass
        return ticker_str, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        for ticker_str, title in ex.map(_fetch_one, missing[:500]):
            if title:
                title_map[ticker_str] = title

    # Final structural fallback (parse_ticker covers known patterns)
    for t in tickers_list:
        if t not in title_map:
            title_map[t] = parse_ticker(t)

    return title_map


# ── Ticker / title helpers ────────────────────────────────────────────────────

_SPORT_CODES = [
    ("NCAAFGAME", "NCAAF"), ("NCAAMGAME", "NCAAM"), ("NCAAMBGAME", "NCAAM"),
    ("NCAAWBGAME", "NCAAW"), ("NFLGAME", "NFL"), ("NBAGAME", "NBA"),
    ("NHLGAME", "NHL"), ("MLBGAME", "MLB"), ("NBACUP", "NBA Cup"), ("NACUP", "NBA Cup"),
]
_MONTHS = {
    "JAN": "Jan", "FEB": "Feb", "MAR": "Mar", "APR": "Apr",
    "MAY": "May", "JUN": "Jun", "JUL": "Jul", "AUG": "Aug",
    "SEP": "Sep", "OCT": "Oct", "NOV": "Nov", "DEC": "Dec",
}


_MENTION_SUBJECTS: dict[str, str] = {
    "NFL": "NFL", "NBA": "NBA", "NCAA": "NCAA", "NCAAM": "NCAA",
    "NCAAF": "NCAAF", "NCAAW": "NCAAW", "MLB": "MLB", "NHL": "NHL",
    "MAMDANI": "Mamdani", "MRBEAST": "MrBeast", "NEWSOM": "Newsom",
    "WALZ": "Walz", "EARNINGS": "Earnings",
}


def parse_ticker(ticker: str) -> str:
    t = ticker.upper()
    if not t.startswith("KX"):
        return ticker
    rest = t[2:]

    # ── Existing sport-game codes ──────────────────────────────────────────
    for code, sport in _SPORT_CODES:
        if rest.startswith(code):
            details = rest[len(code):].lstrip("-")
            parts = [p for p in details.split("-") if p]

            if code in ("NBACUP", "NACUP"):
                year = f"20{parts[0][:2]}" if parts else "?"
                team = parts[1] if len(parts) > 1 else ""
                return f"NBA Cup {year}" + (f" · {team}" if team else "")

            if len(parts) >= 2:
                date_teams, result = parts[0], parts[1]
                m = re.match(r"(\d{2})([A-Z]{3})(\d{2})(.*)", date_teams)
                if m:
                    yy, mon, dd, teams = m.groups()
                    return f"{sport} · {teams} · {result} wins ({_MONTHS.get(mon, mon)} {int(dd)}, 20{yy})"
            break

    # ── Multi-variable enhanced markets ───────────────────────────────────
    if rest.startswith("MVENBASINGLEGAME"):
        return "NBA Single Game"
    if rest.startswith("MVESPORTSMULTIGAME"):
        return "Sports Multi-Game"
    if rest.startswith("MVECROSSCATEGORY"):
        return "Multi-Category Market"

    # ── Super Bowl / event markets ─────────────────────────────────────────
    if rest.startswith("SUPERBOWLAD-"):
        opt = rest.split("-")[-1]
        return f"Super Bowl Ad · {opt}"
    if rest.startswith("NFLSBMVP-") or rest.startswith("SBMVP-"):
        opt = rest.split("-")[-1]
        return f"Super Bowl MVP · {opt}"
    if rest.startswith("PERFORMSUPERBOWL") or rest.startswith("PERFSUPERBOWL"):
        opt = rest.split("-")[-1]
        return f"Super Bowl Performance · {opt}"
    if rest.startswith("FIRSTSUPERBOWLSONG"):
        opt = rest.split("-")[-1]
        return f"Super Bowl Song · {opt}"
    if rest.startswith("SBGUESTS"):
        opt = rest.split("-")[-1]
        return f"Super Bowl Guests · {opt}"

    # ── Award / MVP markets ────────────────────────────────────────────────
    if rest.startswith("NBAALLSTARMVP"):
        opt = rest.split("-")[-1]
        return f"NBA All-Star MVP · {opt}"

    # ── Spread markets: KXNCAAMBSPREAD-26FEB14SJUPROV-SJU4 ────────────────
    m_spread = re.match(
        r"^(NCAAM[BW]?|NCAAF[BW]?|NFL|NBA)SPREAD-(\d{2}[A-Z]{3}\d{2})([A-Z0-9]*)-([A-Z0-9+\-]+)$",
        rest,
    )
    if m_spread:
        sport_s, date_str, teams, opt = m_spread.groups()
        mon_m = re.match(r"\d{2}([A-Z]{3})\d{2}", date_str)
        dd_m  = re.match(r"\d{2}[A-Z]{3}(\d{2})", date_str)
        mon   = _MONTHS.get(mon_m.group(1), "") if mon_m else ""
        day   = int(dd_m.group(1)) if dd_m else 0
        base  = f"{sport_s} Spread"
        if teams:
            base += f" · {teams}"
        base += f" · {opt}"
        if mon and day:
            base += f" ({mon} {day})"
        return base

    # ── Mention markets ────────────────────────────────────────────────────
    if "MENTION" in rest:
        # With game code: KXNFLMENTION-26JAN11LACNE-TUSH
        m1 = re.match(
            r"^([A-Z]+?)MENTION(?:[A-Z]+)?-(\d{2}[A-Z]{3}\d{2})([A-Z0-9]+)-([A-Z0-9]+)$",
            rest,
        )
        if m1:
            subj_raw, _, game, opt = m1.groups()
            subj = _MENTION_SUBJECTS.get(subj_raw, subj_raw.title())
            return f"{subj} Mention · {game} · {opt}"
        # Without game code: KXMAMDANIMENTION-26JAN08-TRAN
        m2 = re.match(
            r"^([A-Z]+?)MENTION(?:[A-Z]+)?-(\d{2}[A-Z]{3}\d{2})-([A-Z0-9]+)$",
            rest,
        )
        if m2:
            subj_raw, _, opt = m2.groups()
            subj = _MENTION_SUBJECTS.get(subj_raw, subj_raw.title())
            return f"{subj} Mention · {opt}"

    return ticker


def normalize_market_title(raw_title: str, ticker: str) -> str:
    title = (raw_title or "").strip()
    if not title or title == ticker:
        return parse_ticker(ticker)

    # Multi-pick: "yes Cleveland, yes OKC, ..."
    if re.match(r"^(yes|no)\s+\S", title, re.IGNORECASE):
        parts = [p.strip() for p in title.split(",")]
        picks = []
        for p in parts:
            m = re.match(r"^(yes|no)\s+(.+)$", p.strip(), re.IGNORECASE)
            picks.append(m.group(2).strip() if m else p.strip())
        if len(picks) <= 4:
            return " · ".join(picks)
        return " · ".join(picks[:3]) + f"  (+{len(picks) - 3} more)"

    # Game matchup: "X at/vs Y [C] Winner?" → "X vs Y"
    m = re.match(
        r"^(.+?)\s+(?:at|vs\.?)\s+(.+?)(?:\s+[A-Z]{1,2})?\s+Winner\??$",
        title, re.IGNORECASE,
    )
    if m:
        t1 = m.group(1).strip()
        t2 = re.sub(r"\s+[A-Z]{1,2}$", "", m.group(2).strip()).strip()
        return f"{t1} vs {t2}"

    # Strip trailing " Winner?" / " winner" / " — Winner"
    title = re.sub(r"[\s\-–]+Winner\??$", "", title, flags=re.IGNORECASE).strip()

    # "Will X qualify for/win the Y?" — keep as-is but trim length
    # Trim boilerplate: "Will ... be the ..." → try to shorten common patterns
    title = re.sub(r"\s+\?$", "?", title)
    title = re.sub(r"\s{2,}", " ", title).strip()

    # "Will X win the ... [Championship|Lottery|Award]?" — abbreviate
    m_will = re.match(
        r"^Will\s+(.+?)\s+(?:win|qualify for|reach|advance to)\s+(.+?)[\?\.]?$",
        title, re.IGNORECASE,
    )
    if m_will:
        subject = m_will.group(1).strip()
        event   = m_will.group(2).strip()
        event   = re.sub(r"the\s+", "", event, flags=re.IGNORECASE).strip()
        return f"{subject} — {event}?"

    # ALL CAPS title → Title Case
    if title == title.upper() and len(title) > 4:
        title = title.title()

    return title.strip()


# ── Data processing ───────────────────────────────────────────────────────────

def process_settlements(settlements: list, creds_key: str, creds: dict) -> pd.DataFrame:
    rows = []
    for s in settlements:
        ticker    = s.get("ticker", "")
        result    = (s.get("market_result") or "").lower()
        yes_cost  = float(s.get("yes_total_cost_dollars", 0))
        no_cost   = float(s.get("no_total_cost_dollars",  0))
        fee       = float(s.get("fee_cost", 0))
        total_cost = yes_cost + no_cost + fee
        yes_count = float(s.get("yes_count_fp", 0))
        no_count  = float(s.get("no_count_fp",  0))

        revenue = yes_count if result == "yes" else (no_count if result == "no" else 0.0)

        if yes_cost > 0 and no_cost == 0:
            held, contracts = "YES", yes_count
            entry_cents = (yes_cost / yes_count * 100) if yes_count > 0 else 0.0
        elif no_cost > 0 and yes_cost == 0:
            held, contracts = "NO", no_count
            entry_cents = (no_cost / no_count * 100) if no_count > 0 else 0.0
        elif yes_cost >= no_cost:
            held, contracts = "YES", yes_count
            entry_cents = (yes_cost / yes_count * 100) if yes_count > 0 else 0.0
        else:
            held, contracts = "NO", no_count
            entry_cents = (no_cost / no_count * 100) if no_count > 0 else 0.0

        rows.append({
            "ticker":       ticker,
            "settled_time": s.get("settled_time", ""),
            "revenue":      revenue,
            "yes_cost":     yes_cost,
            "no_cost":      no_cost,
            "fee":          fee,
            "cost":         total_cost,
            "pnl":          revenue - total_cost,
            "result":       result.upper(),
            "yes_count":    yes_count,
            "no_count":     no_count,
            "held":         held,
            "contracts":    contracts,
            "entry_cents":  entry_cents,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["settled_time"] = pd.to_datetime(df["settled_time"], utc=True, errors="coerce")
    df = df.dropna(subset=["settled_time"])
    df["settled_time"] = df["settled_time"].dt.tz_localize(None)
    df["year"]        = df["settled_time"].dt.year
    df["year_month"]  = df["settled_time"].dt.to_period("M")
    df["month_label"] = df["year_month"].apply(lambda p: p.strftime("%b %Y"))
    df = df.sort_values("settled_time").reset_index(drop=True)

    unique_tickers = tuple(sorted(df["ticker"].unique()))
    title_map = fetch_market_titles(creds_key, creds, unique_tickers)
    df["title"] = df["ticker"].map(title_map)
    return df


def split_by_exclusions(df: pd.DataFrame, keywords: list) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty or not keywords:
        return df.copy(), pd.DataFrame()
    mask = pd.Series(False, index=df.index)
    for kw in keywords:
        kw = kw.strip()
        if kw:
            mask |= df["title"].str.contains(kw, case=False, na=False, regex=False)
            mask |= df["ticker"].str.contains(kw, case=False, na=False, regex=False)
    return df[~mask].copy(), df[mask].copy()


def keyword_match_count(df: pd.DataFrame, kw: str) -> int:
    kw = kw.strip()
    if not kw or df.empty:
        return 0
    mask = (
        df["title"].str.contains(kw, case=False, na=False, regex=False)
        | df["ticker"].str.contains(kw, case=False, na=False, regex=False)
    )
    return int(mask.sum())


# ── Charts ────────────────────────────────────────────────────────────────────

def pnl_bar_chart(grouped: pd.DataFrame, x_col: str, title: str, T: dict) -> go.Figure:
    grouped = grouped.copy()
    grouped["cumulative"] = grouped["pnl"].cumsum()
    mono = "Inter, system-ui, sans-serif"

    fig = go.Figure()
    for _, row in grouped.iterrows():
        color = T["profit"] if row["pnl"] >= 0 else T["loss"]
        fig.add_trace(go.Bar(
            x=[row[x_col]], y=[row["pnl"]],
            marker_color=color, marker_line_width=0, marker_opacity=0.9,
            showlegend=False,
            hovertemplate=f"<b>{row[x_col]}</b><br>PnL: ${row['pnl']:,.2f}<extra></extra>",
        ))

    fig.add_trace(go.Scatter(
        x=grouped[x_col], y=grouped["cumulative"],
        mode="lines", name="Cumulative",
        line=dict(color=T["line"], width=1.5),
        yaxis="y2",
        hovertemplate="<b>%{x}</b><br>Running: $%{y:,.2f}<extra></extra>",
    ))

    fig.update_layout(
        title=dict(text=title.upper(), font=dict(family=mono, color=T["muted"], size=10), x=0),
        height=390,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family=mono, color=T["muted"], size=11),
        yaxis=dict(
            title="", zeroline=True, zerolinecolor=T["border2"], zerolinewidth=1,
            gridcolor=T["border"], tickfont=dict(size=10), tickprefix="$",
        ),
        yaxis2=dict(
            title="", overlaying="y", side="right",
            gridcolor="rgba(0,0,0,0)",
            tickfont=dict(color=T["line"], size=10), tickprefix="$",
        ),
        xaxis=dict(showgrid=False, tickfont=dict(size=10)),
        hovermode="x unified",
        hoverlabel=dict(bgcolor=T["card"], bordercolor=T["border2"],
                        font=dict(family=mono, color=T["text"], size=11)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    font=dict(size=10), bgcolor="rgba(0,0,0,0)"),
        showlegend=False,
        margin=dict(t=36, b=32, l=4, r=4),
        bargap=0.35,
    )
    return fig


# ── HTML rendering helpers ────────────────────────────────────────────────────

def metric_card(label: str, value: str, sub: str, T: dict,
                accent: str | None = None, value_color: str | None = None) -> str:
    ac  = accent or T["accent"]
    vc  = value_color or T["text"]
    sub_html = (
        f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.68rem;'
        f'color:{T["muted"]};margin-top:6px;line-height:1.4">{sub}</div>'
    ) if sub else ""
    return (
        # outer wrapper — the CSS class .metric-card adds hover transition
        f'<div class="metric-card" style="'
        f'background:{T["card"]};'
        f'border:1px solid {T["border"]};'
        f'border-radius:10px;'
        f'padding:18px 20px 16px;'
        f'height:100%;'
        f'position:relative;'
        f'overflow:hidden;'
        f'">'
        # gradient hairline at top
        f'<div style="position:absolute;top:0;left:0;right:0;height:1px;'
        f'background:linear-gradient(to right,transparent,{ac}77,transparent)"></div>'
        # value
        f'<div style="font-family:\'Inter\',sans-serif;font-size:1.6rem;'
        f'font-weight:700;color:{vc};line-height:1;letter-spacing:-0.025em;margin-top:2px">{value}</div>'
        # label
        f'<div style="font-family:\'Inter\',sans-serif;font-size:0.58rem;'
        f'color:{T["muted"]};text-transform:uppercase;letter-spacing:0.1em;'
        f'font-weight:600;margin-top:10px">{label}</div>'
        f'{sub_html}'
        f'</div>'
    )


def html_table(df: pd.DataFrame, T: dict) -> str:
    """Render a DataFrame as a fully themed HTML table."""
    COLOR_RULES: dict[str, object] = {
        "PnL":     lambda v: T["profit"] if str(v).startswith("+") else T["loss"],
        "W/L":     lambda v: T["profit"] if v == "WIN" else (T["loss"] if v == "LOSS" else T["muted"]),
        "Held":    lambda v: T["accent"],
        "Outcome": lambda v: T["profit"] if v == "YES" else T["loss"],
    }
    MONO_COLS = {"PnL", "W/L", "Held", "Outcome", "Contracts", "Entry", "Cost",
                 "PnL", "Month", "Year", "Markets", "Wins", "Win %", "Running Total"}

    ths = "".join(
        f'<th style="padding:9px 14px;text-align:left;'
        f'font-family:\'JetBrains Mono\',monospace;font-size:0.6rem;'
        f'text-transform:uppercase;letter-spacing:0.1em;color:{T["muted"]};'
        f'background:{T["surface"]};border-bottom:1px solid {T["border2"]};'
        f'white-space:nowrap;font-weight:500">{col}</th>'
        for col in df.columns
    )

    rows_html = []
    for i, (_, row) in enumerate(df.iterrows()):
        row_bg = T["card"] if i % 2 == 0 else T["surface"]
        cells = []
        for col in df.columns:
            val = row[col]
            val_str = str(val)
            base = (
                f"padding:8px 14px;border-bottom:1px solid {T['border']};"
                f"background:{row_bg};font-size:0.8rem;white-space:nowrap"
            )
            if col in COLOR_RULES:
                color = COLOR_RULES[col](val_str)
                weight = ";font-weight:600" if col == "PnL" else ""
                style = f"{base};color:{color}{weight};font-family:'JetBrains Mono',monospace"
            elif col == "Market":
                style = (
                    f"{base};color:{T['text']};font-family:'Inter',sans-serif;"
                    f"max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                )
            elif col == "Date":
                style = f"{base};color:{T['soft']};font-family:'JetBrains Mono',monospace"
            elif col in MONO_COLS:
                style = f"{base};color:{T['muted']};font-family:'JetBrains Mono',monospace"
            else:
                style = f"{base};color:{T['text']}"
            cells.append(f'<td style="{style}" title="{val_str}">{val_str}</td>')
        rows_html.append("<tr>" + "".join(cells) + "</tr>")

    return (
        f'<div style="overflow-x:auto;border:1px solid {T["border"]};'
        f'border-radius:8px;background:{T["card"]}">'
        f'<table style="width:100%;border-collapse:collapse">'
        f'<thead><tr>{ths}</tr></thead>'
        f'<tbody>{"".join(rows_html)}</tbody>'
        f'</table></div>'
    )


# ── Table data builders ───────────────────────────────────────────────────────

def build_trade_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["Date"]      = out["settled_time"].apply(lambda d: f"{d.strftime('%b')} {d.day}, {d.year}")
    out["Held"]      = out["held"]
    out["Outcome"]   = out["result"]
    out["W/L"]       = out["pnl"].apply(lambda x: "WIN" if x > 0 else ("LOSS" if x < 0 else "PUSH"))
    out["Contracts"] = out["contracts"].apply(lambda x: str(int(x)) if x == int(x) else f"{x:.1f}")
    out["Entry"]     = out["entry_cents"].apply(lambda x: f"¢{x:.1f}" if x > 0 else "—")
    out["Cost"]      = out["cost"].map("${:,.2f}".format)
    out["PnL"]       = out["pnl"].apply(lambda x: f"+${x:,.2f}" if x > 0 else f"-${abs(x):,.2f}")
    return out[["Date", "title", "Held", "Outcome", "W/L", "Contracts", "Entry", "Cost", "PnL"]].rename(
        columns={"title": "Market"}
    )


def build_monthly_df(df: pd.DataFrame) -> pd.DataFrame:
    g = (
        df.groupby(["year_month", "month_label"])
        .agg(pnl=("pnl", "sum"), markets=("ticker", "count"),
             wins=("pnl", lambda x: (x > 0).sum()))
        .reset_index().sort_values("year_month")
    )
    g["win_pct"]    = (g["wins"] / g["markets"] * 100).round(1)
    g["cumulative"] = g["pnl"].cumsum()
    g["month_label"] = g["year_month"].apply(lambda p: p.strftime("%b %Y"))
    out = g[["month_label", "pnl", "markets", "wins", "win_pct", "cumulative"]].iloc[::-1].reset_index(drop=True)
    out["pnl"]        = out["pnl"].apply(lambda x: f"+${x:,.2f}" if x >= 0 else f"-${abs(x):,.2f}")
    out["cumulative"] = out["cumulative"].apply(lambda x: f"+${x:,.2f}" if x >= 0 else f"-${abs(x):,.2f}")
    out["win_pct"]    = out["win_pct"].map("{:.1f}%".format)
    out.columns = ["Month", "PnL", "Markets", "Wins", "Win %", "Running Total"]
    return out


def build_yearly_df(df: pd.DataFrame) -> pd.DataFrame:
    g = (
        df.groupby("year")
        .agg(pnl=("pnl", "sum"), markets=("ticker", "count"),
             wins=("pnl", lambda x: (x > 0).sum()))
        .reset_index().sort_values("year")
    )
    g["win_pct"]    = (g["wins"] / g["markets"] * 100).round(1)
    g["cumulative"] = g["pnl"].cumsum()
    g["year"]       = g["year"].astype(str)
    out = g[["year", "pnl", "markets", "wins", "win_pct", "cumulative"]].iloc[::-1].reset_index(drop=True)
    out["pnl"]        = out["pnl"].apply(lambda x: f"+${x:,.2f}" if x >= 0 else f"-${abs(x):,.2f}")
    out["cumulative"] = out["cumulative"].apply(lambda x: f"+${x:,.2f}" if x >= 0 else f"-${abs(x):,.2f}")
    out["win_pct"]    = out["win_pct"].map("{:.1f}%".format)
    out.columns = ["Year", "PnL", "Markets", "Wins", "Win %", "Running Total"]
    return out


# ── Sidebar component helpers ─────────────────────────────────────────────────

def section_label(text: str, T: dict) -> None:
    st.markdown(
        f"<p style='font-family:\"Inter\",sans-serif;color:{T['muted']};"
        f"font-size:0.6rem;font-weight:600;text-transform:uppercase;letter-spacing:0.1em;"
        f"margin:0 0 8px'>{text}</p>",
        unsafe_allow_html=True,
    )


# ── App ───────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="Kalshi PnL", page_icon="📈",
        layout="wide", initial_sidebar_state="expanded",
    )

    if "settings" not in st.session_state:
        settings = load_settings()
        # URL query param takes priority — survives page refresh & server restart
        kw_param = st.query_params.get("kw", "")
        if kw_param:
            settings["keywords"] = [k.strip() for k in kw_param.split(",") if k.strip()]
        st.session_state.settings = settings
    if "creds" not in st.session_state:
        st.session_state.creds = None
    if "full_df" not in st.session_state:
        st.session_state.full_df = pd.DataFrame()

    # ── Theme ──
    theme_name = st.session_state.settings.get("theme", "Dark")
    T = THEMES[theme_name]

    st.markdown(build_css(T), unsafe_allow_html=True)
    st.markdown(render_bg_blobs(T), unsafe_allow_html=True)

    logged_in = bool(st.session_state.creds)

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        # Wordmark
        st.markdown(
            f"<div style='padding:4px 0 10px'>"
            f"<div style='font-family:\"Inter\",sans-serif;"
            f"font-size:1.05rem;font-weight:700;color:{T['text']};letter-spacing:-0.02em'>"
            f"Kalshi PnL</div>"
            f"<div style='font-family:\"Inter\",sans-serif;font-size:0.58rem;"
            f"font-weight:500;color:{T['muted']};letter-spacing:0.06em;margin-top:3px'>"
            f"PREDICTION MARKET TRACKER</div></div>",
            unsafe_allow_html=True,
        )
        st.divider()

        # ── Theme toggle ──
        section_label("Theme", T)
        new_theme = st.radio(
            "t", list(THEMES.keys()),
            index=list(THEMES.keys()).index(theme_name),
            horizontal=True,
            label_visibility="collapsed",
        )
        if new_theme != theme_name:
            st.session_state.settings["theme"] = new_theme
            save_settings(st.session_state.settings)
            st.rerun()

        if logged_in:
            st.divider()

            # ── Connected badge + logout ──
            st.markdown(
                f"<div style='background:{T['card']};border:1px solid {T['border']};"
                f"border-left:2px solid {T['profit']};border-radius:0 8px 8px 0;"
                f"padding:9px 14px;margin-bottom:8px;"
                f"box-shadow:0 0 0 1px {T['border']},0 2px 8px rgba(0,0,0,0.15)'>"
                f"<span style='font-family:\"Inter\",sans-serif;"
                f"color:{T['profit']};font-size:0.72rem;font-weight:600'>"
                f"● Connected</span></div>",
                unsafe_allow_html=True,
            )
            if st.button("Logout", use_container_width=True):
                st.session_state.creds = None
                st.session_state.full_df = pd.DataFrame()
                st.cache_data.clear()
                st.rerun()

            st.divider()

            # ── Year filter ──
            section_label("Filter", T)
            all_years: list = st.session_state.get("all_years", [])
            year_opts = ["All years"] + [str(y) for y in sorted(all_years, reverse=True)]
            selected_year = st.selectbox("y", year_opts, label_visibility="collapsed")

            st.divider()

            # ── Exclusions ──
            section_label("Exclusions", T)
            st.markdown(
                f"<p style='color:{T['muted']};font-size:0.78rem;line-height:1.5;margin-bottom:8px'>"
                f"Remove trades from PnL — e.g. trades placed for a friend.</p>",
                unsafe_allow_html=True,
            )
            keywords: list = st.session_state.settings.get("keywords", [])
            full_df  = st.session_state.full_df

            new_kw = st.text_input("kw", placeholder="e.g. NBA, NFL",
                                   label_visibility="collapsed", key="kw_input")
            if st.button("+ Add keyword", use_container_width=True, key="kw_add"):
                kw = new_kw.strip()
                if kw and kw not in keywords:
                    keywords.append(kw)
                    st.session_state.settings["keywords"] = keywords
                    save_settings(st.session_state.settings)
                    st.query_params["kw"] = ",".join(keywords)
                    st.rerun()

            for i, kw in enumerate(keywords[:]):
                count = keyword_match_count(full_df, kw) if not full_df.empty else 0
                c1, c2 = st.columns([5, 1])
                badge_color = T["loss"] if count > 0 else T["muted"]
                c1.markdown(
                    f"<div style='background:{T['card']};border:1px solid {T['border']};"
                    f"border-left:2px solid {T['accent']};border-radius:0 6px 6px 0;"
                    f"padding:6px 10px;margin-bottom:2px;"
                    f"box-shadow:0 1px 4px rgba(0,0,0,0.12)'>"
                    f"<div style='font-family:\"Inter\",sans-serif;font-size:0.8rem;"
                    f"font-weight:500;color:{T['text']}'>{kw}</div>"
                    f"<div style='font-family:\"Inter\",sans-serif;font-size:0.62rem;"
                    f"color:{badge_color};margin-top:2px'>"
                    f"{'no matches' if count == 0 else f'{count} trades excluded'}</div></div>",
                    unsafe_allow_html=True,
                )
                if c2.button("×", key=f"rm_{i}"):
                    keywords.pop(i)
                    st.session_state.settings["keywords"] = keywords
                    save_settings(st.session_state.settings)
                    if keywords:
                        st.query_params["kw"] = ",".join(keywords)
                    elif "kw" in st.query_params:
                        del st.query_params["kw"]
                    st.rerun()

            if not keywords:
                st.markdown(
                    f"<p style='font-family:\"Inter\",sans-serif;"
                    f"color:{T['muted']};font-size:0.72rem;font-style:italic'>None set.</p>",
                    unsafe_allow_html=True,
                )

            st.divider()

            if st.button("↺  Refresh data", use_container_width=True):
                st.cache_data.clear()
                st.rerun()

        else:
            # Pre-login: nothing else in sidebar
            selected_year = "All years"
            keywords = st.session_state.settings.get("keywords", [])

    # ── Pre-login main content ────────────────────────────────────────────────
    if not logged_in:
        # Header
        st.markdown(
            f"<div style='padding:48px 0 8px'>"
            f"<div style='font-family:\"Inter\",sans-serif;"
            f"font-size:1.55rem;font-weight:700;color:{T['text']};line-height:1.1;"
            f"letter-spacing:-0.03em'>Kalshi PnL Dashboard</div>"
            f"<p style='font-family:\"Inter\",sans-serif;font-size:0.88rem;font-weight:400;"
            f"color:{T['muted']};margin-top:10px;line-height:1.65'>"
            f"Analyze realized PnL by trade, market, month, and year.</p></div>",
            unsafe_allow_html=True,
        )

        st.markdown("<div style='margin-top:32px'></div>", unsafe_allow_html=True)

        col_left, col_right = st.columns([3, 2], gap="large")

        with col_left:
            # Connect card — uses .connect-card CSS class (gradient top hairline, multi-shadow)
            st.markdown(
                f"<div class='connect-card'>"
                f"<div style='font-family:\"Inter\",sans-serif;"
                f"font-size:1rem;font-weight:600;color:{T['text']};letter-spacing:-0.01em'>"
                f"Connect your Kalshi account</div>"
                f"<p style='font-family:\"Inter\",sans-serif;font-size:0.78rem;font-weight:400;"
                f"color:{T['muted']};margin-top:6px;margin-bottom:22px;line-height:1.65'>"
                f"Go to kalshi.com → Settings → API to generate your key pair.</p>",
                unsafe_allow_html=True,
            )

            key_id = st.text_input("API Key ID", placeholder="key_xxxxxxxxxxxx")
            pem = st.text_area(
                "Private Key (PEM)",
                placeholder="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----",
                height=140,
            )

            if st.button("Connect to Kalshi", type="primary", use_container_width=True):
                if not key_id.strip() or not pem.strip():
                    st.error("Both fields are required.")
                elif not pem.strip().startswith("-----BEGIN"):
                    st.error(
                        "Private key must start with -----BEGIN RSA PRIVATE KEY----- "
                        "or -----BEGIN PRIVATE KEY-----"
                    )
                else:
                    with st.spinner("Connecting…"):
                        try:
                            serialization.load_pem_private_key(pem.strip().encode(), password=None)
                            st.session_state.creds = {
                                "type": "rsa",
                                "key_id": key_id.strip(),
                                "private_key_pem": pem.strip(),
                            }
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Invalid private key: {e}")

            st.markdown("</div>", unsafe_allow_html=True)

        with col_right:
            # Security card — uses .info-card CSS class
            st.markdown(
                f"<div class='info-card' style='margin-bottom:14px'>"
                f"<div style='font-family:\"Inter\",sans-serif;"
                f"font-size:0.78rem;font-weight:600;color:{T['text']};letter-spacing:-0.01em;"
                f"margin-bottom:14px'>🔒 Security</div>"
                f"<ul style='font-family:\"Inter\",sans-serif;font-size:0.78rem;font-weight:400;"
                f"color:{T['soft']};line-height:2;margin:0 0 12px;padding-left:16px'>"
                f"<li>Your private key is never stored to disk</li>"
                f"<li>Lives in your browser session only</li>"
                f"<li>All requests signed locally, in-memory</li>"
                f"<li>Refresh the page to clear credentials</li>"
                f"<li>Open source — <a href='https://github.com/kevinhjshim/kalshi-pnl' "
                f"target='_blank' style='color:{T['accent']};text-decoration:none;"
                f"font-weight:500'>review the code ↗</a></li>"
                f"</ul>"
                f"</div>",
                unsafe_allow_html=True,
            )

            # Preview card
            st.markdown(
                f"<div class='info-card'>"
                f"<div style='font-family:\"Inter\",sans-serif;"
                f"font-size:0.78rem;font-weight:600;color:{T['text']};letter-spacing:-0.01em;"
                f"margin-bottom:14px'>After connecting you'll get</div>"
                f"<ul style='font-family:\"Inter\",sans-serif;font-size:0.78rem;font-weight:400;"
                f"color:{T['soft']};line-height:2.1;margin:0;padding-left:0;list-style:none'>"
                f"<li><span style='color:{T['accent']};margin-right:8px'>✦</span>Total realized PnL</li>"
                f"<li><span style='color:{T['accent']};margin-right:8px'>✦</span>Monthly &amp; yearly breakdown</li>"
                f"<li><span style='color:{T['accent']};margin-right:8px'>✦</span>Per-trade cost, entry price, W/L</li>"
                f"<li><span style='color:{T['accent']};margin-right:8px'>✦</span>Exclude trades placed for others</li>"
                f"</ul>"
                f"</div>",
                unsafe_allow_html=True,
            )

        return

    # ── Post-login: fetch & render ────────────────────────────────────────────
    creds     = st.session_state.creds
    creds_key = creds.get("key_id") or "bearer"

    settlements, err = fetch_all_settlements(creds_key, creds)
    if err:
        st.error(f"Could not fetch data: {err}")
        if st.button("Logout and retry"):
            st.session_state.creds = None
            st.cache_data.clear()
            st.rerun()
        return

    if not settlements:
        st.info("No settled trades found yet.")
        return

    df = process_settlements(settlements, creds_key, creds)
    if df.empty:
        st.warning("No processable data.")
        return

    st.session_state.full_df  = df
    st.session_state.all_years = sorted(df["year"].unique().tolist())

    view_df = df[df["year"] == int(selected_year)].copy() if selected_year != "All years" else df.copy()
    included, excluded = split_by_exclusions(view_df, keywords)

    if included.empty:
        st.warning("All trades are excluded by your filters.")
        return

    # ── Header & metrics ──────────────────────────────────────────────────────
    total_pnl  = included["pnl"].sum()
    n          = len(included)
    wins       = int((included["pnl"] > 0).sum())
    total_fees = included["fee"].sum()
    avg_pnl    = included["pnl"].mean()
    pnl_color  = T["profit"] if total_pnl >= 0 else T["loss"]
    pnl_sign   = "+" if total_pnl >= 0 else ""

    # Large PnL number — text-shadow glow in profit/loss color for depth
    st.markdown(
        f"<div style='padding:10px 0 4px'>"
        f"<div style='font-family:\"Inter\",sans-serif;"
        f"font-size:3rem;font-weight:800;color:{pnl_color};line-height:1;"
        f"letter-spacing:-0.04em;"
        f"text-shadow:0 0 48px {pnl_color}33'>{pnl_sign}${total_pnl:,.2f}</div>"
        f"<div style='font-family:\"JetBrains Mono\",monospace;font-size:0.62rem;"
        f"font-weight:400;color:{T['muted']};letter-spacing:0.12em;margin-top:8px'>"
        f"{selected_year.upper()} &nbsp;·&nbsp; {n:,} SETTLED MARKETS</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div style='margin-top:18px'></div>", unsafe_allow_html=True)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.markdown(metric_card("Win Rate",    f"{wins/n*100:.1f}%",   f"{wins}W / {n-wins}L", T), unsafe_allow_html=True)
    c2.markdown(metric_card("Avg / Trade", f"${avg_pnl:,.2f}",    "", T,
                            accent=T["profit"] if avg_pnl >= 0 else T["loss"],
                            value_color=T["profit"] if avg_pnl >= 0 else T["loss"]), unsafe_allow_html=True)
    c3.markdown(metric_card("Best Trade",  f"${included['pnl'].max():,.2f}", "", T,
                            accent=T["profit"], value_color=T["profit"]), unsafe_allow_html=True)
    c4.markdown(metric_card("Worst Trade", f"${included['pnl'].min():,.2f}", "", T,
                            accent=T["loss"], value_color=T["loss"]),   unsafe_allow_html=True)
    c5.markdown(metric_card("Total Fees",  f"${total_fees:,.2f}",  "", T,
                            accent=T["muted"]), unsafe_allow_html=True)

    if not excluded.empty:
        excl_pnl = excluded["pnl"].sum()
        st.markdown(
            f"<div style='background:{T['card']};border:1px solid {T['border']};"
            f"border-left:2px solid {T['warn']};border-radius:0 8px 8px 0;"
            f"padding:10px 16px;margin-top:14px;"
            f"box-shadow:0 1px 6px rgba(0,0,0,0.12)'>"
            f"<span style='font-family:\"Inter\",sans-serif;font-size:0.75rem;"
            f"color:{T['muted']}'>"
            f"{len(excluded)} markets excluded &nbsp;·&nbsp; "
            f"excl. PnL: <span style='color:{T['warn']};font-weight:600'>${excl_pnl:,.2f}</span>"
            f" &nbsp;·&nbsp; grand total: <span style='color:{T['text']};font-weight:600'>"
            f"${view_df['pnl'].sum():,.2f}</span>"
            f"</span></div>",
            unsafe_allow_html=True,
        )

    st.markdown("<div style='margin-top:22px'></div>", unsafe_allow_html=True)

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_mo, tab_yr, tab_all = st.tabs(["  Monthly  ", "  Yearly  ", "  All Trades  "])

    with tab_mo:
        mo_data = (
            included.groupby(["year_month", "month_label"])
            .agg(pnl=("pnl", "sum"), markets=("ticker", "count"),
                 wins=("pnl", lambda x: (x > 0).sum()))
            .reset_index().sort_values("year_month")
        )
        mo_data["month_label"] = mo_data["year_month"].apply(lambda p: p.strftime("%b %Y"))
        st.plotly_chart(pnl_bar_chart(mo_data, "month_label", "Monthly PnL", T), use_container_width=True)
        st.markdown(html_table(build_monthly_df(included), T), unsafe_allow_html=True)

    with tab_yr:
        yr_data = (
            included.groupby("year")
            .agg(pnl=("pnl", "sum"), markets=("ticker", "count"),
                 wins=("pnl", lambda x: (x > 0).sum()))
            .reset_index().sort_values("year")
        )
        yr_data["year_label"] = yr_data["year"].astype(str)
        st.plotly_chart(pnl_bar_chart(yr_data, "year_label", "Yearly PnL", T), use_container_width=True)
        st.markdown(html_table(build_yearly_df(included), T), unsafe_allow_html=True)

    with tab_all:
        col_srch, col_sort = st.columns([3, 1])
        search  = col_srch.text_input("s", placeholder="Search market or ticker…",
                                      label_visibility="collapsed")
        sort_by = col_sort.selectbox("o", ["Newest", "Biggest loss", "Biggest win"],
                                     label_visibility="collapsed")

        view = included.copy()
        if search.strip():
            m = (
                view["title"].str.contains(search, case=False, na=False, regex=False)
                | view["ticker"].str.contains(search, case=False, na=False, regex=False)
            )
            view = view[m]

        view = view.sort_values(
            "settled_time" if sort_by == "Newest" else "pnl",
            ascending=(sort_by == "Biggest loss"),
        )

        st.markdown(
            f"<p style='font-family:\"JetBrains Mono\",monospace;color:{T['muted']};"
            f"font-size:0.72rem;margin-bottom:8px'>{len(view):,} trades</p>",
            unsafe_allow_html=True,
        )
        st.markdown(html_table(build_trade_df(view), T), unsafe_allow_html=True)

        if not excluded.empty:
            st.divider()
            with st.expander(
                f"Excluded trades ({len(excluded)})  ·  PnL: ${excluded['pnl'].sum():,.2f}"
            ):
                excl_view = excluded.sort_values("settled_time", ascending=False)
                st.markdown(html_table(build_trade_df(excl_view), T), unsafe_allow_html=True)


if __name__ == "__main__":
    main()
