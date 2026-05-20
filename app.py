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

# ── Kalshi-inspired palette ───────────────────────────────────────────────────
C_BG        = "#0B0E13"
C_SURFACE   = "#111418"
C_CARD      = "#161B22"
C_BORDER    = "#21262D"
C_BORDER2   = "#30363D"
C_TEXT      = "#F0F6FC"
C_MUTED     = "#8B949E"
C_GREEN     = "#3FB950"
C_RED       = "#F85149"
C_BLUE      = "#58A6FF"
C_YELLOW    = "#D29922"

THEME_CSS = f"""
<style>
/* ── Base ── */
html, .stApp, [data-testid="stAppViewContainer"] {{
    background-color: {C_BG} !important;
    color: {C_TEXT};
}}
[data-testid="stHeader"] {{ background-color: {C_BG} !important; }}

/* ── Sidebar ── */
[data-testid="stSidebar"] {{
    background-color: {C_SURFACE} !important;
    border-right: 1px solid {C_BORDER};
}}
[data-testid="stSidebar"] * {{ color: {C_TEXT}; }}
[data-testid="collapsedControl"] {{
    background-color: {C_SURFACE} !important;
    border-right: 1px solid {C_BORDER};
    color: {C_MUTED} !important;
}}

/* ── Metrics ── */
[data-testid="stMetric"] {{
    background-color: {C_CARD};
    border: 1px solid {C_BORDER};
    border-radius: 10px;
    padding: 16px 20px !important;
}}
[data-testid="stMetricLabel"] > div {{
    color: {C_MUTED} !important;
    font-size: 0.7rem !important;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 500;
}}
[data-testid="stMetricValue"] {{
    color: {C_TEXT} !important;
    font-size: 1.45rem !important;
    font-weight: 600;
}}
[data-testid="stMetricDelta"] {{ font-size: 0.75rem !important; }}

/* ── Buttons ── */
.stButton > button {{
    background-color: {C_CARD};
    color: {C_TEXT};
    border: 1px solid {C_BORDER2};
    border-radius: 6px;
    font-size: 0.85rem;
    transition: all 0.15s;
}}
.stButton > button:hover {{
    background-color: {C_BORDER2};
    border-color: {C_MUTED};
}}
.stButton > button[kind="primary"] {{
    background-color: {C_BLUE};
    border-color: {C_BLUE};
    color: #fff;
    font-weight: 600;
}}
.stButton > button[kind="primary"]:hover {{
    background-color: #79b8ff;
    border-color: #79b8ff;
}}

/* ── Inputs ── */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea,
.stSelectbox > div > div > div {{
    background-color: {C_CARD} !important;
    border: 1px solid {C_BORDER2} !important;
    color: {C_TEXT} !important;
    border-radius: 6px;
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
    padding: 8px 16px;
    font-size: 0.875rem;
    font-weight: 500;
}}
.stTabs [aria-selected="true"] {{
    background: transparent !important;
    color: {C_TEXT} !important;
    border-bottom-color: {C_BLUE} !important;
}}
.stTabs [data-baseweb="tab-panel"] {{
    padding-top: 20px;
}}

/* ── Expanders ── */
[data-testid="stExpander"] {{
    background-color: {C_CARD};
    border: 1px solid {C_BORDER};
    border-radius: 8px;
}}
[data-testid="stExpander"] summary {{
    color: {C_TEXT};
}}

/* ── Divider ── */
hr {{ border-color: {C_BORDER} !important; margin: 12px 0; }}

/* ── Code / tags ── */
code {{
    background-color: {C_CARD} !important;
    color: {C_BLUE} !important;
    border: 1px solid {C_BORDER} !important;
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 0.8rem;
}}

/* ── Alerts / info ── */
[data-testid="stAlert"] {{
    background-color: {C_CARD} !important;
    border: 1px solid {C_BORDER} !important;
    border-radius: 8px;
    color: {C_TEXT} !important;
}}

/* ── Dataframe ── */
[data-testid="stDataFrame"] {{
    border: 1px solid {C_BORDER};
    border-radius: 8px;
    overflow: hidden;
}}

/* ── Caption / small text ── */
[data-testid="stCaptionContainer"] {{ color: {C_MUTED}; font-size: 0.8rem; }}

/* ── Radio ── */
.stRadio [data-testid="stMarkdownContainer"] p {{ color: {C_TEXT}; font-size: 0.85rem; }}

/* ── Scrollbar ── */
::-webkit-scrollbar {{ width: 6px; height: 6px; }}
::-webkit-scrollbar-track {{ background: {C_BG}; }}
::-webkit-scrollbar-thumb {{ background: {C_BORDER2}; border-radius: 3px; }}
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
    return dict(
        title=dict(text=title, font=dict(color=C_TEXT, size=15)),
        height=420,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=C_MUTED),
        yaxis=dict(
            title="PnL ($)",
            zeroline=True,
            zerolinecolor=C_BORDER2,
            gridcolor=C_BORDER,
            tickfont=dict(color=C_MUTED),
        ),
        yaxis2=dict(
            title="Cumulative ($)",
            overlaying="y",
            side="right",
            gridcolor="rgba(0,0,0,0)",
            tickfont=dict(color=C_BLUE),
        ),
        xaxis=dict(showgrid=False, tickfont=dict(color=C_MUTED)),
        hovermode="x unified",
        hoverlabel=dict(bgcolor=C_CARD, bordercolor=C_BORDER, font=dict(color=C_TEXT)),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
            font=dict(color=C_MUTED), bgcolor="rgba(0,0,0,0)",
        ),
        margin=dict(t=55, b=40, l=10, r=10),
    )


def pnl_bar_chart(grouped: pd.DataFrame, x_col: str, title: str) -> go.Figure:
    grouped = grouped.copy()
    grouped["cumulative"] = grouped["pnl"].cumsum()
    colors = [C_GREEN if v >= 0 else C_RED for v in grouped["pnl"]]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=grouped[x_col], y=grouped["pnl"],
        marker_color=colors, marker_line_width=0,
        name="PnL",
        text=grouped["pnl"].apply(lambda v: f"${v:,.2f}"),
        textposition="outside",
        textfont=dict(color=C_MUTED, size=11),
        hovertemplate="<b>%{x}</b><br>PnL: $%{y:,.2f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=grouped[x_col], y=grouped["cumulative"],
        mode="lines+markers", name="Cumulative",
        line=dict(color=C_BLUE, width=2, dash="dot"),
        marker=dict(size=5, color=C_BLUE),
        yaxis="y2",
        hovertemplate="<b>%{x}</b><br>Cumulative: $%{y:,.2f}<extra></extra>",
    ))
    fig.update_layout(**_plotly_layout(title))
    return fig


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
            f"<h2 style='color:{C_TEXT};font-size:1.2rem;font-weight:700;"
            f"letter-spacing:0.02em;margin-bottom:4px'>📈 Kalshi PnL</h2>"
            f"<p style='color:{C_MUTED};font-size:0.72rem;margin-top:0'>Profit & Loss Dashboard</p>",
            unsafe_allow_html=True,
        )
        st.divider()

        # ── Auth ──
        if not st.session_state.creds:
            st.markdown(f"<p style='color:{C_MUTED};font-size:0.75rem;font-weight:600;"
                        f"text-transform:uppercase;letter-spacing:0.08em'>Login</p>",
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
                f"border-radius:8px;padding:10px 14px;margin-bottom:8px'>"
                f"<span style='color:{C_GREEN};font-size:0.8rem'>● Connected</span></div>",
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
            f"<p style='color:{C_MUTED};font-size:0.75rem;font-weight:600;"
            f"text-transform:uppercase;letter-spacing:0.08em'>Exclusions</p>"
            f"<p style='color:{C_MUTED};font-size:0.75rem;line-height:1.4;margin-bottom:8px'>"
            f"Exclude trades from PnL — useful for trades placed on behalf of someone else.</p>",
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
            label = f"`{kw}`" + (f" _{count} trades_" if count else "")
            c1.markdown(
                f"<div style='background:{C_CARD};border:1px solid {C_BORDER};"
                f"border-radius:6px;padding:5px 10px;font-size:0.8rem;color:{C_TEXT}'>"
                f"<span style='color:{C_BLUE}'>{kw}</span>"
                f"<span style='color:{C_MUTED};float:right'>{count} trades</span></div>",
                unsafe_allow_html=True,
            )
            if c2.button("×", key=f"rm_{i}", help="Remove"):
                keywords.pop(i)
                st.session_state.exclusions["keywords"] = keywords
                save_exclusions(st.session_state.exclusions)
                st.rerun()

        if not keywords:
            st.markdown(f"<p style='color:{C_MUTED};font-size:0.78rem;font-style:italic'>"
                        f"No exclusions set.</p>", unsafe_allow_html=True)

        st.divider()

        # ── Filters ──
        st.markdown(f"<p style='color:{C_MUTED};font-size:0.75rem;font-weight:600;"
                    f"text-transform:uppercase;letter-spacing:0.08em'>Filters</p>",
                    unsafe_allow_html=True)
        all_years: list = st.session_state.get("all_years", [])
        year_opts = ["All years"] + [str(y) for y in sorted(all_years, reverse=True)]
        selected_year = st.selectbox("Year", year_opts, label_visibility="collapsed")

        st.divider()
        if st.button("↺  Refresh data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        st.markdown(
            f"<p style='color:{C_MUTED};font-size:0.68rem;margin-top:8px;text-align:center'>"
            f"Use the ‹ arrow to collapse this panel</p>",
            unsafe_allow_html=True,
        )

    # ── Main content ──────────────────────────────────────────────────────────
    if not st.session_state.creds:
        st.markdown(
            f"<h1 style='color:{C_TEXT};font-size:2rem;font-weight:700'>📈 Kalshi PnL</h1>"
            f"<p style='color:{C_MUTED};font-size:1rem'>Track your prediction market profits & losses.</p>",
            unsafe_allow_html=True,
        )
        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(
                f"<div style='background:{C_CARD};border:1px solid {C_BORDER};border-radius:10px;"
                f"padding:24px'>"
                f"<h3 style='color:{C_TEXT};font-size:1rem;margin-top:0'>Getting Started</h3>"
                f"<ol style='color:{C_MUTED};font-size:0.875rem;line-height:1.8'>"
                f"<li>Log in at <b style='color:{C_TEXT}'>kalshi.com</b></li>"
                f"<li>Go to <b style='color:{C_TEXT}'>Account → Settings → API</b></li>"
                f"<li>Click <b style='color:{C_TEXT}'>Create API Key</b></li>"
                f"<li>Paste your <b style='color:{C_TEXT}'>Key ID</b> and <b style='color:{C_TEXT}'>"
                f"Private Key</b> in the sidebar</li>"
                f"</ol>"
                f"<p style='color:{C_MUTED};font-size:0.75rem;margin-bottom:0'>"
                f"Your private key is only used to sign API requests and is never stored to disk.</p>"
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

    # ── Header row ────────────────────────────────────────────────────────────
    st.markdown(
        f"<h1 style='color:{C_TEXT};font-size:1.6rem;font-weight:700;"
        f"margin-bottom:2px'>Profit & Loss</h1>"
        f"<p style='color:{C_MUTED};font-size:0.85rem;margin-top:0'>"
        f"{selected_year} · {len(included):,} settled markets</p>",
        unsafe_allow_html=True,
    )

    # ── Metrics ───────────────────────────────────────────────────────────────
    total_pnl = included["pnl"].sum()
    n = len(included)
    wins = int((included["pnl"] > 0).sum())
    total_fees = included["fee"].sum()

    c1, c2, c3, c4, c5 = st.columns(5)
    pnl_color = C_GREEN if total_pnl >= 0 else C_RED
    c1.metric("Total PnL",    f"${total_pnl:,.2f}")
    c2.metric("Markets",      f"{n:,}")
    c3.metric("Win Rate",     f"{wins/n*100:.1f}%",  f"{wins}W / {n-wins}L")
    c4.metric("Avg / Trade",  f"${included['pnl'].mean():,.2f}")
    c5.metric("Total Fees",   f"${total_fees:,.2f}")

    if not excluded.empty:
        st.markdown(
            f"<div style='background:{C_CARD};border:1px solid {C_BORDER};border-radius:8px;"
            f"padding:10px 16px;margin-top:8px;font-size:0.82rem;color:{C_MUTED}'>"
            f"📌 <b style='color:{C_TEXT}'>{len(excluded)} markets excluded</b> · "
            f"Excluded PnL: <b style='color:{C_YELLOW}'>${excluded['pnl'].sum():,.2f}</b> · "
            f"Grand total (inc. excluded): <b style='color:{C_TEXT}'>${view_df['pnl'].sum():,.2f}</b>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown("<div style='margin-top:20px'></div>", unsafe_allow_html=True)

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
