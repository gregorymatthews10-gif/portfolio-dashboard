"""
 - live portfolio terminal (Streamlit).
Holdings/cost basis from holdings.json; prices, history & fundamentals fetched live
from yfinance on load, with graceful fallback so the page always renders.
Dark terminal styling modeled on Mispriced Assets (Nick Nemeth).
"""
import json, datetime, math, time
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="Mispriced? - Live Portfolio", page_icon="chart_with_upwards_trend", layout="wide", initial_sidebar_state="collapsed")

BG="#0d1117"; PANEL="#131a24"; GRID="#1e2733"; TXT="#d6dde6"; MUT="#7d8896"
GREEN="#16c784"; RED="#ea3943"; BLUE="#4d9fff"; PURPLE="#a371f7"; GOLD="#e3b341"
st.markdown(f"""<style>
.stApp {{ background:{BG}; color:{TXT}; }}
section[data-testid="stSidebar"] {{ display:none; }}
.block-container {{ padding-top:3rem; max-width:1450px; }}
h1,h2,h3,h4 {{ color:{TXT}; font-family:'Segoe UI',sans-serif; }}
[data-testid="stMetricLabel"] {{ color:{MUT}; font-size:.7rem; letter-spacing:.09em; text-transform:uppercase; }}
[data-testid="stMetricValue"] {{ font-size:1.55rem; font-weight:700; color:#ffffff; }}
[data-testid="stDataFrame"] {{ background:{PANEL}; }}
.stTabs [data-baseweb="tab-list"] {{ gap:8px; margin-top:.4rem; border-bottom:1px solid {GRID}; padding-bottom:2px; }}
.stTabs [data-baseweb="tab"] {{ background:{PANEL}; color:{MUT}; border-radius:7px; padding:10px 20px; font-weight:600; font-size:.9rem; }}
.stTabs [aria-selected="true"] {{ background:{BLUE}1f; color:{BLUE}; box-shadow:inset 0 -2px 0 {BLUE}; }}
.mono {{ font-family:'JetBrains Mono','Consolas',monospace; }}
table.term {{ width:100%; border-collapse:collapse; font-family:'JetBrains Mono','Consolas',monospace; font-size:.82rem; }}
table.term th {{ text-align:right; color:{MUT}; font-weight:600; padding:7px 10px; border-bottom:1px solid {GRID}; text-transform:uppercase; font-size:.68rem; letter-spacing:.05em; }}
table.term th:nth-child(-n+2), table.term td:nth-child(-n+2) {{ text-align:left; }}
table.term td {{ text-align:right; padding:7px 10px; border-bottom:1px solid {GRID}; }}
table.term tr:hover td {{ background:{GRID}; }}
.tk {{ color:{BLUE}; font-weight:700; }}
.pos {{ color:{GREEN}; }} .neg {{ color:{RED}; }}
.pill {{ padding:2px 9px; border-radius:4px; font-size:.72rem; font-weight:700; letter-spacing:.03em; }}
hr {{ border-color:{GRID}; margin:.6rem 0; }}
</style>""", unsafe_allow_html=True)
PLOT=dict(paper_bgcolor=PANEL, plot_bgcolor=PANEL, font=dict(color=TXT), margin=dict(t=30,b=10,l=10,r=10))
DASH="-"

@st.cache_data(ttl=300)
def load_holdings(): return json.load(open("holdings.json"))
@st.cache_data(ttl=300)
def load_trades():
    try: return json.load(open("trades.json"))
    except Exception: return []
@st.cache_data(ttl=600)
def fetch_history(tickers):
    try:
        import yfinance as yf
        h=yf.download(tickers+["SPY","IWM"], period="1y", progress=False, auto_adjust=True)["Close"]
        if isinstance(h,pd.Series): h=h.to_frame(tickers[0])
        return h.dropna(how="all")
    except Exception: return pd.DataFrame()
def _yf_session():
    """Browser-impersonating session to dodge Yahoo rate-limiting on shared hosts."""
    try:
        from curl_cffi import requests as cffi
        return cffi.Session(impersonate="chrome")
    except Exception:
        return None

@st.cache_data(ttl=21600)
def fetch_info(tickers):
    out={}
    try:
        import yfinance as yf
        sess=_yf_session()
        for t in tickers:
            data={}
            for attempt in range(2):
                try:
                    tk=yf.Ticker(t, session=sess) if sess else yf.Ticker(t)
                    info=tk.get_info() if hasattr(tk,"get_info") else tk.info
                    if info and len(info)>5:
                        data=dict(info); break
                except Exception:
                    pass
                time.sleep(0.3)
            # fall back / supplement with fast_info (price, market cap)
            try:
                tk=yf.Ticker(t, session=sess) if sess else yf.Ticker(t)
                fi=getattr(tk,"fast_info",None)
                if fi:
                    for k,src_k in [("marketCap","market_cap"),("trailingPE","pe_ratio")]:
                        try:
                            v=fi.get(src_k) if hasattr(fi,"get") else getattr(fi,src_k,None)
                            if v and not data.get(k): data[k]=v
                        except Exception: pass
            except Exception: pass
            out[t]=data
    except Exception: pass
    return out

