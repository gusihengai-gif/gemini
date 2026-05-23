import datetime
import pandas as pd
import pandas_ta as ta
import requests

# ==========================================
# 1. 設定參數與資料抓取
# ==========================================
STOCK_ID = "2330"  # 可自行更換股票代號，例如台積電 2330
API_BASE = "https://api.finmindtrade.com/api/v4/data"

# 計算需要足夠的歷史資料（計算 60MA 與 KD 至少需要數個月的資料，這裡抓取近一年）
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

print(f"正在抓取 {STOCK_ID} 的歷史股價資料...")
response = requests.get(API_BASE, params=params)
data = response.json()

if data["msg"] != "success" or not data["data"]:
    print("資料抓取失敗，請檢查網路或股票代碼。")
    exit()

# 轉換為 DataFrame 並整理格式
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
# 確保數值型態正確
for col in ["Close", "Open", "High", "Low", "Volume"]:
    df[col] = pd.to_numeric(df[col])

# 依日期排序
df = df.sort_values("date").reset_index(drop=True)

# ==========================================
# 2. 計算技術指標（依照原 JavaScript 邏輯）
# ==========================================
# A. 均線計算 (20 MA, 60 MA, 5 日均量)
df["ma20"] = ta.sma(df["Close"], length=20)
df["ma60"] = ta.sma(df["Close"], length=60)
df["v_ma5"] = ta.sma(df["Volume"], length=5)

# B. KD 指標計算 (參數 9, 3, 3)
# pandas_ta 的 rsi/stoch 預設可能因平滑方式與台灣習慣稍有不同
# 這裡使用符合台灣股市標準的 KD 計算方式（K=3, D=3 平滑）
kd = ta.stoch(df["High"], df["Low"], df["Close"], k=9, d=3, smooth_k=3)
# 根據 pandas_ta 的欄位名稱命名為 k 與 d
df["k"] = kd["STOCHk_9_3_3"]
df["d"] = kd["STOCHd_9_3_3"]

# 移除因計算指標產生的空值(NaN)行
df = df.dropna().reset_index(drop=True)

# ==========================================
# 3. 策略條件判斷 (保留原買入訊號邏輯)
# ==========================================
# 逐行判斷是否符合條件
df["cond_ma20"] = df["Close"] > df["ma20"]  # 價格在 20 MA 之上
df["cond_ma60"] = df["Close"] > df["ma60"]  # 價格在 60 MA 之上
df["cond_ma_trend"] = df["ma20"] > df["ma60"]  # 多頭排列 ma20 > ma60
df["cond_kd_cross"] = df["k"] > df["d"]  # K 值大於 D 值
df["cond_k_high"] = df["k"] > 50  # K 值大於 50
df["cond_vol"] = df["Volume"] > df["v_ma5"]  # 當日成交量大於 5日均量

# 必須全部條件皆為 True 才是買進訊號
df["signal"] = (
    df["cond_ma20"]
    & df["cond_ma60"]
    & df["cond_ma_trend"]
    & df["cond_kd_cross"]
    & df["cond_k_high"]
    & df["cond_vol"]
)

# ==========================================
# 4. 輸出最新一筆的結果
# ==========================================
latest = df.iloc[-1]
latest_date = latest["date"].strftime("%Y-%m-%d")

print("\n" + "=" * 40)
print(f"【策略篩選結果】 股票代號: {STOCK_ID}  日期: {latest_date}")
print("=" * 40)
print(f"當日收盤價: {latest['Close']} | 成交量: {int(latest['Volume'])}")
print(f"20 MA: {latest['ma20']:.2f} | 60 MA: {latest['ma60']:.2f}")
print(f"K 值: {latest['k']:.2f} | D 值: {latest['d']:.2f}")
print("-" * 40)
print("【各項條件檢視】")
print(f"1. 股價 > 20MA:        {'PASS' if latest['cond_ma20'] else 'WAIT'}")
print(f"2. 股價 > 60MA:        {'PASS' if latest['cond_ma60'] else 'WAIT'}")
print(f"3. 均線多頭(20>60):     {'PASS' if latest['cond_ma_trend'] else 'WAIT'}")
print(f"4. KD金叉維持(K>D):    {'PASS' if latest['cond_kd_cross'] else 'WAIT'}")
print(f"5. K值大於50(多方):     {'PASS' if latest['cond_k_high'] else 'WAIT'}")
print(f"6. 量增(成交量>5日均量): {'PASS' if latest['cond_vol'] else 'WAIT'}")
print("-" * 40)

# 最終綜合訊號判斷
if latest["signal"]:
    print("▶ 最終決策狀態: 【 符合策略進場 】")
else:
    print("▶ 最終決策狀態: 【 觀望等待訊號 】")
print("=" * 40)
