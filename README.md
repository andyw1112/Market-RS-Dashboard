# RS Thrust Rate Dashboard

每個美股交易日收市後自動更新，顯示約 170 隻 ETF 相對 **RSP**（S&P 500 Equal Weight）嘅相對強度。

```
RS(t)            = Close_ETF(t) / Close_RSP(t)          # 收市價，非 Adj Close
RS Thrust Rate % = 100 × #{k=1..6  : RS(0) > RS(-k)} / 6
1-Mth RS %       = 100 × #{k=1..20 : RS(0) > RS(-k)} / 20
```

## 結構

| 路徑 | 用途 |
|---|---|
| `config/tickers.csv` | ETF 清單（`group,ticker,name`）—— 加減 ticker 只改呢度 |
| `config/index_condition.csv` | 「Index condition」面板嘅指數／幣（`label,symbol`，Yahoo 代號） |
| `scripts/fetch.py` | yfinance 攞 ~400 日 OHLC；攞唔到嘅 ticker 會 retry，再唔得就標 No data |
| `scripts/compute.py` | RS / Thrust / 其他欄位 |
| `scripts/update.py` | 主程式 → `data/latest.json` + `data/history/YYYY-MM-DD.json` + `data/history/index.json` |
| `site/` | 靜態網站（HTML / JS / CSS，inline SVG sparkline） |
| `tests/test_compute.py` | 用原 Google Sheet CSV 驗證公式（170/170） |
| `.github/workflows/update.yml` | 定時更新 + 部署 GitHub Pages |

## 本地使用

```bash
pip install -r requirements.txt
pytest -q
python scripts/update.py          # 交易日冇變就唔寫檔；加 --force 強制重寫
python -m http.server 8765        # 然後開 http://localhost:8765/site/
```

## 部署（GitHub Pages）

1. 將呢個 folder push 去一個 GitHub repo（branch `main`）。
2. Repo → **Settings → Pages → Build and deployment → Source** 揀 **GitHub Actions**。
3. Repo → **Settings → Actions → General → Workflow permissions** 揀 **Read and write permissions**（workflow 要 commit `data/`）。
4. **Actions → Update RS dashboard → Run workflow** 手動跑一次，完成後網址會喺 run summary 顯示。

之後每個平日 UTC 22:30（香港時間 06:30）自動跑。美股假期時最新交易日冇變，唔會 commit。失敗 GitHub 會 email 通知。

## 備註

- `% Gap` = Open(0)/Close(−1) − 1（正常定義；原 Sheet 嘅 "% change" 係負嘅 gap）。
- `% 1-Mth` = Close(0)/Close(−21) − 1（跟 spec）。原 Sheet 實際係用 30 日 sparkline 第一日（Close(−29)），所以數字會唔同。
- 跑緊美股交易時段時，yfinance 會俾未完成嘅當日 K 線，`fetch.py` 會自動剔走。
- `DRAM` = Roundhill Memory ETF（2026-04 上市，未夠一年，% Off 52W High 係計上市以來高位）。ARKK / ARKG / ARKX / REM / PAVE 已改用美國上市版本。

## Financial calendar

`data/calendar.json` 由 `scripts/calendar_fetch.py` 產生，每次 update 都會刷新（逢星期日 UTC 22:30 會額外跑一次，香港時間星期一朝早就有新一週）。

- **Economic data**：ForexFactory 每週 feed，只取 US + High impact（CPI、PPI、NFP、FOMC、Retail Sales 等）。呢個 feed 有 rate limit（大約 5 分鐘 2 次），本地唔好密密 run。
- **Earnings**：yfinance（Yahoo earnings calendar），市值 ≥ US$10B（100億），唔包 OTC 外國股。要改門檻就改 `EARNINGS_MIN_CAP`。
- 任何一個來源失敗都唔會令 run 失敗，會保留同一週上次成功攞到嘅數據。

## Stocks scanner

`scripts/scanner.py` 掃全部美股普通股（Nasdaq Trader symbol directory，剔走 ETF、warrant、unit、right、優先股、notes），結果寫入 `data/scanner.json`。有新交易日先會跑（大約 5,900 隻，要幾分鐘）。

共同條件：收市 > $2、20 日平均成交額 > US$10M、市值 ≥ US$500M（市值、sector、industry 由 Yahoo 攞）。

| Scanner | 條件 |
|---|---|
| 30D HTF | 收市 ÷ 過去 30 個交易日最低位 − 1 ≥ 50%，收市 > daily 50 EMA |
| 60D HTF | 同上，60 日、≥ 75% |
| 100D HTF | 同上，100 日、≥ 75% |
| 52W High | 收市距離 52 週（252 日）最高位 3% 以內 |

**綠色 ticker** = 呢隻股票所屬 sector ETF 嘅 1-Mth RS ≥ 90%（即係出現喺「Sector RS 90% above」嗰啲）。股票 → ETF 嘅對應喺 `config/sector_map.csv`：`sector` 行要 Yahoo sector 完全一樣，`industry` 行係 Yahoo industry 包含嗰段字就算。想改對應直接改呢個檔。

本地淨係想重跑 scanner：`python scripts/update.py --scan-only`；更新其他嘢但唔跑 scanner：`--skip-scan`。
