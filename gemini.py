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

# 抓取過去 365 天的歷史資料
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

try:
    response = requests.get(API_BASE, params=params)
    data = response.json()
except Exception as e:
    st.error(f"❌ 連線至 FinMind API 失敗，請稍後再試。錯誤訊息: {e}")
    st.stop()

if data.get("msg") != "success" or not data.get("data"):
    st.error(
        f"❌ 找不到股票代碼 【{STOCK_ID}】 的資料，請確認代碼是否正確，或該股票今天是否無交易。"
    )
    st.stop()

# 轉換為 DataFrame
df = pd.DataFrame(data["data"])

# 【除錯專用顯示】如果在部署時還有問題，這行會列出 API 給了什麼
# st.write("原始欄位檢查：", list(df.columns))

# 建立一個對照表，不管大小寫都對應到標準名稱
mapping = {}
for col in df.columns:
    col_lower = col.lower()
    if col_lower == "close":
        mapping[col] = "Close"
    elif col_lower == "open":
        mapping[col] = "Open"
    elif col_lower == "high":
        mapping[col] = "High"
    elif col_lower == "low":
        mapping[col] = "Low"
    elif col_lower in ["volume", "trading_volume"]:
        mapping[col] = "Volume"
    elif col_lower == "date":
        mapping[col] = "date"

# 重新命名欄位
df = df.rename(columns=mapping)

# 檢查必要的欄位是否都有成功對應
required_cols = ["Close", "Open", "High", "Low", "Volume", "date"]
missing_cols = [c for c in required_cols if c not in df.columns]

if missing_cols:
    st.error(
        f"❌ API 回傳資料異常！缺少關鍵欄位: {missing_cols}。無法進行策略計算。"
    )
    st.info(f"API 目前回傳的實際欄位為: {list(df.columns)}")
    st.stop()

# 確保資料型態與排序
df["date"] = pd.to_datetime(df["date"])
for col in ["Close", "Open", "High", "Low", "Volume"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")

df = df.sort_values("date").reset_index(drop=True)

# 檢查歷史資料長度是否足夠
if len(df) < 60:
    st.warning(
        f"⚠️ 股票 {STOCK_ID} 的歷史交易天數不足 60 天（目前僅有 {len(df)} 天），無法計算 60MA 策略指標。"
    )
    st.stop()

# ==========================================
# 2. 原生技術指標計算
# ==========================================
df["ma20"] = df["Close"].rolling(window=20).mean()
df["ma60"] = df["Close"].rolling(window=60).mean()
df["v_ma5"] = df["Volume"].rolling(window=5).mean()

# 計算 KD 指標 (9, 3, 3)
df["rsv_high"] = df["High"].rolling(window=9).max()
df["rsv_low"] = df["Low"].rolling(window=9).min()

# 避免除以 0 的安全保護
df["rsv"] = (
    (df["Close"] - df["rsv_low"]) / (df["rsv_high"] - df["rsv_low"] + 1e-8)
) * 100

k_list = []
d_list = []
current_k = 50.0
current_d = 50.0

for rsv in df["rsv"]:
    if pd.isna(rsv):
        k_list.append(None)
        d_list.append(None)
    else:
        current_k = (2 / 3) * current_k + (1 / 3) * rsv
        current_d = (2 / 3) * current_d + (1 / 3) * current_k
        k_list.append(current_k)
        d_list.append(current_d)

df["k"] = k_list
df["d"] = d_list

# 移除空值行
df = df.dropna().reset_index(drop=True)

if df.empty:
    st.error("❌ 指標計算後無有效數據，請確認該股票近期交易狀況。")
    st.stop()

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
