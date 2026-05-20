"""Kalshi PnL Dashboard — track realized profits/losses per month and year."""

from __future__ import annotations

import base64
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

KALSHI_API_BASE = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_API_PATH_PREFIX = "/trade-api/v2"
EXCLUSIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exclusions.json")

# ── Night Market palette ──────────────────────────────────────────────────────
C_BG      = "#060606"
C_SURFACE = "#0E0E0E"
C_CARD    = "#161616"
C_BORDER  = "#282828"
C_BORDER2 = "#363636"
C_TEXT    = "#F2F2F2"
C_MUTED   = "#5E5E5E"
C_SOFT    = "#999999"
C_GOLD    = "#FFD60A"   # primary accent — vivid gold
C_PROFIT  = "#00D68F"   # electric mint green
C_LOSS    = "#FF4D4F"   # vivid red
C_LINE    = "#7B61FF"   # cumulative line — violet

THEME_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,300..800&family=JetBrains+Mono:ital,wght@0,300;0,400;0,500;1,300&display=swap');

/* ── Base ── */
html, body, .stApp, [data-testid="stAppViewContainer"] {{
    background-color: {C_BG} !important;
    color: {C_TEXT};
    font-family: 'Bricolage Grotesque', sans-serif;
}}
[data-testid="stHeader"] {{ background-color: {C_BG} !important; border-bottom: 1px solid {C_BORDER}; }}
p, li, span, div {{ font-family: 'Bricolage Grotesque', sans-serif; }}

/* ── Sidebar ── */
[data-testid="stSidebar"] {{
    background-color: {C_SURFACE} !important;
    border-right: 1px solid {C_BORDER};
}}
[data-testid="stSidebar"] * {{ color: {C_TEXT}; }}
[data-testid="collapsedControl"] {{
    background-color: {C_SURFACE} !important;
    border-right: 1px solid {C_BORDER};
}}

/* ── Buttons ── */
.stButton > button {{
    background-color: transparent;
    color: {C_SOFT};
    border: 1px solid {C_BORDER2};
    border-radius: 4px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.78rem;
    letter-spacing: 0.04em;
    transition: all 0.12s ease;
}}
.stButton > button:hover {{
    border-color: {C_GOLD};
    color: {C_GOLD};
    background-color: rgba(255,214,10,0.06);
}}
.stButton > button[kind="primary"] {{
    background-color: {C_GOLD};
    border-color: {C_GOLD};
    color: {C_BG};
    font-weight: 700;
}}
.stButton > button[kind="primary"]:hover {{
    background-color: #FFE040;
    border-color: #FFE040;
}}

/* ── Inputs ── */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea {{
    background-color: {C_CARD} !important;
    border: 1px solid {C_BORDER2} !important;
    color: {C_TEXT} !important;
    border-radius: 4px;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.82rem !important;
}}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {{
    border-color: {C_GOLD} !important;
    box-shadow: 0 0 0 2px rgba(255,214,10,0.15) !important;
}}
.stSelectbox > div > div {{
    background-color: {C_CARD} !important;
    border: 1px solid {C_BORDER2} !important;
    border-radius: 4px;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.82rem !important;
}}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {{
    border-color: {C_BLUE} !important;
    box-shadow: 0 0 0 2px rgba(88,166,255,0.2) !important;
}}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {{
    background: transparent;
    border-bottom: 1px solid {C_BORDER};
    gap: 0;
}}
.stTabs [data-baseweb="tab"] {{
    background: transparent;
    color: {C_MUTED};
    border-bottom: 2px solid transparent;
    padding: 10px 20px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
    font-weight: 400;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}}
.stTabs [aria-selected="true"] {{
    background: transparent !important;
    color: {C_GOLD} !important;
    border-bottom-color: {C_GOLD} !important;
}}
.stTabs [data-baseweb="tab-panel"] {{ padding-top: 24px; }}

/* ── Expanders ── */
[data-testid="stExpander"] {{
    background-color: {C_CARD};
    border: 1px solid {C_BORDER};
    border-radius: 4px;
}}
[data-testid="stExpander"] summary {{ color: {C_SOFT}; font-size: 0.82rem; }}

/* ── Divider ── */
hr {{ border-color: {C_BORDER} !important; margin: 16px 0; }}