@st.cache_data(ttl=21600)
def fetch_finnhub(tickers, key):
    """Reliable fundamentals via Finnhub (works on shared hosts where Yahoo .info is blocked)."""
    import requests
    out={}
    for t in tickers:
        try:
            r=requests.get("https://finnhub.io/api/v1/stock/metric",
                           params={"symbol":t,"metric":"all","token":key}, timeout=12)
            met=(r.json() or {}).get("metric",{}) or {}
        except Exception:
            met={}
        def f(k):
            v=met.get(k); return v if isinstance(v,(int,float)) else None
        m={}
        mc=f("marketCapitalization"); m["marketCap"]=mc*1e6 if mc else None
        m["trailingPE"]=f("peTTM") or f("peBasicExclExtraTTM")
        m["forwardPE"]=f("forwardPE") or f("peNormalizedAnnual")
        m["priceToSalesTrailing12Months"]=f("psTTM")
        m["priceToBook"]=f("pbAnnual") or f("pbQuarterly")
        m["enterpriseToEbitda"]=f("currentEv/ebitdaTTM") or f("currentEv/ebitdaAnnual")
        for s,dkey in [("grossMarginTTM","grossMargins"),("operatingMarginTTM","operatingMargins"),
                       ("netProfitMarginTTM","profitMargins"),("roeTTM","returnOnEquity"),
                       ("roaTTM","returnOnAssets")]:
            v=f(s); m[dkey]=v/100 if v is not None else None
        rg=f("revenueGrowthTTMYoy"); m["revenueGrowth"]=rg/100 if rg is not None else None
        m["dividendRate"]=f("dividendPerShareAnnual")
        m["dividendYield"]=f("dividendYieldIndicatedAnnual")
        out[t]={k:v for k,v in m.items() if v is not None}
    return out

