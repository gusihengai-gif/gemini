import datetime
import pandas as pd
import requests
import streamlit as st
import plotly.graph_objects as go

# ==========================================
# 0. 網頁全域風格配置 (保留原 React Dark Style)
# ==========================================
st.set_page_config(
    page_title="Stock Signal Dashboard",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 【核心修正】改用 st.html 配合 <iframe> 注入，或包裹在不被解析的標籤中，徹底繞過 Streamlit 內建的 st.markdown Bug
css_style = """
<style>
    .stApp { background-color: #0b1329; color: #f8fafc; } 
    [data-testid='stSidebar'] { background-color: #0f172a; border-right: 1px solid rgba(255,255,255,0.05); } 
    .metric-card { background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border: 1px solid rgba(255,255,255,0.05); border-radius: 16px; padding: 20px; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.3); } 
    .status-pass { background-color: rgba(16, 185, 129, 0.15); color: #10b981; padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: 900; } 
    .status-wait { background-color: rgba(30, 41, 59, 0.8); color: #64748b; padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: 900; }
</style>
"""
# 透過元件層級注入 CSS，避免 st.markdown 內部機制去解析大括號 {}
st.components.v1.html(css_style, height=0, width=0)

# 同時使用無大括號的純文字給 markdown 兜底安全網
st.markdown("", unsafe_allowed_html=True)

# ==========================================
# 1. 股票資料庫 (已精簡，方便後續自行新增)
# ==========================================
STOCK_DATABASE = [
    {"id": "2330", "name": "台積電"},
    {"id": "9958", "name": "世紀鋼"},
    {"id": "9945", "name": "潤泰新"}
    # 您可以在此處依據 {"id": "代碼", "name": "名稱"}, 的格式手動複製新增股票
]
stock_options = [f"{s['id']} {s['name']}" for s in STOCK_DATABASE]

# Sidebar 設定
st.sidebar.markdown("### 🔍 策略篩選系統")
selected_stock_str = st.sidebar.selectbox("選擇或輸入股票", stock_options, index=0)
STOCK_ID = selected_stock_str.split(" ")[0]

# ==========================================
# 2. 資料抓取與對齊
# ==========================================
API_BASE = "https://api.finmindtrade.com/api/v4/data"
end_date = datetime.date.today().strftime("%Y-%m-%d")
start_date = (datetime.date.today() - datetime.timedelta(days=450)).strftime("%Y-%m-%d")

@st.cache_data(ttl=3600)
def fetch_stock_data(stock_id):
    params = {"dataset": "TaiwanStockPrice", "data_id": stock_id, "start_date": start_date, "end_date": end_date}
    try:
        res = requests.get(API_BASE, params=params, timeout=10)
        return res.json()
    except:
        return None

data = fetch_stock_data(STOCK_ID)

if not data or data.get("msg") != "success" or not data.get("data"):
    st.sidebar.error(f"無法取得 {STOCK_ID} 資料，請稍後再試。")
    st.stop()

df = pd.DataFrame(data["data"])

# 自動修正 FinMind 欄位對齊
mapping = {}
for col in df.columns:
    col_lower = col.lower()
    if col_lower == "close": mapping[col] = "Close"
    elif col_lower == "open": mapping[col] = "Open"
    elif col_lower in ["high", "max"]: mapping[col] = "High"
    elif col_lower in ["low", "min"]: mapping[col] = "Low"
    elif col_lower in ["volume", "trading_volume"]: mapping[col] = "Volume"
    elif col_lower == "date": mapping[col] = "date"

df = df.rename(columns=mapping)
df["date"] = pd.to_datetime(df["date"])
for col in ["Close", "Open", "High", "Low", "Volume"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")
df = df.sort_values("date").reset_index(drop=True)

# ==========================================
# 3. 技術指標計算 (20MA, 60MA, 5MA量, KD)
# ==========================================
df["ma20"] = df["Close"].rolling(window=20).mean()
df["ma60"] = df["Close"].rolling(window=60).mean()
df["v_ma5"] = df["Volume"].rolling(window=5).mean()

df["rsv_high"] = df["High"].rolling(window=9).max()
df["rsv_low"] = df["Low"].rolling(window=9).min()
df["rsv"] = ((df["Close"] - df["rsv_low"]) / (df["rsv_high"] - df["rsv_low"] + 1e-8)) * 100

k_list, d_list = [], []
current_k, current_d = 50.0, 50.0
for rsv in df["rsv"]:
    if pd.isna(rsv):
        k_list.append(None); d_list.append(None)
    else:
        current_k = (2 / 3) * current_k + (1 / 3) * rsv
        current_d = (2 / 3) * current_d + (1 / 3) * current_k
        k_list.append(current_k); d_list.append(current_d)
df["k"], df["d"] = k_list, d_list
df = df.dropna().reset_index(drop=True)

# ==========================================
# 4. 策略篩選與訊號 (PASS / WAIT)
# ==========================================
df["cond_ma20"] = df["Close"] > df["ma20"]
df["cond_ma60"] = df["Close"] > df["ma60"]
df["cond_ma_trend"] = df["ma20"] > df["ma60"]
df["cond_kd_cross"] = df["k"] > df["d"]
df["cond_k_high"] = df["k"] > 50
df["cond_vol"] = df["Volume"] > df["v_ma5"]

df["signal"] = (
    df["cond_ma20"] & df["cond_ma60"] & df["cond_ma_trend"] & 
    df["cond_kd_cross"] & df["cond_k_high"] & df["cond_vol"]
)

latest = df.iloc[-1]
latest_date = latest["date"].strftime("%Y-%m-%d")

# ==========================================
# 5. UI 畫面渲染
# ==========================================
st.title(f"📊 {selected_stock_str}")
st.caption(f"數據更新時間：{latest_date}")

left_col, right_col = st.columns([2, 1], gap="medium")

with left_col:
    st.markdown("#### 📈 互動式趨勢分析圖表")
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["Close"], name="收盤價",
        line=dict(color="#38bdf8", width=2),
        fill='tozeroy', fillcolor='rgba(56, 189, 248, 0.05)'
    ))
    fig.add_trace(go.Scatter(x=df["date"], y=df["ma20"], name="20 MA", line=dict(color="#fbbf24", width=1.5, dash='dash')))
    fig.add_trace(go.Scatter(x=df["date"], y=df["ma60"], name="60 MA", line=dict(color="#ec4899", width=1.5)))
    
    signal_days = df[df["signal"] == True]
    fig.add_trace(go.Scatter(
        x=signal_days["date"], y=signal_days["Close"], name="策略進場點",
        mode='markers', marker=dict(color='#10b981', size=8, symbol='triangle-up', line=dict(width=1, color='white'))
    ))
    
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=10, r=10, t=10, b=10), height=450,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(color="#94a3b8")),
        xaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.03)', tickfont=dict(color='#64748b')),
        yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.03)', tickfont=dict(color='#64748b'), side="right")
    )
    st.plotly_chart(fig, use_container_width=True)

