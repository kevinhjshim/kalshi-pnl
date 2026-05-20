"""Kalshi PnL Dashboard — track realized profits/losses per month and year."""

from __future__ import annotations

import base64
import json
import os
import time

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

KALSHI_API_BASE = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_API_PATH_PREFIX = "/trade-api/v2"
EXCLUSIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exclusions.json")


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
    """Build Kalshi RSA-signed request headers."""
    ts = str(int(time.time() * 1000))
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode() if isinstance(private_key_pem, str) else private_key_pem,
        password=None,
    )
    message = (ts + method.upper() + path.split("?")[0]).encode()
    sig = private_key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "Content-Type": "application/json",
    }


def email_login(email: str, password: str) -> tuple[str | None, str | None]:
    """Login with email/password and return (token, error)."""
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


def bearer_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def make_headers(creds: dict, method: str, path: str) -> dict:
    """Build headers from whatever credentials are stored in session."""
    if creds["type"] == "rsa":
        return rsa_headers(creds["key_id"], creds["private_key_pem"], method, path)
    return bearer_headers(creds["token"])


# ── API calls ─────────────────────────────────────────────────────────────────

def _get(path: str, creds: dict, params: dict | None = None) -> requests.Response:
    url = KALSHI_API_BASE + path
    full_path = KALSHI_API_PATH_PREFIX + path  # used for RSA signature
    headers = make_headers(creds, "GET", full_path)
    return requests.get(url, headers=headers, params=params, timeout=20)


@st.cache_data(ttl=300, show_spinner="Fetching settlements…")
def fetch_all_settlements(creds_key: str, creds: dict) -> tuple[list, str | None]:
    settlements = []
    cursor = None
    path = "/portfolio/settlements"
    while True:
        params: dict = {"limit": 1000}
        if cursor:
            params["cursor"] = cursor
        try:
            resp = _get(path, creds, params)
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


@st.cache_data(ttl=3600, show_spinner="Fetching market titles…")
def fetch_market_titles(creds_key: str, creds: dict, tickers: tuple) -> dict:
    title_map: dict = {}
    tickers_list = list(tickers)
    for i in range(0, len(tickers_list), 200):
        batch = tickers_list[i : i + 200]
        try:
            resp = _get("/markets", creds, {"tickers": ",".join(batch), "limit": 200})
            if resp.status_code == 200:
                for m in resp.json().get("markets", []):
                    title_map[m["ticker"]] = m.get("title", m["ticker"])
        except Exception:
            pass
    for t in tickers_list:
        title_map.setdefault(t, t)
    return title_map


# ── Data processing ───────────────────────────────────────────────────────────