@st.cache_data(ttl=1800)
def fetch_news(tickers):
    items=[]
    try:
        import yfinance as yf
        for t in tickers:
            try: raw=yf.Ticker(t).news or []
            except Exception: raw=[]
            for n in raw[:5]:
                c=n.get("content") if isinstance(n.get("content"),dict) else n
                title=n.get("title") or c.get("title")
                pub=n.get("publisher") or (c.get("provider") or {}).get("displayName") or ""
                link=n.get("link") or (c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url") or ""
                ts=n.get("providerPublishTime")
                when=None
                if isinstance(ts,(int,float)): when=datetime.datetime.utcfromtimestamp(ts)
                elif c.get("pubDate"):
                    try: when=datetime.datetime.fromisoformat(c["pubDate"].replace("Z","+00:00")).replace(tzinfo=None)
                    except Exception: when=None
                if title: items.append((t,title,pub,when,link))
    except Exception: pass
    return items

def gi(d,k):
    v=d.get(k) if d else None
    return v if isinstance(v,(int,float)) and not (isinstance(v,float) and np.isnan(v)) else None
def money(v,dec=0): return f"${v:,.{dec}f}" if isinstance(v,(int,float)) else DASH
def pctf(v,dec=1,signed=True):
    if not isinstance(v,(int,float)): return DASH
    return f"{v:+.{dec}%}" if signed else f"{v:.{dec}%}"
def numf(v,dec=2,suff=""): return f"{v:,.{dec}f}{suff}" if isinstance(v,(int,float)) else DASH
def bn(v):
    if not isinstance(v,(int,float)): return DASH
    return f"${v/1e9:.1f}B" if abs(v)>=1e9 else f"${v/1e6:.0f}M"
def cls(v): return "pos" if (isinstance(v,(int,float)) and v>=0) else "neg"

d=load_holdings(); hold=d["holdings"]; tickers=[h["ticker"] for h in hold]
hist=fetch_history(tickers); info=fetch_info(tickers); live_ok=not hist.empty
try:
    FINN_KEY=st.secrets.get("FINNHUB_KEY","")
except Exception:
    FINN_KEY=""
if FINN_KEY:
    try:
        for _t,_m in fetch_finnhub(tickers, FINN_KEY).items():
            info.setdefault(_t,{}).update(_m)
    except Exception: pass

def last_price(tk,fb):
    if tk in hist.columns and hist[tk].dropna().size: return float(hist[tk].dropna().iloc[-1])
    return fb
def prev_price(tk,fb):
    if tk in hist.columns and hist[tk].dropna().size>=2: return float(hist[tk].dropna().iloc[-2])
    return fb

rows=[]
for h in hold:
    tk=h["ticker"]; sh=h["shares"]; avg=h["avg_cost"]
    price=last_price(tk,h["last_price"]); prev=prev_price(tk,h["last_price"])
    rows.append(dict(Ticker=tk,Company=h["company"],Sector=h["sector"],Country=h["country"],
        beta_ref=h["beta"],Shares=sh,Avg_Cost=avg,Price=price,Prev=prev,
        Day=(price/prev-1) if prev else 0,Cost=avg*sh,MV=price*sh,PnL=(price-avg)*sh,
        PnL_pct=((price-avg)*sh/abs(avg*sh) if avg*sh else 0),Status=h.get("status",""),
        Thesis=h.get("thesis",""),Kill=h.get("kill","")))
df=pd.DataFrame(rows)
invested=df["MV"].sum(); cash=d["cash"]; nav=invested+cash
total_pnl=df["PnL"].sum(); total_ret=nav/d["starting_capital"]-1
df["Weight"]=df["MV"]/invested
day_pnl=(df["MV"]-df["Shares"]*df["Prev"]).sum()
total_inc=sum((gi(info.get(r.Ticker),"dividendRate") or 0)*r.Shares for r in df.itertuples() if r.Shares>0)

def port_returns():
    cols=[t for t in tickers if t in hist.columns]
    if not cols: return pd.Series(dtype=float)
    rets=hist[cols].pct_change().dropna()
    w=df.set_index("Ticker").loc[cols,"MV"]; w=w/w.sum()
    return (rets*w.values).sum(axis=1)
pr=port_returns()
ann_ret=pr.mean()*252 if len(pr) else None
ann_vol=pr.std()*np.sqrt(252) if len(pr) else None
sharpe=(ann_ret/ann_vol) if (ann_ret is not None and ann_vol) else None
downside=pr[pr<0]
sortino=(ann_ret/(downside.std()*np.sqrt(252))) if (ann_ret is not None and len(downside) and downside.std()) else None
def max_dd(s):
    if not len(s): return None
    cur=(1+s).cumprod(); return float((cur/cur.cummax()-1).min())
mdd=max_dd(pr)
def beta_vs(b):
    if b in hist.columns and len(pr):
        x=hist[b].pct_change().reindex(pr.index).dropna(); a=pr.reindex(x.index)
        if len(x)>2 and x.var(): return float(np.cov(a,x)[0,1]/x.var())
    return None
beta_spy=beta_vs("SPY"); beta_iwm=beta_vs("IWM")
var95=-np.percentile(pr,5) if len(pr) else None
var99=-np.percentile(pr,1) if len(pr) else None
cvar95=-pr[pr<=np.percentile(pr,5)].mean() if len(pr) else None
win_rate=(pr>0).mean() if len(pr) else None


# ---------------- vol / options helpers ----------------
def _ncdf(x): return 0.5*(1+math.erf(x/math.sqrt(2)))

def garch_vol(series, a=0.09, b=0.88):
    r=series.pct_change().dropna().values
    if len(r)<30: return None
    lr=float(np.var(r)); omega=lr*(1-a-b)
    s2=lr
    for x in r: s2=omega+a*x*x+b*s2
    fc=omega+a*r[-1]**2+b*s2
    return float(np.sqrt(max(fc,1e-12))*np.sqrt(252))

def hv20(series):
    r=series.pct_change().dropna()
    if len(r)<20: return None
    return float(r.tail(20).std()*np.sqrt(252))

def vol_regime(series):
    r=series.pct_change().dropna()
    if len(r)<40: return None
    roll=r.rolling(20).std().dropna()
    if not len(roll): return None
    pc=(roll.rank(pct=True)).iloc[-1]
    return "EXTREME" if pc>0.8 else "HIGH" if pc>0.6 else "NORMAL" if pc>0.4 else "LOW"

@st.cache_data(ttl=1800)
def fetch_options(tickers):
    """Nearest ~2wk expiry; pick call closest to 0.40 delta. Returns list of dicts."""
    out=[]
    try:
        import yfinance as yf
        today=datetime.date.today()
        for t in tickers:
            try:
                tk=yf.Ticker(t)
                spot=None
                h=tk.history(period="1d")
                if len(h): spot=float(h["Close"].iloc[-1])
                exps=tk.options or []
                if not exps or not spot: continue
                # choose expiry: DTE in [7,28] closest to 14
                cand=[]
                for e in exps:
                    try: dte=(datetime.date.fromisoformat(e)-today).days
                    except Exception: continue
                    if 5<=dte<=35: cand.append((abs(dte-14),e,dte))
                if not cand: continue
                _,exp,dte=sorted(cand)[0]
                calls=tk.option_chain(exp).calls
                if calls is None or not len(calls): continue
                T=max(dte,1)/365.0
                best=None
                for _,row in calls.iterrows():
                    K=float(row["strike"]); iv=float(row.get("impliedVolatility") or 0)
                    bid=float(row.get("bid") or 0); ask=float(row.get("ask") or 0)
                    mid=(bid+ask)/2 if (bid and ask) else float(row.get("lastPrice") or 0)
                    if iv<=0 or mid<=0 or K<=0: continue
                    d1=(math.log(spot/K)+0.5*iv*iv*T)/(iv*math.sqrt(T))
                    delta=_ncdf(d1)
                    diff=abs(delta-0.40)
                    if best is None or diff<best[0]:
                        d2=d1-iv*math.sqrt(T); pwin=_ncdf(d2)
                        spread=(ask-bid)/mid if (ask and bid and mid) else 1
                        vol=float(row.get("volume") or 0); oi=float(row.get("openInterest") or 0)
                        liq=("ILLIQUID" if (vol+oi)<50 else "WIDE" if spread>0.25 else "OK")
                        be=(K+mid)/spot-1
                        best=(diff,dict(Ticker=t,Expiry=exp,Strike=K,Mid=mid,DTE=dte,Delta=delta,
                                        BE=be,PWin=pwin,IV=iv,Liq=liq))
                if best:
                    out.append(o)
            except Exception: continue
    except Exception: pass
    return out

# ---------------- header ribbon ----------------
st.markdown(f"<div class='mono' style='color:{MUT}'>"
            f"<span style='color:{GREEN if live_ok else GOLD}'>&#9679; {'LIVE' if live_ok else 'SNAPSHOT'}</span>"
            f" &nbsp;|&nbsp; SMID-cap book &nbsp;|&nbsp; benchmarks SPY + IWM</div>", unsafe_allow_html=True)
k=st.columns(6)
k[0].metric("Portfolio Value", money(nav))
k[1].metric("Daily P&L", money(day_pnl), pctf(day_pnl/nav if nav else 0))
k[2].metric("Total Return", pctf(total_ret))
k[3].metric("Annual Income", money(total_inc))
k[4].metric("Sharpe", numf(sharpe) if sharpe is not None else DASH)
k[5].metric("Max Drawdown", pctf(mdd) if mdd is not None else DASH)
st.markdown("<hr>", unsafe_allow_html=True)

tabs=st.tabs(["Overview","Risk","Technicals","Volatility","Options","News","Income","Valuation","Profitability","Theses","Trades"])

def term_table(headers, rows_html):
    h="".join(f"<th>{x}</th>" for x in headers)
    return f"<table class='term'><thead><tr>{h}</tr></thead><tbody>{''.join(rows_html)}</tbody></table>"

with tabs[0]:
    if len(pr):
        st.subheader("Growth of $100 - portfolio vs SPY vs IWM")
        cols=[t for t in tickers if t in hist.columns]
        w=df.set_index("Ticker").loc[cols,"MV"]; w=w/w.sum()
        prc=(hist[cols].pct_change().fillna(0)*w.values).sum(axis=1)
        idx=pd.DataFrame({"Portfolio":(1+prc).cumprod()*100})
        for b in ["SPY","IWM"]:
            if b in hist.columns: idx[b]=(1+hist[b].pct_change().fillna(0)).cumprod().reindex(idx.index)*100
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=idx.index,y=idx["Portfolio"],name="Portfolio",
            line=dict(color=BLUE,width=2.4),fill="tozeroy",fillcolor="rgba(77,159,255,0.12)"))
        for b,c in [("SPY",GOLD),("IWM",PURPLE)]:
            if b in idx.columns:
                fig.add_trace(go.Scatter(x=idx.index,y=idx[b],name=b,line=dict(color=c,width=1.2,dash="dot")))
        ymin=float(idx.min().min()); fig.update_yaxes(range=[max(0,ymin-5),float(idx.max().max())+5])
        fig.update_layout(**PLOT,height=340,xaxis=dict(gridcolor=GRID),yaxis=dict(gridcolor=GRID),legend=dict(orientation="h"))
        st.plotly_chart(fig, width='stretch')
    a,b=st.columns(2)
    with a:
        st.subheader("Sector exposure")
        sec=df.groupby("Sector")["MV"].sum().reset_index()
        f1=px.pie(sec,values="MV",names="Sector",hole=.55,color_discrete_sequence=px.colors.qualitative.Set2)
        f1.update_layout(**PLOT,height=300,legend=dict(font=dict(size=10))); f1.update_traces(textinfo="percent")
        st.plotly_chart(f1, width='stretch')
    with b:
        st.subheader("Geographic exposure")
        geo=df.groupby("Country")["MV"].sum().reset_index()
        f2=px.pie(geo,values="MV",names="Country",hole=.55,color_discrete_sequence=px.colors.qualitative.Pastel)
        f2.update_layout(**PLOT,height=300,legend=dict(font=dict(size=10))); f2.update_traces(textinfo="percent")
        st.plotly_chart(f2, width='stretch')
    st.subheader("Positions")
    show=df.sort_values("MV",ascending=False)
    rhtml=[]
    for _,r in show.iterrows():
        rhtml.append(
            f"<tr><td class='tk'>{r['Ticker']}</td><td>{r['Company']}</td>"
            f"<td>{r['Shares']:,.0f}</td><td>{money(r['Price'],2)}</td>"
            f"<td>{money(r['MV'])}</td>"
            f"<td class='{cls(r['PnL'])}'>{'+' if r['PnL']>=0 else ''}{money(r['PnL'])}</td>"
            f"<td class='{cls(r['PnL_pct'])}'>{pctf(r['PnL_pct'])}</td>"
            f"<td>{pctf(r['Weight'],1,False)}</td>"
            f"<td class='{cls(r['Day'])}'>{pctf(r['Day'],2)}</td></tr>")
    st.markdown(term_table(["Ticker","Company","Shares","Price","Mkt Val","P&L","P&L %","Weight","Day"],rhtml),
                unsafe_allow_html=True)
    def rsi(tk,n=14):
        if tk not in hist.columns: return None
        s=hist[tk].dropna()
        if len(s)<n+1: return None
        delta=s.diff(); up=delta.clip(lower=0).rolling(n).mean(); dn=(-delta.clip(upper=0)).rolling(n).mean()
        rs=up/dn.replace(0,np.nan)
        return float(100-100/(1+rs.iloc[-1])) if not np.isnan(rs.iloc[-1]) else None
    rsis={t:rsi(t) for t in tickers}
    bull=sum(1 for v in rsis.values() if v and v>55); bear=sum(1 for v in rsis.values() if v and v<45)
    neut=sum(1 for v in rsis.values() if v is not None)-bull-bear
    st.markdown(f"<div class='mono' style='color:{MUT};margin-top:8px'>"
                f"<span class='pos'>&#9650; BULLISH: {bull}</span> &nbsp; NEUTRAL: {neut} &nbsp; "
                f"<span class='neg'>&#9660; BEARISH: {bear}</span> &nbsp;(RSI-based)</div>", unsafe_allow_html=True)

