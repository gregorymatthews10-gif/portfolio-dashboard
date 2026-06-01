"""
Portfolio dashboard — Streamlit + live yfinance prices.
Holdings/cost basis come from holdings.json (exported from My Portfolio_BUILT.xlsx);
current prices are fetched live on load. Falls back to last-known prices if a
fetch fails, so the page always renders.

Run locally:   streamlit run app.py
Deploy public: push this folder to GitHub, then deploy on streamlit.io (see README).
"""
import json, datetime
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="Greg's Portfolio", page_icon="📈", layout="wide")

NAVY="#1C2541"; GREEN="#007A33"; RED="#B81D13"
st.markdown(f"""<style>
.block-container{{padding-top:1.5rem;}}
h1,h2,h3{{color:{NAVY};}}
[data-testid="stMetricValue"]{{font-size:1.6rem;}}
</style>""", unsafe_allow_html=True)

@st.cache_data(ttl=300)
def load_holdings():
    return json.load(open("holdings.json"))

@st.cache_data(ttl=300)
def fetch_prices(tickers):
    """Live current + previous close from yfinance. Returns {tkr:(price,prev)} or {} on failure."""
    out = {}
    try:
        import yfinance as yf
        data = yf.download(tickers + ["IWM"], period="5d", progress=False, auto_adjust=True)["Close"]
        if isinstance(data, pd.Series):
            data = data.to_frame(tickers[0])
        for t in tickers + ["IWM"]:
            if t in data.columns:
                s = data[t].dropna()
                if len(s) >= 1:
                    cur = float(s.iloc[-1])
                    prev = float(s.iloc[-2]) if len(s) >= 2 else cur
                    out[t] = (cur, prev)
    except Exception as e:
        st.session_state["fetch_err"] = str(e)
    return out

d = load_holdings()
hold = d["holdings"]
tickers = [h["ticker"] for h in hold]
live = fetch_prices(tickers)
live_ok = len(live) > 0

rows = []
for h in hold:
    tk = h["ticker"]; sh = h["shares"]; avg = h["avg_cost"]
    if tk in live:
        price, prev = live[tk]
    else:
        price = h["last_price"]; prev = h["last_price"]
    mv = price * sh
    cost = avg * sh
    pnl = (price - avg) * sh
    pnl_pct = pnl / abs(cost) if cost else 0
    day = (price/prev - 1) if prev else 0
    rows.append(dict(Ticker=tk, Company=h["company"], Sector=h["sector"], Country=h["country"],
                     Shares=sh, Avg_Cost=avg, Price=price, Day=day,
                     Cost_Basis=cost, Market_Value=mv, PnL=pnl, PnL_pct=pnl_pct,
                     Status=h.get("status",""), Thesis=h.get("thesis",""), Kill=h.get("kill","")))
df = pd.DataFrame(rows)
invested = df["Market_Value"].sum()
cash = d["cash"]
nav = invested + cash
total_pnl = df["PnL"].sum()
total_ret = nav/d["starting_capital"] - 1
df["Weight"] = df["Market_Value"]/invested

# ---- header ----
st.title("📈 Live Portfolio Dashboard")
src = "🟢 Live prices (yfinance)" if live_ok else "🟡 Last-known prices (live fetch unavailable)"
st.caption(f"{src} • SMID-cap book • benchmark IWM • generated {datetime.date.today().isoformat()}")

c1,c2,c3,c4,c5 = st.columns(5)
c1.metric("Net Asset Value", f"${nav:,.0f}")
c2.metric("Total Return", f"{total_ret:,.1%}")
c3.metric("Unrealized P&L", f"${total_pnl:,.0f}")
c4.metric("Invested (Mkt Val)", f"${invested:,.0f}")
c5.metric("Cash (margin)", f"${cash:,.0f}")

# ---- charts ----
left, right = st.columns([3,2])
def fmt_table(src, money=(), pct=(), money0=()):
    o = src.copy()
    for c in money:  o[c] = o[c].map(lambda v: f"${v:,.2f}")
    for c in money0: o[c] = o[c].map(lambda v: f"${v:,.0f}")
    for c in pct:    o[c] = o[c].map(lambda v: f"{v:+.1%}")
    return o