with right_col:
    if latest["signal"]:
        status_html = "<div style='background: linear-gradient(135deg, #064e3b 0%, #022c22 100%); border: 1px solid #10b981; border-radius:16px; padding:25px; text-align:center; box-shadow: 0 0 20px rgba(16,185,129,0.2);'>" \
                      "<span style='color:#34d399; font-size:12px; font-weight:900; letter-spacing:2px;'>DECISION STATUS</span>" \
                      "<h2 style='color:#10b981; margin-top:5px; font-weight:900;'>🎯 符合策略進場</h2></div>"
    else:
        status_html = "<div style='background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border: 1px solid #334155; border-radius:16px; padding:25px; text-align:center;'>" \
                      "<span style='color:#94a3b8; font-size:12px; font-weight:900; letter-spacing:2px;'>DECISION STATUS</span>" \
                      "<h2 style='color:#64748b; margin-top:5px; font-weight:900;'>⏳ 觀望等待訊號</h2></div>"
    st.components.v1.html(status_html, height=120)
    st.write("")
    
    st.markdown("#### 📋 策略條件檢視")
    
    def render_row(label, val_str, cond):
        tag = f"<span class='status-pass' style='float:right; background-color: rgba(16, 185, 129, 0.15); color: #10b981; padding: 2px 8px; border-radius: 9999px; font-size: 11px; font-weight: 900;'>PASS</span>" if cond else f"<span class='status-wait' style='float:right; background-color: rgba(30, 41, 59, 0.8); color: #64748b; padding: 2px 8px; border-radius: 9999px; font-size: 11px; font-weight: 900;'>WAIT</span>"
        return f"""
        <div style='padding:10px 5px; border-bottom:1px solid rgba(255,255,255,0.05); font-family:sans-serif;'>
            <span style='font-size:13px; font-weight:600; color:#e2e8f0;'>{label}</span>
            <span style='font-size:11px; color:#64748b; margin-left:5px;'>({val_str})</span>
            {tag}
        </div>
        """
    
    rows_html = "<div style='background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border: 1px solid rgba(255,255,255,0.05); border-radius: 16px; padding: 15px; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.3);'>" + \
                render_row("股價高於 20MA", f"{latest['Close']:.1f} > {latest['ma20']:.1f}", latest['cond_ma20']) + \
                render_row("股價高於 60MA", f"{latest['Close']:.1f} > {latest['ma60']:.1f}", latest['cond_ma60']) + \
                render_row("均線多頭排列", "20MA > 60MA", latest['cond_ma_trend']) + \
                render_row("KD 金叉維持", f"K:{latest['k']:.1f} > D:{latest['d']:.1f}", latest['cond_kd_cross']) + \
                render_row("K 值大於 50", f"K:{latest['k']:.1f} > 50", latest['cond_k_high']) + \
                render_row("當日量增突破", "量 > 5日均量", latest['cond_vol']) + \
                "</div>"
                
    st.components.v1.html(rows_html, height=320)
