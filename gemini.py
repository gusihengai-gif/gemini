import datetime
import pandas as pd
import requests
import streamlit as st

# ==========================================
# 1. Streamlit 介面設定與參數抓取
# ==========================================
st.title("股票策略分析面板")

# 在側邊欄提供股票代號輸入，預設 2330
STOCK_ID = st.sidebar.text_input("輸入台灣股票代號", value="2330").strip()

API_BASE = "https://api.finmindtrade.com/api/v4/data"

# 計算需要足夠的歷史資料，抓取近 365 天
end_date = datetime.date.today().strftime("%Y-%m-%d")
start_date = (datetime.date.today() - datetime.timedelta(days=365)).strftime(
    "%Y-%m-%d"
)

params = {
    "dataset": "TaiwanStockPrice",
    "data_id": STOCK_ID,
    "start_date": start_date,
    "end_date": end_date,
}

response = requests.get(API_BASE, params=params)
data = response.json()

if data["msg"] != "success" or not data["data"]:
    st.error(f"資料抓取失敗，請檢查網路或股票代碼 【{STOCK_ID}】 是否正確。")
    st.stop()  # 替代原有的 sys.exit()，讓 Streamlit 優雅停止而不崩潰

# 轉換為 DataFrame
df = pd.DataFrame(data["data"])
df["date"] = pd.to_datetime(df["date"])
df = df.rename(
    columns={
        "close": "Close",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "volume": "Volume",
    }
)
for col in ["Close", "Open", "High", "Low", "Volume"]:
    df[col] = pd.to_numeric(df[col])

df = df.sort_values("date").reset_index(drop=True)

# ==========================================
# 2. 原生技術指標計算（修正 KD 邏輯失真問題）
# ==========================================
# A. 計算均線與均量
df["ma20"] = df["Close"].rolling(window=20).mean()
df["ma60"] = df["Close"].rolling(window=60).mean()
df["v_ma5"] = df["Volume"].rolling(window=5).mean()

# B. 計算 KD 指標 (9, 3, 3)
df["rsv_high"] = df["High"].rolling(window=9).max()
df["rsv_low"] = df["Low"].rolling(window=9).min()

# 計算 RSV 值
df["rsv"] = (
    (df["Close"] - df["rsv_low"]) / (df["rsv_high"] - df["rsv_low"])
) * 100

# 【修正點】精準計算 KD 迴圈
k_list = []
d_list = []
current_k = 50.0
current_d = 50.0

for rsv in df["rsv"]:
    if pd.isna(rsv):
        # 在前 8 天 RSV 為空值時，KD 保持 50，且不讓失真資料影響後續權重
        k_list.append(None)
        d_list.append(None)
    else:
        # 台灣標準 KD 平滑公式
        current_k = (2 / 3) * current_k + (1 / 3) * rsv
        current_d = (2 / 3) * current_d + (1 / 3) * current_k
        k_list.append(current_k)
        d_list.append(current_d)

df["k"] = k_list
df["d"] = d_list

# 移除因計算指標（特別是 ma60 需要 60 天資料）產生的早期空值行
df = df.dropna().reset_index(drop=True)

# ==========================================
# 3. 策略條件判斷
# ==========================================
df["cond_ma20"] = df["Close"] > df["ma20"]
df["cond_ma60"] = df["Close"] > df["ma60"]
df["cond_ma_trend"] = df["ma20"] > df["ma60"]
df["cond_kd_cross"] = df["k"] > df["d"]
df["cond_k_high"] = df["k"] > 50
df["cond_vol"] = df["Volume"] > df["v_ma5"]

df["signal"] = (
    df["cond_ma20"]
    & df["cond_ma60"]
    & df["cond_ma_trend"]
    & df["cond_kd_cross"]
    & df["cond_k_high"]
    & df["cond_vol"]
)

# ==========================================
# 4. Streamlit 網頁畫面輸出
# ==========================================
if df.empty:
    st.warning("歷史資料量不足以計算 60MA 與 KD 指標，請確認該股票是否有足夠交易日。")
    st.stop()

latest = df.iloc[-1]
latest_date = latest["date"].strftime("%Y-%m-%d")

st.subheader(f"股票：{STOCK_ID}  |  分析日期：{latest_date}")

col1, col2, col3 = st.columns(3)
col1.metric("當日收盤價", f"{latest['Close']:.2f}")
col2.metric("20 MA / 60 MA", f"{latest['ma20']:.2f} / {latest['ma60']:.2f}")
col3.metric("K 值 / D 值", f"{latest['k']:.2f} / {latest['d']:.2f}")

st.markdown("### 【各項條件檢視】")


def get_status_tag(cond):
    return "🟩 **PASS**" if cond else "🟥 **WAIT**"


st.write(f"{get_status_tag(latest['cond_ma20'])} 1. 股價 > 20MA")
st.write(f"{get_status_tag(latest['cond_ma60'])} 2. 股價 > 60MA")
st.write(f"{get_status_tag(latest['cond_ma_trend'])} 3. 均線多頭排列 (20MA > 60MA)")
st.write(f"{get_status_tag(latest['cond_kd_cross'])} 4. KD金叉維持 (K > D)")
st.write(f"{get_status_tag(latest['cond_k_high'])} 5. K值大於50 (多方掌控)")
st.write(f"{get_status_tag(latest['cond_vol'])} 6. 量增 (成交量 > 5日均量)")

st.markdown("---")
if latest["signal"]:
    st.success("## 最終決策狀態：【 符合策略進場 】")
else:
    st.warning("## 最終決策狀態：【 觀望等待訊號 】")