with left:
    st.subheader("Positions")
    show = df[["Ticker","Shares","Avg_Cost","Price","Day","Market_Value","PnL","PnL_pct","Weight","Status"]].copy()
    show = show.sort_values("Market_Value", ascending=False)
    disp = fmt_table(show, money=("Avg_Cost","Price"), money0=("Market_Value","PnL"),
                     pct=("Day","PnL_pct","Weight"))
    st.dataframe(disp, use_container_width=True, height=460, hide_index=True)
with right:
    st.subheader("Allocation")
    alloc = df[df["Market_Value"]>0]
    fig = px.pie(alloc, values="Market_Value", names="Ticker", hole=.45)
    fig.update_layout(margin=dict(t=10,b=10,l=10,r=10), height=300, showlegend=False)
    fig.update_traces(textposition="inside", textinfo="label+percent")
    st.plotly_chart(fig, use_container_width=True)
    st.subheader("Sector exposure")
    sec = df.groupby("Sector")["Market_Value"].sum().sort_values(ascending=False).reset_index()
    figs = px.bar(sec, x="Market_Value", y="Sector", orientation="h", color_discrete_sequence=[NAVY])
    figs.update_layout(margin=dict(t=10,b=10,l=10,r=10), height=240, yaxis_title="", xaxis_title="")
    st.plotly_chart(figs, use_container_width=True)

# ---- winners / losers ----
st.subheader("Best & worst (unrealized)")
w,l = st.columns(2)
top = df.sort_values("PnL", ascending=False).head(5)[["Ticker","PnL","PnL_pct"]]
bot = df.sort_values("PnL").head(5)[["Ticker","PnL","PnL_pct"]]
w.dataframe(fmt_table(top, money0=("PnL",), pct=("PnL_pct",)), use_container_width=True, hide_index=True)
l.dataframe(fmt_table(bot, money0=("PnL",), pct=("PnL_pct",)), use_container_width=True, hide_index=True)

# ---- stress test (beta-driven) ----
st.subheader("Stress test vs IWM")
df["beta"] = [h["beta"] or 1.0 for h in hold]
beta_dollar = (df["Market_Value"]*df["beta"]).sum()
port_beta = beta_dollar/invested if invested else 0
scen = {"Crash -20%":-.20, "Correction -10%":-.10, "Flash -5%":-.05, "Rally +10%":.10}
srows = [dict(Scenario=k, IWM_Move=v, PnL_Impact=beta_dollar*v, Proj_NAV=nav+beta_dollar*v) for k,v in scen.items()]
sdf = pd.DataFrame(srows)
st.caption(f"Portfolio beta to IWM ≈ {port_beta:.2f}. STEP short carries negative MV, so it cushions selloffs.")
sdisp = sdf.copy()
sdisp["IWM_Move"] = sdisp["IWM_Move"].map(lambda v: f"{v:+.0%}")
sdisp["PnL_Impact"] = sdisp["PnL_Impact"].map(lambda v: f"${v:,.0f}")
sdisp["Proj_NAV"] = sdisp["Proj_NAV"].map(lambda v: f"${v:,.0f}")
st.dataframe(sdisp, use_container_width=True, hide_index=True)

# ---- thesis ----
seeded = df[df["Thesis"].astype(str).str.len()>0]
if len(seeded):
    st.subheader("Thesis notes")
    for _,r in seeded.iterrows():
        badge = {"On Track":"🟢","Slower":"🟡","Broken":"🔴","Played Out":"⚪"}.get(r["Status"],"•")
        with st.expander(f"{badge} {r['Ticker']} — {r['Status'] or 'note'}  ({r['PnL_pct']:+.1%})"):
            st.write(f"**Thesis:** {r['Thesis']}")
            if r["Kill"]: st.write(f"**Kill criteria:** {r['Kill']}")

st.caption("Holdings & cost basis from My Portfolio_BUILT.xlsx. Not investment advice.")