def process_settlements(settlements: list, creds_key: str, creds: dict) -> pd.DataFrame:
    rows = []
    for s in settlements:
        ticker = s.get("ticker", "")
        revenue = s.get("revenue", 0) / 100
        cost = (s.get("yes_total_cost", 0) + s.get("no_total_cost", 0)) / 100
        rows.append(
            {
                "ticker": ticker,
                "settled_time": s.get("settled_time", ""),
                "revenue": revenue,
                "cost": cost,
                "pnl": revenue - cost,
                "result": (s.get("market_result") or "").upper(),
                "yes_count": s.get("yes_count", 0),
                "no_count": s.get("no_count", 0),
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["settled_time"] = pd.to_datetime(df["settled_time"], utc=True, errors="coerce")
    df = df.dropna(subset=["settled_time"])
    df["settled_time"] = df["settled_time"].dt.tz_localize(None)
    df["year"] = df["settled_time"].dt.year
    df["year_month"] = df["settled_time"].dt.to_period("M")
    df["month_label"] = df["year_month"].apply(lambda p: p.strftime("%b %Y"))
    df = df.sort_values("settled_time").reset_index(drop=True)

    unique_tickers = tuple(sorted(df["ticker"].unique()))
    title_map = fetch_market_titles(creds_key, creds, unique_tickers)
    df["title"] = df["ticker"].map(title_map)
    return df


def split_by_exclusions(df: pd.DataFrame, keywords: list) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty or not keywords:
        return df, pd.DataFrame()
    mask = pd.Series(False, index=df.index)
    for kw in keywords:
        kw = kw.strip()
        if kw:
            mask |= df["title"].str.contains(kw, case=False, na=False, regex=False)
            mask |= df["ticker"].str.contains(kw, case=False, na=False, regex=False)
    return df[~mask].copy(), df[mask].copy()


# ── Charts ────────────────────────────────────────────────────────────────────

def pnl_bar_chart(grouped: pd.DataFrame, x_col: str, title: str) -> go.Figure:
    grouped = grouped.copy()
    grouped["cumulative"] = grouped["pnl"].cumsum()
    colors = grouped["pnl"].apply(lambda v: "#10B981" if v >= 0 else "#EF4444")

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=grouped[x_col],
            y=grouped["pnl"],
            marker_color=colors,
            name="PnL",
            text=grouped["pnl"].apply(lambda v: f"${v:,.2f}"),
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>PnL: $%{y:,.2f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=grouped[x_col],
            y=grouped["cumulative"],
            mode="lines+markers",
            name="Cumulative",
            line=dict(color="#818CF8", width=2, dash="dot"),
            marker=dict(size=6),
            yaxis="y2",
            hovertemplate="<b>%{x}</b><br>Cumulative: $%{y:,.2f}<extra></extra>",
        )
    )
    fig.update_layout(
        title=title,
        height=430,
        yaxis=dict(title="PnL ($)", zeroline=True, zerolinecolor="#4B5563"),
        yaxis2=dict(title="Cumulative ($)", overlaying="y", side="right"),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=60, b=40),
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(showgrid=True, gridcolor="#374151")
    return fig


def format_trade_table(df: pd.DataFrame) -> pd.DataFrame:
    out = df[["settled_time", "ticker", "title", "result", "yes_count", "no_count", "cost", "revenue", "pnl"]].copy()
    out["settled_time"] = out["settled_time"].dt.strftime("%Y-%m-%d")
    out["cost"] = out["cost"].map("${:,.2f}".format)
    out["revenue"] = out["revenue"].map("${:,.2f}".format)
    out["pnl"] = out["pnl"].map("${:,.2f}".format)
    return out.rename(
        columns={
            "settled_time": "Date", "ticker": "Ticker", "title": "Market",
            "result": "Result", "yes_count": "YES", "no_count": "NO",
            "cost": "Cost", "revenue": "Revenue", "pnl": "PnL",
        }
    )


# ── App ───────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(page_title="Kalshi PnL", page_icon="📈", layout="wide")
    st.markdown("<style>[data-testid='stMetricValue']{font-size:1.5rem}</style>", unsafe_allow_html=True)
    st.title("📈 Kalshi PnL Dashboard")

    if "exclusions" not in st.session_state:
        st.session_state.exclusions = load_exclusions()
    if "creds" not in st.session_state:
        st.session_state.creds = None

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("Login")
        auth_mode = st.radio(
            "Method",
            ["API Key (RSA)", "Email / Password"],
            horizontal=True,
            label_visibility="collapsed",
        )

        if auth_mode == "API Key (RSA)":
            key_id = st.text_input("Key ID", placeholder="Paste your Key ID")
            private_key_pem = st.text_area(
                "Private Key (PEM)",
                placeholder="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----",
                height=160,
            )
            if st.button("Connect", type="primary", use_container_width=True):
                if not key_id.strip() or not private_key_pem.strip():
                    st.error("Both Key ID and Private Key are required.")
                else:
                    try:
                        # Validate key parses correctly
                        serialization.load_pem_private_key(
                            private_key_pem.strip().encode(), password=None
                        )
                        st.session_state.creds = {
                            "type": "rsa",
                            "key_id": key_id.strip(),
                            "private_key_pem": private_key_pem.strip(),
                        }
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Invalid private key: {e}")
        else:
            email = st.text_input("Email")
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

        if st.session_state.creds:
            st.success("Connected ✓")
            if st.button("Logout", use_container_width=True):
                st.session_state.creds = None
                st.cache_data.clear()
                st.rerun()

        st.divider()

        # Exclusions
        st.header("Exclusions")
        st.caption("Trades matching these keywords are excluded from PnL totals.")
        keywords: list = st.session_state.exclusions.get("keywords", [])

        col_a, col_b = st.columns([3, 1])
        new_kw = col_a.text_input("Keyword", placeholder="e.g. NBA, TRUMP", label_visibility="collapsed")
        if col_b.button("Add", use_container_width=True) and new_kw.strip():
            kw = new_kw.strip()
            if kw not in keywords:
                keywords.append(kw)
                st.session_state.exclusions["keywords"] = keywords
                save_exclusions(st.session_state.exclusions)
            st.rerun()

        for i, kw in enumerate(keywords[:]):
            c1, c2 = st.columns([4, 1])
            c1.code(kw, language=None)
            if c2.button("×", key=f"rm_{i}"):
                keywords.pop(i)
                st.session_state.exclusions["keywords"] = keywords
                save_exclusions(st.session_state.exclusions)
                st.rerun()

        if not keywords:
            st.caption("_No exclusions set._")

        st.divider()

        st.header("Filters")
        all_years: list = st.session_state.get("all_years", [])
        year_opts = ["All years"] + [str(y) for y in sorted(all_years, reverse=True)]
        selected_year = st.selectbox("Year", year_opts, label_visibility="collapsed")

        st.divider()
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    # ── Main content ──────────────────────────────────────────────────────────
    if not st.session_state.creds:
        st.info("👈 Log in to get started.")
        with st.expander("How to find your Kalshi API key"):
            st.markdown(
                """
**For Google SSO accounts (like yours):**
1. Log in at **kalshi.com**
2. Go to **Account → Settings → API**
3. Click **Create API Key**
4. Copy the **Key ID** and the **Private Key** (PEM text)
5. Paste both into the sidebar — select **API Key (RSA)** mode

The private key is only stored in your browser session and never sent anywhere except Kalshi's API.
"""
            )
        return

    creds = st.session_state.creds
    # Stable string used as cache key (avoids hashing the private key on every call)
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

    with st.expander("🔍 Raw settlement fields (debug — remove once confirmed)"):
        st.json(settlements[0])

    df = process_settlements(settlements, creds_key, creds)
    if df.empty:
        st.warning("No processable data.")
        return

    st.session_state.all_years = sorted(df["year"].unique().tolist())

    if selected_year != "All years":
        df = df[df["year"] == int(selected_year)].copy()

    included, excluded = split_by_exclusions(df, keywords)

    if included.empty:
        st.warning("All trades are excluded by the current filters.")
        return

    # Metrics
    total_pnl = included["pnl"].sum()
    n = len(included)
    wins = int((included["pnl"] > 0).sum())
    win_rate = wins / n * 100 if n else 0

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Total PnL", f"${total_pnl:,.2f}")
    c2.metric("Markets", f"{n:,}")
    c3.metric("Win Rate", f"{win_rate:.1f}%", f"{wins}W / {n - wins}L")
    c4.metric("Avg / Trade", f"${included['pnl'].mean():,.2f}")
    c5.metric("Best", f"${included['pnl'].max():,.2f}")
    c6.metric("Worst", f"${included['pnl'].min():,.2f}")

    if not excluded.empty:
        st.caption(
            f"📌 **{len(excluded)} markets excluded** · "
            f"Excluded PnL: **${excluded['pnl'].sum():,.2f}** · "
            f"Grand total (inc. excluded): **${df['pnl'].sum():,.2f}**"
        )

    st.divider()

    tab_mo, tab_yr, tab_all = st.tabs(["📅 Monthly", "📆 Yearly", "🗂️ All Trades"])

    with tab_mo:
        monthly = (
            included.groupby(["year_month", "month_label"])
            .agg(pnl=("pnl", "sum"), markets=("ticker", "count"), wins=("pnl", lambda x: (x > 0).sum()))
            .reset_index()
            .sort_values("year_month")
        )
        monthly["win_pct"] = (monthly["wins"] / monthly["markets"] * 100).round(1)
        st.plotly_chart(pnl_bar_chart(monthly, "month_label", "Monthly PnL"), use_container_width=True)

        tbl = monthly[["month_label", "pnl", "markets", "wins", "win_pct"]].copy()
        tbl["cumulative"] = tbl["pnl"].cumsum()
        tbl = tbl.iloc[::-1].reset_index(drop=True)
        tbl["pnl"] = tbl["pnl"].map("${:,.2f}".format)
        tbl["cumulative"] = tbl["cumulative"].map("${:,.2f}".format)
        tbl["win_pct"] = tbl["win_pct"].map("{:.1f}%".format)
        tbl.columns = ["Month", "PnL", "Markets", "Wins", "Win %", "Running Total"]
        st.dataframe(tbl, use_container_width=True, hide_index=True)

    with tab_yr:
        yearly = (
            included.groupby("year")
            .agg(pnl=("pnl", "sum"), markets=("ticker", "count"), wins=("pnl", lambda x: (x > 0).sum()))
            .reset_index()
            .sort_values("year")
        )
        yearly["win_pct"] = (yearly["wins"] / yearly["markets"] * 100).round(1)
        yearly["year_label"] = yearly["year"].astype(str)
        st.plotly_chart(pnl_bar_chart(yearly, "year_label", "Yearly PnL"), use_container_width=True)

        tbl_yr = yearly[["year_label", "pnl", "markets", "wins", "win_pct"]].copy()
        tbl_yr["cumulative"] = tbl_yr["pnl"].cumsum()
        tbl_yr = tbl_yr.iloc[::-1].reset_index(drop=True)
        tbl_yr["pnl"] = tbl_yr["pnl"].map("${:,.2f}".format)
        tbl_yr["cumulative"] = tbl_yr["cumulative"].map("${:,.2f}".format)
        tbl_yr["win_pct"] = tbl_yr["win_pct"].map("{:.1f}%".format)
        tbl_yr.columns = ["Year", "PnL", "Markets", "Wins", "Win %", "Running Total"]
        st.dataframe(tbl_yr, use_container_width=True, hide_index=True)

    with tab_all:
        st.subheader(f"Included trades ({len(included)})")
        search = st.text_input("🔍 Search by market title or ticker")
        view = included.sort_values("settled_time", ascending=False)
        if search.strip():
            mask = (
                view["title"].str.contains(search, case=False, na=False, regex=False)
                | view["ticker"].str.contains(search, case=False, na=False, regex=False)
            )
            view = view[mask]
        st.dataframe(format_trade_table(view), use_container_width=True, hide_index=True)

        if not excluded.empty:
            st.divider()
            with st.expander(f"🚫 Excluded trades ({len(excluded)}) — PnL: ${excluded['pnl'].sum():,.2f}"):
                st.dataframe(
                    format_trade_table(excluded.sort_values("settled_time", ascending=False)),
                    use_container_width=True,
                    hide_index=True,
                )


if __name__ == "__main__":
    main()