/* ── Code / tags ── */
code {{
    background-color: {C_CARD} !important;
    color: {C_GOLD} !important;
    border: 1px solid {C_BORDER2} !important;
    border-radius: 3px;
    padding: 2px 7px;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.78rem;
}}

/* ── Alerts ── */
[data-testid="stAlert"] {{
    background-color: {C_CARD} !important;
    border: 1px solid {C_BORDER2} !important;
    border-radius: 4px;
    color: {C_SOFT} !important;
    font-size: 0.85rem;
}}

/* ── Dataframe ── */
[data-testid="stDataFrame"] {{
    border: 1px solid {C_BORDER};
    border-radius: 4px;
    overflow: hidden;
}}

/* ── Radio ── */
.stRadio label {{ font-size: 0.82rem !important; color: {C_SOFT} !important; }}
.stRadio [data-testid="stMarkdownContainer"] p {{ color: {C_SOFT}; font-size: 0.82rem; }}

/* ── Select ── */
[data-testid="stSelectbox"] label {{ color: {C_MUTED} !important; font-size: 0.72rem; }}

/* ── Scrollbar ── */
::-webkit-scrollbar {{ width: 4px; height: 4px; }}
::-webkit-scrollbar-track {{ background: {C_BG}; }}
::-webkit-scrollbar-thumb {{ background: {C_BORDER2}; border-radius: 2px; }}
::-webkit-scrollbar-thumb:hover {{ background: {C_MUTED}; }}
</style>
"""


# ── Persistence ───────────────────────────────────────────────────────────────

def load_exclusions() -> dict:
    if os.path.exists(EXCLUSIONS_FILE):
        try:
            with open(EXCLUSIONS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"keywords": []}


def save_exclusions(data: dict) -> None:
    with open(EXCLUSIONS_FILE, "w") as f:
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


@st.cache_data(ttl=3600, show_spinner="Resolving market titles…")
def fetch_market_titles(creds_key: str, creds: dict, tickers: tuple) -> dict:
    title_map: dict = {}
    tickers_list = list(tickers)

    # Batch fetch
    for i in range(0, len(tickers_list), 200):
        batch = tickers_list[i : i + 200]
        try:
            resp = _get("/markets", creds, {"tickers": ",".join(batch), "limit": 200})
            if resp.status_code == 200:
                for m in resp.json().get("markets", []):
                    title = m.get("title") or m.get("subtitle") or ""
                    if title:
                        title_map[m["ticker"]] = clean_title(title)
        except Exception:
            pass

    # Individual fallback for anything still missing
    missing = [t for t in tickers_list if t not in title_map]
    for t in missing[:60]:
        try:
            resp = _get(f"/markets/{t}", creds)
            if resp.status_code == 200:
                m = resp.json().get("market", {})
                title = m.get("title") or m.get("subtitle") or ""
                if title:
                    title_map[t] = clean_title(title)
        except Exception:
            pass

    # Ticker parser fallback for anything still missing
    for t in tickers_list:
        if t not in title_map:
            title_map[t] = parse_ticker(t)

    return title_map


# ── Ticker / title helpers ────────────────────────────────────────────────────

_SPORT_CODES = [
    ("NCAAFGAME", "NCAAF"),
    ("NCAAMGAME", "NCAAM"),
    ("NFLGAME",   "NFL"),
    ("NBAGAME",   "NBA"),
    ("NHLGAME",   "NHL"),
    ("MLBGAME",   "MLB"),
    ("NBACUP",    "NBA Cup"),
    ("NACUP",     "NBA Cup"),
]
_MONTHS = {
    "JAN": "Jan", "FEB": "Feb", "MAR": "Mar", "APR": "Apr",
    "MAY": "May", "JUN": "Jun", "JUL": "Jul", "AUG": "Aug",
    "SEP": "Sep", "OCT": "Oct", "NOV": "Nov", "DEC": "Dec",
}


def parse_ticker(ticker: str) -> str:
    """Convert a raw Kalshi ticker into a human-readable label."""
    t = ticker.upper()
    if not t.startswith("KX"):
        return ticker
    rest = t[2:]

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
                    mon_str = _MONTHS.get(mon, mon)
                    dd_int = int(dd)
                    return f"{sport} · {teams} · {result} wins ({mon_str} {dd_int}, 20{yy})"
            break

    return ticker


def clean_title(title: str) -> str:
    """Normalize API-returned titles to consistent sentence case."""
    title = title.strip()
    if not title:
        return title
    # If all-caps, convert to title case
    if title == title.upper() and len(title) > 4:
        title = title.title()
    # Trim trailing punctuation oddities
    title = title.rstrip(" -_")
    return title


# ── Data processing ───────────────────────────────────────────────────────────

def process_settlements(settlements: list, creds_key: str, creds: dict) -> pd.DataFrame:
    rows = []
    for s in settlements:
        ticker  = s.get("ticker", "")
        result  = (s.get("market_result") or "").lower()
        yes_cost = float(s.get("yes_total_cost_dollars", 0))
        no_cost  = float(s.get("no_total_cost_dollars",  0))
        fee      = float(s.get("fee_cost", 0))
        total_cost = yes_cost + no_cost + fee
        yes_count = float(s.get("yes_count_fp", 0))
        no_count  = float(s.get("no_count_fp",  0))

        if result == "yes":
            revenue = yes_count
        elif result == "no":
            revenue = no_count
        else:
            revenue = 0.0

        rows.append({
            "ticker":      ticker,
            "settled_time": s.get("settled_time", ""),
            "revenue":     revenue,
            "cost":        total_cost,
            "fee":         fee,
            "pnl":         revenue - total_cost,
            "result":      result.upper(),
            "yes_count":   yes_count,
            "no_count":    no_count,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["settled_time"] = pd.to_datetime(df["settled_time"], utc=True, errors="coerce")
    df = df.dropna(subset=["settled_time"])
    df["settled_time"] = df["settled_time"].dt.tz_localize(None)
    df["year"]       = df["settled_time"].dt.year
    df["year_month"] = df["settled_time"].dt.to_period("M")
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

def _plotly_layout(title: str) -> dict:
    mono = "JetBrains Mono, monospace"
    return dict(
        title=dict(
            text=title.upper(),
            font=dict(family=mono, color=C_MUTED, size=10),
            x=0, xanchor="left",
        ),
        height=400,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family=mono, color=C_MUTED, size=11),
        yaxis=dict(
            title="",
            zeroline=True, zerolinecolor=C_BORDER2, zerolinewidth=1,
            gridcolor=C_BORDER, gridwidth=1,
            tickfont=dict(family=mono, color=C_MUTED, size=10),
            tickprefix="$",
        ),
        yaxis2=dict(
            title="",
            overlaying="y", side="right",
            gridcolor="rgba(0,0,0,0)",
            tickfont=dict(family=mono, color=C_LINE, size=10),
            tickprefix="$",
        ),
        xaxis=dict(
            showgrid=False,
            tickfont=dict(family=mono, color=C_MUTED, size=10),
        ),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=C_CARD, bordercolor=C_BORDER2,
            font=dict(family=mono, color=C_TEXT, size=11),
        ),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
            font=dict(family=mono, color=C_MUTED, size=10),
            bgcolor="rgba(0,0,0,0)",
        ),
        margin=dict(t=36, b=32, l=4, r=4),
        bargap=0.35,
    )


def pnl_bar_chart(grouped: pd.DataFrame, x_col: str, title: str) -> go.Figure:
    grouped = grouped.copy()
    grouped["cumulative"] = grouped["pnl"].cumsum()

    fig = go.Figure()
    # Bars with per-bar color
    for _, row in grouped.iterrows():
        color = C_PROFIT if row["pnl"] >= 0 else C_LOSS
        fig.add_trace(go.Bar(
            x=[row[x_col]], y=[row["pnl"]],
            marker_color=color,
            marker_line_width=0,
            marker_opacity=0.85,
            showlegend=False,
            hovertemplate=f"<b>{row[x_col]}</b><br>PnL: ${row['pnl']:,.2f}<extra></extra>",
        ))

    # Cumulative line
    fig.add_trace(go.Scatter(
        x=grouped[x_col], y=grouped["cumulative"],
        mode="lines", name="cumulative",
        line=dict(color=C_LINE, width=1.5),
        yaxis="y2",
        hovertemplate="<b>%{x}</b><br>Running: $%{y:,.2f}<extra></extra>",
    ))

    # Zero line annotation-style fill for emphasis
    fig.add_hline(y=0, line_color=C_BORDER2, line_width=1, layer="below")

    layout = _plotly_layout(title)
    layout["showlegend"] = False
    fig.update_layout(**layout)
    return fig


def metric_card(label: str, value: str, sub: str = "",
                accent: str = C_GOLD, value_color: str = C_TEXT) -> str:
    sub_html = (f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.7rem;'
                f'color:{C_MUTED};margin-top:5px">{sub}</div>') if sub else ""
    return (
        f'<div style="background:{C_CARD};border:1px solid {C_BORDER};'
        f'border-top:2px solid {accent};border-radius:4px;padding:18px 20px 16px">'
        f'<div style="font-family:\'Bricolage Grotesque\',sans-serif;font-size:1.9rem;'
        f'font-weight:700;color:{value_color};line-height:1;letter-spacing:-0.02em">{value}</div>'
        f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.62rem;'
        f'color:{C_MUTED};text-transform:uppercase;letter-spacing:0.12em;margin-top:8px">{label}</div>'
        f'{sub_html}</div>'
    )


def format_trade_table(df: pd.DataFrame) -> pd.DataFrame:
    out = df[["settled_time", "ticker", "title", "result",
              "yes_count", "no_count", "fee", "cost", "revenue", "pnl"]].copy()
    out["settled_time"] = out["settled_time"].dt.strftime("%Y-%m-%d")
    for col in ("fee", "cost", "revenue", "pnl"):
        out[col] = out[col].map("${:,.2f}".format)
    return out.rename(columns={
        "settled_time": "Date", "ticker": "Ticker", "title": "Market",
        "result": "Result", "yes_count": "YES", "no_count": "NO",
        "fee": "Fees", "cost": "Cost", "revenue": "Revenue", "pnl": "PnL",
    })


# ── Summary table helpers ─────────────────────────────────────────────────────

def monthly_table(df: pd.DataFrame) -> pd.DataFrame:
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
    out["pnl"]        = out["pnl"].map("${:,.2f}".format)
    out["cumulative"] = out["cumulative"].map("${:,.2f}".format)
    out["win_pct"]    = out["win_pct"].map("{:.1f}%".format)
    out.columns = ["Month", "PnL", "Markets", "Wins", "Win %", "Running Total"]
    return out


def yearly_table(df: pd.DataFrame) -> pd.DataFrame:
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
    out["pnl"]        = out["pnl"].map("${:,.2f}".format)
    out["cumulative"] = out["cumulative"].map("${:,.2f}".format)
    out["win_pct"]    = out["win_pct"].map("{:.1f}%".format)
    out.columns = ["Year", "PnL", "Markets", "Wins", "Win %", "Running Total"]
    return out


# ── App ───────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="Kalshi PnL", page_icon="📈",
        layout="wide", initial_sidebar_state="expanded",
    )
    st.markdown(THEME_CSS, unsafe_allow_html=True)

    if "exclusions" not in st.session_state:
        st.session_state.exclusions = load_exclusions()
    if "creds" not in st.session_state:
        st.session_state.creds = None
    # All-time df for exclusion match counts (populated after first data load)
    if "full_df" not in st.session_state:
        st.session_state.full_df = pd.DataFrame()

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown(
            f"<div style='padding:4px 0 12px'>"
            f"<div style='font-family:\"Bricolage Grotesque\",sans-serif;font-size:1.15rem;"
            f"font-weight:800;color:{C_TEXT};letter-spacing:-0.01em'>KALSHI PNL</div>"
            f"<div style='font-family:\"JetBrains Mono\",monospace;font-size:0.62rem;"
            f"color:{C_MUTED};letter-spacing:0.14em;margin-top:2px'>PREDICTION MARKET TRACKER</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.divider()

        # ── Auth ──
        if not st.session_state.creds:
            st.markdown(f"<p style='font-family:\"JetBrains Mono\",monospace;color:{C_MUTED};"
                        f"font-size:0.62rem;font-weight:400;text-transform:uppercase;"
                        f"letter-spacing:0.14em;margin-bottom:8px'>LOGIN</p>",
                        unsafe_allow_html=True)
            auth_mode = st.radio("", ["API Key (RSA)", "Email / Password"],
                                 label_visibility="collapsed")

            if auth_mode == "API Key (RSA)":
                key_id = st.text_input("Key ID", placeholder="key_xxxxxxxxxxxxxxxx")
                pem = st.text_area(
                    "Private Key",
                    placeholder="-----BEGIN RSA PRIVATE KEY-----\n...",
                    height=140,
                )
                if st.button("Connect", type="primary", use_container_width=True):
                    if not key_id.strip() or not pem.strip():
                        st.error("Both fields are required.")
                    else:
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
            else:
                email    = st.text_input("Email")
                password = st.text_input("Password", type="password")
                if st.button("Login", type="primary", use_container_width=True):
                    with st.spinner("Authenticating…"):
                        token, err = email_login(email, password)
                    if token:
                        st.session_state.creds = {"type": "bearer", "token": token}
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(f"Login failed: {err}")
        else:
            st.markdown(
                f"<div style='background:{C_CARD};border:1px solid {C_BORDER};"
                f"border-top:1px solid {C_PROFIT};border-radius:4px;"
                f"padding:8px 14px;margin-bottom:10px'>"
                f"<span style='font-family:\"JetBrains Mono\",monospace;color:{C_PROFIT};"
                f"font-size:0.72rem;letter-spacing:0.08em'>● CONNECTED</span></div>",
                unsafe_allow_html=True,
            )
            if st.button("Logout", use_container_width=True):
                st.session_state.creds = None
                st.session_state.full_df = pd.DataFrame()
                st.cache_data.clear()
                st.rerun()

        st.divider()

        # ── Exclusions ──
        st.markdown(
            f"<p style='font-family:\"JetBrains Mono\",monospace;color:{C_MUTED};"
            f"font-size:0.62rem;text-transform:uppercase;letter-spacing:0.14em;"
            f"margin-bottom:4px'>Exclusions</p>"
            f"<p style='color:{C_MUTED};font-size:0.78rem;line-height:1.5;margin-bottom:10px'>"
            f"Filter trades out of your PnL — e.g. trades made for a friend.</p>",
            unsafe_allow_html=True,
        )

        keywords: list = st.session_state.exclusions.get("keywords", [])
        full_df = st.session_state.full_df

        col_a, col_b = st.columns([3, 1])
        new_kw = col_a.text_input(
            "kw", placeholder="e.g. NBA, NFL, TRUMP",
            label_visibility="collapsed", key="kw_input",
        )
        if col_b.button("Add", use_container_width=True, key="kw_add"):
            kw = new_kw.strip()
            if kw and kw not in keywords:
                keywords.append(kw)
                st.session_state.exclusions["keywords"] = keywords
                save_exclusions(st.session_state.exclusions)
                st.rerun()

        for i, kw in enumerate(keywords[:]):
            count = keyword_match_count(full_df, kw) if not full_df.empty else 0
            c1, c2 = st.columns([5, 1])
            c1.markdown(
                f"<div style='background:{C_CARD};border:1px solid {C_BORDER};"
                f"border-left:2px solid {C_GOLD};border-radius:0 4px 4px 0;"
                f"padding:6px 10px;margin-bottom:2px'>"
                f"<div style='font-family:\"JetBrains Mono\",monospace;font-size:0.78rem;"
                f"color:{C_TEXT}'>{kw}</div>"
                f"<div style='font-family:\"JetBrains Mono\",monospace;font-size:0.62rem;"
                f"color:{C_MUTED if count == 0 else C_LOSS}'>"
                f"{'no matches' if count == 0 else f'{count} trades excluded'}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            if c2.button("×", key=f"rm_{i}", help="Remove"):
                keywords.pop(i)
                st.session_state.exclusions["keywords"] = keywords
                save_exclusions(st.session_state.exclusions)
                st.rerun()

        if not keywords:
            st.markdown(
                f"<p style='font-family:\"JetBrains Mono\",monospace;color:{C_MUTED};"
                f"font-size:0.72rem;font-style:italic'>none set</p>",
                unsafe_allow_html=True,
            )

        st.divider()

        # ── Filters ──
        st.markdown(
            f"<p style='font-family:\"JetBrains Mono\",monospace;color:{C_MUTED};"
            f"font-size:0.62rem;text-transform:uppercase;letter-spacing:0.14em;"
            f"margin-bottom:8px'>Filters</p>",
            unsafe_allow_html=True,
        )
        all_years: list = st.session_state.get("all_years", [])
        year_opts = ["All years"] + [str(y) for y in sorted(all_years, reverse=True)]
        selected_year = st.selectbox("Year", year_opts, label_visibility="collapsed")

        st.divider()
        if st.button("↺  Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        st.markdown(
            f"<p style='font-family:\"JetBrains Mono\",monospace;color:{C_MUTED};"
            f"font-size:0.6rem;letter-spacing:0.06em;margin-top:6px;text-align:center'>"
            f"← collapse sidebar</p>",
            unsafe_allow_html=True,
        )

    # ── Main content ──────────────────────────────────────────────────────────
    if not st.session_state.creds:
        st.markdown(
            f"<div style='padding:40px 0 20px'>"
            f"<div style='font-family:\"Bricolage Grotesque\",sans-serif;font-size:3.2rem;"
            f"font-weight:800;color:{C_TEXT};line-height:1;letter-spacing:-0.03em'>"
            f"Track your<br><span style='color:{C_GOLD}'>edge.</span></div>"
            f"<div style='font-family:\"JetBrains Mono\",monospace;font-size:0.82rem;"
            f"color:{C_MUTED};margin-top:16px;line-height:1.6'>"
            f"Kalshi PnL — per trade, per month, per year.</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.divider()
        st.markdown(
            f"<div style='background:{C_CARD};border:1px solid {C_BORDER};"
            f"border-left:2px solid {C_GOLD};border-radius:0 4px 4px 0;padding:24px 28px;max-width:420px'>"
            f"<div style='font-family:\"JetBrains Mono\",monospace;font-size:0.65rem;"
            f"color:{C_MUTED};text-transform:uppercase;letter-spacing:0.14em;"
            f"margin-bottom:14px'>Getting started</div>"
            f"<ol style='color:{C_SOFT};font-size:0.85rem;line-height:2;margin:0;padding-left:18px'>"
            f"<li>Log in at <span style='color:{C_TEXT}'>kalshi.com</span></li>"
            f"<li>Go to <span style='color:{C_TEXT}'>Account → Settings → API</span></li>"
            f"<li>Click <span style='color:{C_GOLD}'>Create API Key</span></li>"
            f"<li>Paste your Key ID + Private Key in the sidebar</li>"
            f"</ol>"
            f"<div style='font-family:\"JetBrains Mono\",monospace;font-size:0.68rem;"
            f"color:{C_MUTED};margin-top:16px;border-top:1px solid {C_BORDER};"
            f"padding-top:12px'>Your private key never touches disk — used only to sign requests.</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        return

    creds = st.session_state.creds
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
        st.info("No settled trades found yet — markets appear here after they resolve.")
        return

    df = process_settlements(settlements, creds_key, creds)
    if df.empty:
        st.warning("No processable data.")
        return

    # Store full df for exclusion match counts in sidebar
    st.session_state.full_df = df
    st.session_state.all_years = sorted(df["year"].unique().tolist())

    # Apply year filter
    view_df = df[df["year"] == int(selected_year)].copy() if selected_year != "All years" else df.copy()

    # Apply exclusions
    keywords = st.session_state.exclusions.get("keywords", [])
    included, excluded = split_by_exclusions(view_df, keywords)

    if included.empty:
        st.warning("All trades in this period are excluded. Adjust your exclusion filters.")
        return

    # ── Header ────────────────────────────────────────────────────────────────
    total_pnl = included["pnl"].sum()
    n = len(included)
    wins = int((included["pnl"] > 0).sum())
    total_fees = included["fee"].sum()
    pnl_color = C_PROFIT if total_pnl >= 0 else C_LOSS
    pnl_sign  = "+" if total_pnl >= 0 else ""

    st.markdown(
        f"<div style='display:flex;align-items:baseline;gap:16px;padding:8px 0 4px'>"
        f"<div style='font-family:\"Bricolage Grotesque\",sans-serif;font-size:3rem;"
        f"font-weight:800;color:{pnl_color};line-height:1;letter-spacing:-0.03em'>"
        f"{pnl_sign}${total_pnl:,.2f}</div>"
        f"<div style='font-family:\"JetBrains Mono\",monospace;font-size:0.7rem;"
        f"color:{C_MUTED};letter-spacing:0.1em'>{selected_year.upper()} · {n:,} MARKETS</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── Metrics ───────────────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    avg = included["pnl"].mean()
    c1.markdown(metric_card("Win Rate",    f"{wins/n*100:.1f}%",   f"{wins}W  {n-wins}L"), unsafe_allow_html=True)
    c2.markdown(metric_card("Avg / Trade", f"${avg:,.2f}",         accent=C_PROFIT if avg >= 0 else C_LOSS, value_color=C_PROFIT if avg >= 0 else C_LOSS), unsafe_allow_html=True)
    c3.markdown(metric_card("Best Trade",  f"${included['pnl'].max():,.2f}", accent=C_PROFIT, value_color=C_PROFIT), unsafe_allow_html=True)
    c4.markdown(metric_card("Worst Trade", f"${included['pnl'].min():,.2f}", accent=C_LOSS,   value_color=C_LOSS),   unsafe_allow_html=True)
    c5.markdown(metric_card("Total Fees",  f"${total_fees:,.2f}",  accent=C_BORDER2),  unsafe_allow_html=True)

    if not excluded.empty:
        excl_pnl = excluded["pnl"].sum()
        st.markdown(
            f"<div style='background:{C_CARD};border:1px solid {C_BORDER};"
            f"border-left:2px solid {C_GOLD};border-radius:0 4px 4px 0;"
            f"padding:9px 14px;margin-top:10px'>"
            f"<span style='font-family:\"JetBrains Mono\",monospace;font-size:0.72rem;"
            f"color:{C_MUTED}'>"
            f"{len(excluded)} markets excluded  ·  "
            f"excl. PnL <span style='color:{C_GOLD}'>${excl_pnl:,.2f}</span>  ·  "
            f"grand total <span style='color:{C_TEXT}'>${view_df['pnl'].sum():,.2f}</span>"
            f"</span></div>",
            unsafe_allow_html=True,
        )

    st.markdown("<div style='margin-top:24px'></div>", unsafe_allow_html=True)

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
        st.plotly_chart(
            pnl_bar_chart(mo_data, "month_label", "Monthly PnL"),
            use_container_width=True,
        )
        st.dataframe(monthly_table(included), use_container_width=True, hide_index=True)

    with tab_yr:
        yr_data = (
            included.groupby("year")
            .agg(pnl=("pnl", "sum"), markets=("ticker", "count"),
                 wins=("pnl", lambda x: (x > 0).sum()))
            .reset_index().sort_values("year")
        )
        yr_data["year_label"] = yr_data["year"].astype(str)
        st.plotly_chart(
            pnl_bar_chart(yr_data, "year_label", "Yearly PnL"),
            use_container_width=True,
        )
        st.dataframe(yearly_table(included), use_container_width=True, hide_index=True)

    with tab_all:
        col_srch, col_sort = st.columns([3, 1])
        search = col_srch.text_input("🔍", placeholder="Search by market or ticker…",
                                     label_visibility="collapsed")
        sort_by = col_sort.selectbox("Sort", ["Newest first", "Largest loss", "Largest win"],
                                     label_visibility="collapsed")

        view = included.copy()
        if search.strip():
            mask = (
                view["title"].str.contains(search, case=False, na=False, regex=False)
                | view["ticker"].str.contains(search, case=False, na=False, regex=False)
            )
            view = view[mask]

        if sort_by == "Newest first":
            view = view.sort_values("settled_time", ascending=False)
        elif sort_by == "Largest loss":
            view = view.sort_values("pnl", ascending=True)
        else:
            view = view.sort_values("pnl", ascending=False)

        st.markdown(
            f"<p style='color:{C_MUTED};font-size:0.8rem;margin-bottom:6px'>"
            f"{len(view):,} trades shown</p>",
            unsafe_allow_html=True,
        )
        st.dataframe(format_trade_table(view), use_container_width=True, hide_index=True)

        if not excluded.empty:
            st.divider()
            with st.expander(
                f"🚫  Excluded trades ({len(excluded)}) · PnL: ${excluded['pnl'].sum():,.2f}"
            ):
                st.dataframe(
                    format_trade_table(excluded.sort_values("settled_time", ascending=False)),
                    use_container_width=True, hide_index=True,
                )


if __name__ == "__main__":
    main()