with tabs[1]:
    m1,m2=st.columns([1,2])
    with m1:
        st.subheader("Risk metrics")
        rm=[("Annualized Return",pctf(ann_ret) if ann_ret is not None else DASH),
            ("Annualized Volatility",pctf(ann_vol,1,False) if ann_vol is not None else DASH),
            ("Sharpe Ratio",numf(sharpe) if sharpe is not None else DASH),
            ("Sortino Ratio",numf(sortino) if sortino is not None else DASH),
            ("Max Drawdown",pctf(mdd) if mdd is not None else DASH),
            ("Beta (SPY)",numf(beta_spy) if beta_spy is not None else DASH),
            ("Beta (IWM)",numf(beta_iwm) if beta_iwm is not None else DASH),
            ("VaR 95% (daily)",pctf(-var95,2) if var95 is not None else DASH),
            ("VaR 99% (daily)",pctf(-var99,2) if var99 is not None else DASH),
            ("CVaR 95% (daily)",pctf(-cvar95,2) if cvar95 is not None else DASH),
            ("Win Rate",pctf(win_rate,1,False) if win_rate is not None else DASH)]
        st.dataframe(pd.DataFrame(rm,columns=["Metric","Value"]), width='stretch', hide_index=True, height=420)
    with m2:
        st.subheader("Correlation matrix")
        cols=[t for t in tickers if t in hist.columns]
        if len(cols)>=2:
            corr=hist[cols].pct_change().dropna().corr()
            fig=px.imshow(corr,color_continuous_scale="RdBu_r",zmin=-1,zmax=1,aspect="auto")
            fig.update_layout(**PLOT,height=420); st.plotly_chart(fig, width='stretch')
        else: st.info("Correlation needs live price history (deploy to populate).")
    st.subheader("Monte Carlo - loss distribution (Student-t, 10k sims)")
    if len(pr)>20:
        mu=pr.mean(); sd=pr.std(); dfree=6; sims={}
        for label,hd in [("1-Day",1),("1-Week",5),("1-Month",21),("3-Month",63)]:
            draws=np.random.standard_t(dfree,size=(10000,hd))*sd*np.sqrt((dfree-2)/dfree)+mu
            cum=(1+draws).prod(axis=1)-1
            sims[label]=dict(a=np.percentile(cum,5),b=np.percentile(cum,1),c=cum[cum<=np.percentile(cum,5)].mean(),
                             d=np.median(cum),e=cum.min(),f=cum.max(),g=(cum<=-.2).mean())
        mc=pd.DataFrame([dict(Horizon=k,**{"VaR 95%":pctf(v["a"],2),"VaR 99%":pctf(v["b"],2),"CVaR 95%":pctf(v["c"],2),
            "Median":pctf(v["d"],2),"Worst":pctf(v["e"],1),"Best":pctf(v["f"],1),"P(>20% loss)":pctf(v["g"],1,False)}) for k,v in sims.items()])
        st.dataframe(mc, width='stretch', hide_index=True)
    else: st.info("Monte Carlo needs live price history (deploy to populate).")
    st.subheader("Historical stress scenarios (beta-scaled)")
    pb=(df["MV"]*df["beta_ref"].fillna(1.0)).sum()/invested if invested else 1.0
    scen=[("COVID Crash (Feb-Mar 2020)",-.339),("2022 Rate Shock",-.252),("GFC 2008-09",-.565),
          ("Dot-Com Bust (2000-02)",-.491),("Black Monday (1987)",-.204),("Aug 2024 Yen Carry",-.084)]
    sr=pd.DataFrame([dict(Scenario=s,**{"Market Move":pctf(mv,1),"Portfolio Impact":pctf(mv*pb,1),
        "Stressed NAV":money(nav*(1+mv*pb)),"P&L":money(nav*mv*pb)}) for s,mv in scen])
    st.caption(f"Portfolio beta (bottom-up) ~ {pb:.2f}. STEP short cushions selloffs.")
    st.dataframe(sr, width='stretch', hide_index=True)
    c1,c2=st.columns(2)
    with c1:
        st.subheader("Tail risk")
        if len(pr)>5:
            sk=float(((pr-pr.mean())**3).mean()/pr.std()**3); ku=float(((pr-pr.mean())**4).mean()/pr.std()**4-3)
            tr=[("Daily Vol",pctf(pr.std(),2,False)),("Annualized Vol",pctf(ann_vol,1,False)),("Skewness",numf(sk,3)),
                ("Excess Kurtosis",numf(ku,2)),("Worst Day",pctf(pr.min(),2)),("Best Day",pctf(pr.max(),2))]
            st.dataframe(pd.DataFrame(tr,columns=["Metric","Value"]), width='stretch', hide_index=True)
        else: st.info("Needs live history.")
    with c2:
        st.subheader("Liquidity - days to exit (20% ADV)")
        lr=[]
        for _,r in df.iterrows():
            adv=gi(info.get(r["Ticker"]),"averageVolume"); days=(abs(r["Shares"])/(0.2*adv)) if adv else None
            lr.append(dict(Ticker=r["Ticker"],**{"Avg Daily Vol":f"{adv:,.0f}" if adv else DASH,
                "Days to Exit":numf(days,1) if days is not None else DASH,"Weight":pctf(r["Weight"],1,False)}))
        st.dataframe(pd.DataFrame(lr), width='stretch', hide_index=True, height=300)

