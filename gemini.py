import datetime
import pandas as pd
import requests
import streamlit as st
import plotly.graph_objects as go

# ==========================================
# 0. 網頁全域風格配置 (使用 Streamlit 官方標準 API)
# ==========================================
st.set_page_config(
    page_title="Stock Signal Dashboard",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 徹底移除所有 st.markdown(..., unsafe_allowed_html=True)，絕不踩 Python 3.14 的底層相容 Bug

# ==========================================
# 1. 股票資料庫 (精簡為 3 檔，方便您後續自行新增)
# ==========================================
STOCK_DATABASE = [
    {"id": "2330", "name": "台積電"},
    {"id": "9958", "name": "世紀鋼"},
    {"id": "9945", "name": "潤泰新"}
    # 您可以在此處依據 {"id": "代碼", "name": "名稱"}, 的格式手動複製新增股票
]
stock_options = [f"{s['id']} {s['name']}" for s in STOCK_DATABASE]

# Sidebar 設定 (使用純文字 Markdown，不帶 HTML 參數)
st.sidebar.markdown("## 🔍 策略篩選系統")
selected_stock_str = st.sidebar.selectbox("選擇或輸入股票", stock_options, index=0)
STOCK_ID = selected_stock_str.split(" ")[0]

# ==========================================
# 2. 資料抓取與對齊 (抓取 600 天確保 240天均線有足夠數據計算)
# ==========================================
API_BASE = "https://api.finmindtrade.com/api/v4/data"
end_date = datetime.date.today().strftime("%Y-%m-%d")
start_date = (datetime.date.today() - datetime.timedelta(days=600)).strftime("%Y-%m-%d")

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

# 記住最後一天的數據（用於右側條件看板檢視）
latest = df.iloc[-1]
latest_date = latest["date"].strftime("%Y-%m-%d")

# ==========================================
# 5. UI 畫面渲染
# ==========================================
st.title(f"📈 {selected_stock_str}")
st.text(f"數據分析更新時間：{latest_date}")

left_col, right_col = st.columns([2, 1], gap="large")

with left_col:
    st.markdown("### 📊 互動式趨勢分析圖表")
    
    # 快速看盤時間區間切換按鈕
    time_options = ["10天", "20天", "30天", "60天", "120天", "240天", "全部"]
    selected_period = st.radio(
        "快速切換看盤區間：",
        time_options,
        index=3,  # 預設 60天
        horizontal=True
    )
    
    # 根據按鈕點選結果動態切換 plot_df
    if selected_period == "10天":
        plot_df = df.tail(10)
    elif selected_period == "20天":
        plot_df = df.tail(20)
    elif selected_period == "30天":
        plot_df = df.tail(30)
    elif selected_period == "60天":
        plot_df = df.tail(60)
    elif selected_period == "120天":
        plot_df = df.tail(120)
    elif selected_period == "240天":
        plot_df = df.tail(240)
    else:
        plot_df = df
        
    # 建立 Plotly 圖表
    fig = go.Figure()
    
    # 收盤價折線圖
    fig.add_trace(go.Scatter(
        x=plot_df["date"], y=plot_df["Close"], name="收盤價",
        line=dict(color="#38bdf8", width=2.5)
    ))
    
    # 🎯【已修正：刪除 20MA 和 60MA 線段】不再往圖表添加這兩條均線的 Trace
    
    # 策略進場點
    signal_days = plot_df[plot_df["signal"] == True]
    fig.add_trace(go.Scatter(
        x=signal_days["date"], y=signal_days["Close"], name="策略進場點",
        mode='markers', marker=dict(color='#10b981', size=10, symbol='triangle-up', line=dict(width=1, color='white'))
    ))
    
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor='rgba(15,23,42,0.5)', 
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=20, r=20, t=20, b=20), height=480,
        # 🎯【已修正：刪除上方重複原生圖例】將 showlegend 設為 False 即可徹底隱藏重複區塊
        showlegend=False,
        xaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.05)'),
        yaxis=dict(
            showgrid=True, 
            gridcolor='rgba(255,255,255,0.05)', 
            side="right",
            autorange=True  
        )
    )
    
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

with right_col:
    st.markdown("### 🎯 決策狀態")
    if latest["signal"]:
        st.success("### 🎯 符合所有策略條件：建議進場")
    else:
        st.warning("### ⏳ 條件尚未滿足：觀望等待訊號")
        
    st.write("")
    st.markdown("### 📋 策略細節即時檢視")
    
    def show_condition(label, val_text, is_ok):
        col_lbl, col_val, col_tag = st.columns([2, 2, 1])
        with col_lbl:
            st.write(f"**{label}**")
        with col_val:
            st.caption(f"({val_text})")
        with col_tag:
            if is_ok:
                st.info("PASS")
            else:
                st.text("WAIT")

    # 渲染出條件看板
    show_condition("股價高於 20MA", f"{latest['Close']:.1f} > {latest['ma20']:.1f}", latest['cond_ma20'])
    show_condition("股價高於 60MA", f"{latest['Close']:.1f} > {latest['ma60']:.1f}", latest['cond_ma60'])
    show_condition("均線多頭排列", "20MA > 60MA", latest['cond_ma_trend'])
    show_condition("KD 金叉維持", f"K:{latest['k']:.1f} > D:{latest['d']:.1f}", latest['cond_kd_cross'])
    show_condition("K 值大於 50", f"K:{latest['k']:.1f} > 50", latest['cond_k_high'])
    show_condition("當日量增突破", "量 > 5日均量", latest['cond_vol'])