with tabs[2]:
    st.subheader("Technical signals (RSI + MACD)")
    def macd_sig(tk):
        if tk not in hist.columns: return None
        s=hist[tk].dropna()
        if len(s)<35: return None
        macd=s.ewm(span=12).mean()-s.ewm(span=26).mean(); sig=macd.ewm(span=9).mean()
        return 1 if macd.iloc[-1]>sig.iloc[-1] else -1
    PILL={"STRONG BUY":GREEN,"BUY":GREEN,"LEAN BULL":BLUE,"NEUTRAL":MUT,"LEAN BEAR":PURPLE,"SELL":RED}
    trows=[]
    for t in tickers:
        s=hist[t].dropna() if t in hist.columns else pd.Series(dtype=float); r=None
        if len(s)>=15:
            delta=s.diff(); up=delta.clip(lower=0).rolling(14).mean(); dn=(-delta.clip(upper=0)).rolling(14).mean()
            rs=up/dn.replace(0,np.nan); r=float(100-100/(1+rs.iloc[-1])) if not np.isnan(rs.iloc[-1]) else None
        mac=macd_sig(t)
        comp=(1 if (r and r>55) else -1 if (r and r<45) else 0)+(mac or 0)
        sig=("STRONG BUY" if comp>=2 else "BUY" if comp==1 else "SELL" if comp<=-2 else "LEAN BEAR" if comp==-1 else "NEUTRAL")
        trows.append((comp,t,sig,r,mac))
    trows.sort(key=lambda x:-x[0])
    rhtml=[]
    for comp,t,sig,r,mac in trows:
        col=PILL.get(sig,MUT)
        rhtml.append(f"<tr><td class='tk'>{t}</td>"
            f"<td style='text-align:left'><span class='pill' style='background:{col}22;color:{col}'>{sig}</span></td>"
            f"<td class='{ 'pos' if comp>0 else 'neg' if comp<0 else ''}'>{comp:+d}</td>"
            f"<td>{numf(r,0) if r is not None else DASH}</td>"
            f"<td class='{ 'pos' if mac==1 else 'neg' if mac==-1 else ''}'>{'up' if mac==1 else 'down' if mac==-1 else DASH}</td></tr>")
    st.markdown(term_table(["Ticker","Signal","Composite","RSI","MACD"],rhtml), unsafe_allow_html=True)
    st.caption("Composite = RSI signal (>55 bull / <45 bear) + MACD cross. Educational, not a recommendation.")

with tabs[3]:
    st.subheader("Volatility - realized vs GARCH(1,1) forecast")
    vrows=[]; exps=[]
    for t in tickers:
        s=hist[t].dropna() if t in hist.columns else pd.Series(dtype=float)
        hv=hv20(s); gv=garch_vol(s); reg=vol_regime(s)
        exp=(gv/hv-1) if (gv and hv) else None
        if exp is not None: exps.append(exp)
        vrows.append((exp if exp is not None else 0, t, hv, gv, exp, reg))
    vrows.sort(key=lambda x:-x[0])
    if any(r[2] for r in vrows):
        avg_exp=np.mean(exps) if exps else None
        st.markdown(f"<div class='mono' style='color:{MUT}'>AVG EXPANSION: "
                    f"<span class='{cls(avg_exp)}'>{pctf(avg_exp,0)}</span> &nbsp; (GARCH vol vs 20d realized)</div>",
                    unsafe_allow_html=True)
        REGC={"EXTREME":RED,"HIGH":GOLD,"NORMAL":MUT,"LOW":GREEN}
        rhtml=[]
        for _,t,hv,gv,exp,reg in vrows:
            rc=REGC.get(reg,MUT)
            rhtml.append(f"<tr><td class='tk'>{t}</td>"
                f"<td>{pctf(hv,0,False) if hv else DASH}</td>"
                f"<td>{pctf(gv,0,False) if gv else DASH}</td>"
                f"<td class='{cls(exp)}'>{pctf(exp,0) if exp is not None else DASH}</td>"
                f"<td style='text-align:left'><span class='pill' style='background:{rc}22;color:{rc}'>{reg or DASH}</span></td></tr>")
        st.markdown(term_table(["Ticker","HV 20D","GARCH","Expansion","Regime"],rhtml), unsafe_allow_html=True)
        st.caption("GARCH(1,1) a=0.09 b=0.88, 1-step-ahead, annualized. Expansion = GARCH/HV20 - 1. Regime = percentile of 20d realized vol.")
    else:
        st.info("Volatility needs live price history (deploy to populate).")

with tabs[4]:
    st.subheader("Best short-term calls (~2-week expiry, ~0.40 delta)")
    opts=fetch_options(tickers)
    if not opts:
        st.info("Option chains load live from yfinance on deploy (none available here).")
    else:
        gvmap={t:garch_vol(hist[t].dropna()) if t in hist.columns else None for t in tickers}
        opts.sort(key=lambda o:-(((gvmap.get(o["Ticker"]) or 0)-o["IV"])/o["IV"] if o["IV"] else -9))
        rhtml=[]
        for o in opts:
            gv=gvmap.get(o["Ticker"]); edge=((gv-o["IV"])/o["IV"]) if (gv and o["IV"]) else None
            lc={"OK":GREEN,"WIDE":GOLD,"ILLIQUID":RED}.get(o["Liq"],MUT)
            rhtml.append(f"<tr><td class='tk'>{o['Ticker']}</td><td>{o['Expiry']}</td>"
                f"<td>${o['Strike']:,.1f}C</td><td>${o['Mid']:,.2f}</td><td>{o['DTE']}d</td>"
                f"<td>{o['Delta']:.2f}</td><td class='{cls(o['BE'])}'>{pctf(o['BE'],1)}</td>"
                f"<td>{pctf(o['PWin'],0,False)}</td>"
                f"<td class='{cls(edge)}'>{pctf(edge,0) if edge is not None else DASH}</td>"
                f"<td style='text-align:left'><span class='pill' style='background:{lc}22;color:{lc}'>{o['Liq']}</span></td></tr>")
        st.markdown(term_table(["Ticker","Expiry","Strike","Mid","DTE","Delta","B/E","P(win)","Edge","Liq"],rhtml), unsafe_allow_html=True)
        st.caption("Edge = (GARCH vol - market IV)/IV. BS delta/P(win), r=0. Educational only, not a recommendation.")

with tabs[5]:
    st.subheader("News - portfolio holdings")
    news=fetch_news(tickers)
    if not news:
        st.info("Headlines load live from yfinance on deploy (none available here).")
    else:
        news.sort(key=lambda x: x[3] or datetime.datetime.min, reverse=True)
        out=[]
        for tk,title,pub,when,link in news[:40]:
            ago=""
            if when:
                hrs=(datetime.datetime.utcnow()-when).total_seconds()/3600
                ago = f"{int(hrs)}h ago" if hrs<48 else when.strftime("%b %d")
            t_html=f"<a href='{link}' target='_blank' style='color:{TXT};text-decoration:none'>{title}</a>" if link else title
            out.append(f"<div style='padding:9px 0;border-bottom:1px solid {GRID}'>"
                       f"<span class='pill' style='background:{BLUE}22;color:{BLUE};margin-right:8px'>{tk}</span>"
                       f"<span style='font-size:.92rem'>{t_html}</span>"
                       f"<div class='mono' style='color:{MUT};font-size:.72rem;margin-top:3px'>{pub} &nbsp; {ago}</div></div>")
        st.markdown("".join(out), unsafe_allow_html=True)

with tabs[6]:
    st.subheader("Income & dividends")
    ic=st.columns(3)
    ic[0].metric("Total Annual Income", money(total_inc))
    ic[1].metric("Portfolio Yield", pctf(total_inc/invested if invested else 0,2,False))
    payers=[r for r in df.itertuples() if (gi(info.get(r.Ticker),"dividendRate") or 0)>0]
    ic[2].metric("Positions Paying", f"{len(payers)}")
    irows=[]
    for _,r in df.iterrows():
        i=info.get(r["Ticker"]); rate=gi(i,"dividendRate"); yld=gi(i,"dividendYield")
        anninc=(rate*r["Shares"]) if (rate and r["Shares"]>0) else None
        irows.append(dict(Ticker=r["Ticker"],**{"Div Yield":pctf((yld/100 if yld>1 else yld),2,False) if yld else DASH,
            "Div Rate":money(rate,2) if rate else DASH,"Shares":f"{r['Shares']:,.0f}",
            "Annual Income":money(anninc) if anninc else DASH,
            "Yld on Cost":pctf(rate/r["Avg_Cost"],2,False) if (rate and r["Avg_Cost"]) else DASH}))
    st.dataframe(pd.DataFrame(irows), width='stretch', hide_index=True, height=480)

with tabs[7]:
    st.subheader("Valuation")
    v=pd.DataFrame({"Ticker":df["Ticker"],"Mkt Cap":[bn(gi(info.get(t),"marketCap")) for t in df["Ticker"]],
        "P/E":[numf(gi(info.get(t),"trailingPE"),1) for t in df["Ticker"]],
        "Fwd P/E":[numf(gi(info.get(t),"forwardPE"),1) for t in df["Ticker"]],
        "P/S":[numf(gi(info.get(t),"priceToSalesTrailing12Months"),2) for t in df["Ticker"]],
        "P/B":[numf(gi(info.get(t),"priceToBook"),2) for t in df["Ticker"]],
        "EV/EBITDA":[numf(gi(info.get(t),"enterpriseToEbitda"),1) for t in df["Ticker"]]})
    st.dataframe(v, width='stretch', hide_index=True, height=560)

with tabs[8]:
    st.subheader("Profitability")
    p=pd.DataFrame({"Ticker":df["Ticker"],
        "Gross Margin":[pctf(gi(info.get(t),"grossMargins"),1,False) for t in df["Ticker"]],
        "Op Margin":[pctf(gi(info.get(t),"operatingMargins"),1,False) for t in df["Ticker"]],
        "Net Margin":[pctf(gi(info.get(t),"profitMargins"),1,False) for t in df["Ticker"]],
        "ROE":[pctf(gi(info.get(t),"returnOnEquity"),1,False) for t in df["Ticker"]],
        "ROA":[pctf(gi(info.get(t),"returnOnAssets"),1,False) for t in df["Ticker"]],
        "Rev Growth":[pctf(gi(info.get(t),"revenueGrowth"),1) for t in df["Ticker"]]})
    st.dataframe(p, width='stretch', hide_index=True, height=560)

with tabs[9]:
    st.subheader("Investment theses")
    seeded=df[df["Thesis"].astype(str).str.len()>0]
    if len(seeded)==0: st.write("No theses filled in yet.")
    for _,r in seeded.iterrows():
        with st.expander(f"{r['Ticker']}  [{r['Status'] or 'note'}]   ({pctf(r['PnL_pct'])})"):
            st.write(f"**Thesis:** {r['Thesis']}")
            if r["Kill"]: st.write(f"**Kill criteria:** {r['Kill']}")


with tabs[10]:
    st.subheader("Trade history")
    trades=load_trades()
    if not trades:
        st.info("No trade history loaded.")
    else:
        LAB={"Buy":GREEN,"Addition":BLUE,"Trim":GOLD,"Sell":RED,"Short":PURPLE,"Cover":PURPLE}
        from collections import Counter
        cnt=Counter(t["label"] for t in trades)
        chips=" &nbsp; ".join(f"<span class='pill' style='background:{LAB.get(k,MUT)}22;color:{LAB.get(k,MUT)}'>{k}: {v}</span>" for k,v in cnt.most_common())
        st.markdown(f"<div style='margin-bottom:8px'>{chips}</div>", unsafe_allow_html=True)
        rh=[]
        for t in trades:
            col=LAB.get(t["label"],MUT)
            amt=t.get("amount"); ac=cls(amt) if isinstance(amt,(int,float)) else ""
            rh.append("<tr>"
                f"<td>{t['date']}</td><td class='tk'>{t['ticker']}</td>"
                f"<td style='text-align:left'><span class='pill' style='background:{col}22;color:{col}'>{t['label']}</span></td>"
                f"<td>{t['shares']:,.4f}</td>"
                f"<td>{money(t['price'],2) if isinstance(t.get('price'),(int,float)) else DASH}</td>"
                f"<td class='{ac}'>{money(amt,2) if isinstance(amt,(int,float)) else DASH}</td></tr>")
        st.markdown(term_table(["Date","Ticker","Action","Shares","Price","Amount"],rh), unsafe_allow_html=True)
        st.caption("Buy = new position - Addition = added to existing - Trim = partial sell - Sell = closed - Short = short sale.")

st.markdown(f"<hr><div class='mono' style='color:{MUT};text-align:center'>&gt; session.active &nbsp;.&nbsp; MISPRICED? &nbsp;.&nbsp; {datetime.date.today().isoformat()} &nbsp;|&nbsp; not financial advice</div>", unsafe_allow_html=True)
