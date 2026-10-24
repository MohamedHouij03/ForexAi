<div align="center">

# 📈 Forex AI: Machine-Learning Trading Assistant for Forex & Spot Metals

**Short-horizon probabilistic forecasting of trade outcomes on 15-minute FX candles,
with leakage-free validation, a cost-aware backtester and a live paper-trading coach.**

[![CI](https://img.shields.io/badge/CI-GitHub_Actions-2088FF?logo=githubactions&logoColor=white)](.github/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-282_passing-success?logo=pytest&logoColor=white)](backend/tests)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Paper trading only](https://img.shields.io/badge/mode-paper_trading_only-orange)](#%EF%B8%8F-disclaimer)

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![pandas](https://img.shields.io/badge/pandas-2.x-150458?logo=pandas&logoColor=white)](https://pandas.pydata.org/)
[![scikit-learn](https://img.shields.io/badge/scikit--learn-1.5%2B-F7931E?logo=scikitlearn&logoColor=white)](https://scikit-learn.org/)
[![XGBoost](https://img.shields.io/badge/XGBoost-2.1%2B-189FDD)](https://xgboost.ai/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org/)
[![SQLite](https://img.shields.io/badge/SQLite-default-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-optional-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)

[![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-4-06B6D4?logo=tailwindcss&logoColor=white)](https://tailwindcss.com/)
[![Lightweight Charts](https://img.shields.io/badge/TradingView-Lightweight_Charts-131722?logo=tradingview&logoColor=white)](https://www.tradingview.com/lightweight-charts/)
[![Twelve Data](https://img.shields.io/badge/data-Twelve_Data_API-2B6CB0)](https://twelvedata.com/)
[![Telegram](https://img.shields.io/badge/alerts-Telegram_Bot-26A5E4?logo=telegram&logoColor=white)](https://core.telegram.org/bots)

</div>

---

## 📄 Abstract

This project asks a simple, well-defined research question:

> *Can a supervised machine-learning model, trained only on past 15-minute price candles, predict which
> short-term trades (BUY / SELL / WAIT) will reach their profit target before their stop loss, well enough
> to cover realistic trading costs?*

The project is an end-to-end, reproducible system. It has a **data pipeline** (download, clean and validate
~980,000 candles for six instruments, 2020–2026), **70 scale-free engineered features** proven free of
look-ahead bias, **barrier-based outcome labels** simulated with the spread included, and **three
classifiers** (Logistic Regression, Random Forest, XGBoost). These are evaluated with a **chronological
train / validation / test split, walk-forward analysis and a statistical deployability gate**. The models
then run in a **live signal engine** with risk-managed position sizing and a web dashboard that coaches a
human through paper trades.

**Main finding:** the models beat a naive baseline at *classification* (lower log-loss). They do **not**
produce a statistically significant trading edge after costs. The best model scores +0.017 R per trade on
the untouched test period, but the 95% lower bound is −0.050 R and only 20% of walk-forward folds were
profitable. A live paper-trading forward test with a low decision threshold confirmed the negative
expectancy. The system therefore keeps its *deployability gate* closed: in `proven` mode it answers
**WAIT**. This negative result, reached by a careful method, is the project's main contribution.

---

## 🖼 Screenshots

<table>
  <tr>
    <td width="50%"><b>Live Assistant</b>: 15-minute chart with EMA 20/50/200 and past signals, the current BUY/SELL/WAIT call, and risk settings</td>
    <td width="50%"><b>AI Model &amp; Performance</b>: the three models compared per trade after costs, and the final test per instrument</td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/live-assistant.png" alt="Live Assistant dashboard: EUR/USD 15-minute candlestick chart with three moving averages and signal markers, a WAIT signal card with model probabilities, and the paper account's risk configuration"></td>
    <td><img src="docs/screenshots/model-performance.png" alt="Model page: XGBoost marked not proven, comparison table of Logistic Regression, Random Forest and XGBoost on validation and walk-forward data, and final test results per instrument with log-loss and confusion matrix"></td>
  </tr>
  <tr>
    <td><b>Data validation</b>: every check run on the cleaned EUR/USD dataset, with coverage by year and the largest gaps</td>
    <td><b>Live track record</b>: paper trades closed by the user next to every AI call, scored automatically against what the market did</td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/data-validation.png" alt="Dataset validation report for EUR/USD 15-minute data: status WARN, 164,138 candles, 98.99% coverage, a table of OK, INFO and WARN checks, and coverage by year from 2020 to 2026"></td>
    <td><img src="docs/screenshots/track-record.png" alt="Track record panel: paper balance $95.53 from $100, 32 closed trades, 89 AI calls scored with an average of -0.25 R, and tables of closed trades and recent AI calls with their outcomes"></td>
  </tr>
  <tr>
    <td><b>Mobile: Live Assistant</b></td>
    <td><b>Mobile: AI Model &amp; Performance</b></td>
  </tr>
  <tr>
    <td align="center"><img src="docs/screenshots/live-assistant-mobile.png" width="260" alt="Live Assistant on a phone: watched pairs all on WAIT, EUR/USD last price and market closed, and the start of the chart"></td>
    <td align="center"><img src="docs/screenshots/model-performance-mobile.png" width="260" alt="Model page on a phone: current XGBoost model, its training, validation and test periods, and the not-proven warning"></td>
  </tr>
</table>

<sub>Screenshots show the project's real downloaded market data, trained model and the author's own paper-trading
record. No example data was added. They were taken on a weekend with the live engine switched off, so the
market shows as closed and prices are from the last candle.</sub>

---

## 📚 Table of contents

- [Screenshots](#-screenshots)
- [Key concepts & terminology](#-key-concepts--terminology)
- [Data source](#-data-source)
- [Methodology](#-methodology)
  - [Pipeline overview](#pipeline-overview)
  - [1. Data collection](#1-data-collection)
  - [2. Data cleaning & validation](#2-data-cleaning--validation)
  - [3. Feature engineering](#3-feature-engineering)
  - [4. Target labelling](#4-target-labelling)
  - [5. Models](#5-models)
  - [6. Evaluation protocol](#6-evaluation-protocol)
  - [7. Backtesting](#7-backtesting)
  - [8. Live signal engine & coach](#8-live-signal-engine--coach)
- [Results](#-results)
- [Technologies](#-technologies)
- [System architecture](#-system-architecture)
- [Project structure](#-project-structure)
- [Getting started](#-getting-started)
- [Configuration](#%EF%B8%8F-configuration)
- [REST & WebSocket API](#-rest--websocket-api)
- [Testing](#-testing)
- [Limitations](#-limitations)
- [Future work](#-future-work)
- [Disclaimer](#%EF%B8%8F-disclaimer)
- [License](#-license)

---

## 🧠 Key concepts & terminology

| Term | Meaning in this project |
|------|-------------------------|
| **Forex (FX)** | The foreign-exchange market, where currency **pairs** such as EUR/USD are traded. |
| **Spot metals** | Gold (XAU/USD), silver (XAG/USD), platinum and palladium quoted against the US dollar. |
| **Candle (OHLC)** | One time bar with **O**pen, **H**igh, **L**ow and **C**lose prices. Granularity here is **M15** (15 minutes). |
| **Pip** | The smallest standard price step: 0.0001 for most pairs, 0.01 for JPY pairs and gold. |
| **Spread** | The difference between the ask (buy) and bid (sell) price. It is the main **transaction cost** and is modelled explicitly. |
| **Time-series forecasting** | Predicting a future quantity from past observations. Here the forecast is **probabilistic and short-horizon**: P(BUY wins), P(SELL wins), P(neither) over the next 15–60 minutes. |
| **Multi-class classification** | The forecasting task is framed as three classes: BUY / SELL / WAIT. |
| **Technical indicators** | Deterministic transforms of price: EMA, RSI, MACD, ATR, Bollinger Bands, pivots, etc. |
| **ATR (Average True Range)** | A volatility measure (14 candles). Stops, targets and most features are expressed in ATR units. |
| **Feature engineering** | Turning raw candles into model inputs. All 70 features are **scale-free**, so one model can learn across pairs with very different prices. |
| **Look-ahead bias / data leakage** | Using information that would not have been available at decision time. Prevented by construction and **proven by tests**. |
| **Barrier labelling** | Each candle is labelled by simulating a trade with a **take-profit** barrier, a **stop-loss** barrier and a **time** barrier (similar to the *triple-barrier method*). |
| **R-multiple (R)** | A trade result divided by the amount risked: hitting the stop = −1 R. It makes results comparable across pairs and position sizes. |
| **Expectancy** | Mean R per trade. A strategy needs positive expectancy **after costs**. |
| **Profit factor** | Gross profit ÷ gross loss (> 1 = profitable). |
| **Chronological split** | Train → validation → test strictly in time order, never shuffled. |
| **Embargo** | A time gap at each split boundary, so labels whose future window crosses the boundary cannot leak. |
| **Walk-forward analysis** | Repeatedly retrain on an expanding past window and test on the next unseen period. It simulates how the model would really have been used. |
| **Out-of-sample (OOS)** | Data the model never saw while it was fitted or tuned. |
| **Backtesting** | Replaying OOS signals with realistic account rules, costs and gap slippage. |
| **Drawdown / Sharpe ratio / risk of ruin** | Peak-to-trough equity loss; risk-adjusted return; Monte-Carlo probability of losing the account. |
| **Position sizing** | Choosing trade size so that a stop-out loses at most a fixed % of the balance (default 1%). |
| **Paper trading** | Simulated trading with no real money, here on a broker *demo* account. |
| **Deployability gate** | The set of statistical conditions a model must pass before it may emit live signals. |

---

## 🗄 Data source

| | |
|---|---|
| **Provider** | [Twelve Data](https://twelvedata.com/) REST API (default), with the free *Basic* plan. [OANDA v20](https://developer.oanda.com/) is supported as an alternative (adds bid/ask and volume). |
| **Live data** | Twelve Data REST polling at every candle close, plus the Twelve Data **WebSocket** for real-time ticks (EUR/USD and XAU/USD on the free plan). |
| **Instruments studied** | EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD, XAU/USD (any forex pair or spot metal can be added). Crypto and equities are rejected by design. |
| **Granularity** | 15-minute candles (M15). 1-hour candles (H1) are derived by resampling for comparison. |
| **Period** | January 2020 → September 2026 |
| **Size** | **979,792 clean M15 candles** (≈ 164k per instrument, about 99% coverage of trading hours) |
| **Price type** | Mid prices (no bid/ask or volume on the free plan), so a conservative per-instrument spread is modelled. |
| **Rate limits** | 8 requests/min and 800 requests/day. The client throttles itself and resumes interrupted downloads. |

| Instrument | Clean candles | Coverage | Notable events kept in the data |
|------------|--------------:|---------:|---------------------------------|
| EUR/USD | 164,138 | 98.99% | 2022-11-10 US CPI shock |
| GBP/USD | 164,439 | 99.14% | Sept 2022 UK "mini-budget" crash |
| USD/JPY | 164,284 | 99.02% | 2022 Japanese FX intervention, BoJ decisions |
| AUD/USD | 164,338 | 99.01% | March 2020 COVID crash |
| USD/CAD | 164,617 | 99.03% | — |
| XAU/USD | 157,976 | 98.89% | 2021-08-09 gold flash crash |

> Market data is **not** included in this repository (provider terms of use, and size). It is
> re-downloaded with one command using a free API key; see [Getting started](#-getting-started).

---

## 🔬 Methodology

### Pipeline overview

```mermaid
flowchart LR
    A[Twelve Data / OANDA<br/>REST API] -->|paginated, resumable,<br/>rate-limited| B[(Raw candles<br/>SQLite / PostgreSQL)]
    B --> C[Validate raw]
    C --> D[Clean<br/>remove impossible &<br/>weekend candles]
    D --> E[Validate clean]
    E --> F[(Parquet<br/>ML dataset)]
    F --> G[70 scale-free<br/>features]
    G --> H[Barrier labels<br/>BUY / SELL / WAIT]
    H --> I[Train 3 models<br/>LR · RF · XGBoost]
    I --> J[Validation ·<br/>walk-forward · test]
    J --> K{Deployability<br/>gate}
    K -->|pass| L[Live signals]
    K -->|fail| M[WAIT only /<br/>practice mode]
    J --> N[Backtester<br/>account rules + costs]
```

### 1. Data collection

`app/data/` implements a provider-agnostic client (`providers.py`, `twelvedata_client.py`, `oanda_client.py`):

- Paginated history download from 2020, **resumable**: every page is committed, so an interrupted run
  continues where it stopped.
- Idempotent upserts (overlapping candles are never duplicated), and the candle that is still forming is
  never stored.
- One provider per instrument: mixing two providers' data for one instrument is refused.

### 2. Data cleaning & validation

Raw candles are stored untouched. The ML dataset is produced by **removing** rows, never by repairing or
filling them, because repairs would invent prices:

| Removed | Reason |
|---------|--------|
| Missing values, prices ≤ 0, high/low not bracketing open/close, ask < bid | Physically impossible candles |
| Duplicate timestamps | Keep the first occurrence |
| Candles inside the asset class's **weekend closure** | Indicative quotes no broker would fill |

Each dataset gets a validation report (`PASS` / `WARN` / `FAIL`) with about 20 checks. Examples: unique,
increasing and 15-minute-aligned UTC timestamps; OHLC consistency; long gaps; coverage against **real trading
hours** (DST-aware New York sessions, metal daily breaks, Good Friday and holiday closures); extreme returns;
spread anomalies. Every removed row is written to a CSV with its reason.

### 3. Feature engineering

`app/features/engineering.py` computes **68 price features + 2 instrument-context features = 70 inputs**
per candle:

| Group | Examples |
|-------|----------|
| Returns | log returns over 1–24 candles, also measured in ATRs |
| Trend | price vs EMA 10/20/50/100/200, EMA spreads and slopes (÷ ATR) |
| Momentum | RSI 14, MACD / signal / histogram (÷ ATR), rate of change |
| Volatility | ATR % of price, ATR vs its 100-candle mean, realised volatility, Bollinger width & position |
| Candle shape | body, wicks, range (÷ ATR), body/range ratio |
| Market structure | distance to 24/96-candle highs & lows, swing points, previous-day high/low, daily pivot, R1/S1 |
| Multi-timeframe | H1 and H4 EMA distance, EMA slope and RSI |
| Calendar / session | hour (also as sine/cosine), weekday, Asia / London / New York sessions and overlap (DST-aware) |
| Data quality | missing candles just before / in the last 24 candles |
| Context | `is_metal`, spread ÷ ATR (cost relative to volatility) |

**Guarantees, all covered by tests:**

- **No look-ahead.** Features recomputed on truncated data, or with the future rewritten, must not change.
- **Scale-free.** Features are identical whether price is 1.08 or 150, so one model learns across all pairs.
- **Gap-aware.** Indicators restart after provider holes, and the first 600 candles of each stretch are
  excluded while long EMAs warm up.

### 4. Target labelling

For every candle *t*, `app/models/targets.py` simulates **both** a BUY and a SELL entered at *t*'s close,
under exactly the rules a trader would follow:

- stop loss = `SL × ATR`, take profit = `TP × ATR`, maximum holding = `H` candles
- entry and exit pay half the modelled spread each
- if stop and target are touched inside the same candle, the **stop** is assumed (pessimistic)

```
label = BUY   if the buy reaches its target first
        SELL  if the sell reaches its target first
        WAIT  otherwise (both stopped out, or time ran out)
```

The current model uses SL = 1 ATR, TP = 1 ATR, H = 2 candles (30 min). On the test period the classes are
**BUY 19.5% / SELL 20.6% / WAIT 59.9%**. Trading blindly loses about **−0.15 R per trade**, which is the
cost of the spread. That is the bar a model has to beat.

### 5. Models

| Model | Configuration | Role |
|-------|---------------|------|
| **Logistic Regression** | Standardised inputs, L2 (C = 0.1) | Linear, interpretable baseline |
| **Random Forest** | 200 trees, depth 10, min leaf 200, 25% bootstrap | Non-linear, robust to noise |
| **XGBoost** | Gradient-boosted trees, depth 4, η = 0.03, early stopping on validation log-loss | Strong tabular learner |

All three output class probabilities P(SELL), P(WAIT), P(BUY). A trade is signalled when
`max(P(BUY), P(SELL)) ≥ threshold`.

### 6. Evaluation protocol

Accuracy is *not* the objective, because a model that always says WAIT is about 60% accurate and earns
nothing. Models are judged on the **R-expectancy of the trades they would have taken**, with costs included
and no overlapping trades per instrument.

```mermaid
gantt
    dateFormat YYYY-MM
    axisFormat %Y
    title Chronological split (never shuffled, 30-min embargo at each boundary)
    section Fit
    Train (569,672 rows)          :2020-02, 2024-01
    section Tune
    Validation (190,105 rows)     :2024-01, 2025-06
    section Final check
    Untouched test (189,961 rows) :2025-06, 2026-09
```

1. **Validation** chooses the threshold and the model.
2. **Walk-forward**: 5 expanding folds, all before the test period, each retrained from scratch.
3. **Test**: the chosen model is refitted on train + validation and scored **once** on the untouched period.

**Deployability gate.** Live signals are allowed only if **all** of these hold:
1. validation: ≥ 200 trades and the 95% one-sided lower confidence bound of mean R > 0;
2. walk-forward: positive mean R overall **and** in ≥ 60% of folds;
3. test: positive mean R.

### 7. Backtesting

`app/trading/backtest.py` replays the **out-of-sample** predictions with real account constraints:
compounding position size (1% risk, margin cap, 30:1 leverage), maximum open trades, a 3% daily loss stop,
no entries before the weekend close, entry at bid/ask, and **gap slippage**: a candle that opens beyond the
stop or target fills at the open. It reports final balance, win rate, profit factor, max drawdown, Sharpe,
streaks, breakdowns by session/month/year/instrument, and a **Monte-Carlo risk of ruin**.

### 8. Live signal engine & coach

`app/live/service.py` runs inside the API process:

1. Fetches each new 15-minute candle for every watchlist instrument (1 request per pair per candle).
2. Recomputes features exactly as in training, runs the model and applies every risk rule.
3. Publishes **BUY / SELL / WAIT with a reason**, plus entry, SL, TP, position size, maximum loss and expiry,
   over WebSocket, as a desktop notification and (optionally) on **Telegram**.
4. A human places the trade on a demo account and confirms the fill. The coach then tracks it live and
   advises when to close (target, stop, time limit, or the model turning against the trade).
5. Every signal, taken or not, is scored automatically. This gives an honest **forward test** on data no
   experiment has seen.

---

## 📊 Results

### Model comparison (current model `v20260926-093747`, SL 1 ATR / TP 1 ATR / 30 min)

| Model | Val. log-loss (baseline 0.928) | Validation mean R (trades) | Walk-forward mean R | Profitable WF folds |
|-------|------:|------:|------:|------:|
| Logistic Regression | 0.873 | +0.037 (452) | −0.071 | 40% |
| Random Forest | 0.859 | −0.062 (267) | −0.058 | 40% |
| **XGBoost** (selected) | **0.850** | **+0.072** (460) | **−0.013** | 20% |

**Untouched test (XGBoost, threshold 0.45):** 538 trades, **+0.017 R** per trade, win rate 50%, profit
factor 1.04, but the **95% lower bound is −0.050 R**.

➡️ **Gate result: NOT deployable.** Walk-forward expectancy is negative, and only 20% of folds were
profitable.

### What the models learned

The most important XGBoost features are **hour of day (18%)**, the **Asian (13%) and London (8%) session**
flags and the **candle range in ATRs (8%)**. The models learned *when* large moves happen (time and
volatility) much better than *which direction* they go. That explains why log-loss improves while trading
expectancy does not.

### Sensitivity analysis: decision threshold and exit rules

Using the saved out-of-sample predictions, 1,440 configurations were replayed: threshold × stop × target ×
holding time × volatility filter × session filter. Each configuration was **chosen on walk-forward data
(2022-03 → 2025-06) and checked on test data (2025-06 → 2026-09)**.

| Threshold | Walk-forward mean R | Test mean R | Test trades |
|----------:|------:|------:|------:|
| 0.35 | −0.089 | −0.103 | 13,815 |
| 0.40 | −0.061 | −0.083 | 3,177 |
| 0.45 | −0.013 | +0.017 | 538 |
| 0.50 | +0.109 | +0.006 | 102 |

*(SL 1 / TP 1 ATR / 30 min)*

- **The confidence threshold is the dominant factor.** Low thresholds generate many signals and lose
  steadily.
- **Small take-profits are the worst exit rule.** TP = 0.5 ATR raised the win rate to 60–75% but lost about
  −0.10 R per trade in both periods, because costs eat a larger share of each win.
- The most consistent configuration was **threshold 0.50, SL 1 ATR, TP 1.5 ATR, 1-hour hold**: +0.115 R
  (walk-forward, 321 trades) and +0.085 R (test, 101 trades). It produces only about 1–2 signals a week, and
  with ~100 test trades and 1,440 configurations tried, the result is **not statistically conclusive**.
  This is the live engine's current practice configuration.
- Session and volatility filters helped in one period and hurt in the other, so they were not adopted.

### Backtest with account rules (earlier 4-hour model, SL 1.5 / TP 3 ATR)

| Model | Walk-forward period (2022 → 2025-06) | Untouched test (2025-06 → 2026-09) |
|-------|--------------------------------------|------------------------------------|
| 15-minute | $100 → **$84.53** (−15%), 716 trades, max DD −36% | $100 → **$84.85** (−15%), 131 trades, max DD −19% |
| 1-hour (8 h hold) | $100 → **$73.58** (−26%), max DD −55% | $100 → **$52.37** (−48%) |

### Live forward test (paper trading, Sept–Oct 2026)

With a deliberately low practice threshold (0.35), the live engine produced **75 signals**. They were
scored automatically against what actually happened: **18 targets, 42 stops, 15 time exits, −24 R in total
(−0.32 R per signal)**. This agrees with the out-of-sample prediction for that threshold. A human trader
following the signals on a demo account (38 trades) won 66% of trades but lost money overall, because the
average loss was 2.3 × the average win. That is the same cost/asymmetry effect the sensitivity analysis
found.

### Conclusion

With publicly available 15-minute price data and standard technical features, the models **did not find an
edge large enough to beat transaction costs** for these six instruments. This is consistent with the weak
form of the efficient-market hypothesis at short horizons. The value of the project is the **methodology**:
leakage-free features, realistic labels and costs, strict chronological validation, an explicit
deployability gate, and a live forward test, which together keep the system from reporting an edge it does
not have.

---

## 🛠 Technologies

| Layer | Technology | Used for |
|-------|-----------|----------|
| Language | **Python 3.11+**, **TypeScript 5** | Backend / ML, frontend |
| Data | **pandas**, **NumPy**, **PyArrow / Parquet** | Time-series processing, columnar ML datasets |
| Machine learning | **scikit-learn** (Logistic Regression, Random Forest), **XGBoost**, **joblib** | Models, model persistence |
| API | **FastAPI**, **Uvicorn**, **Pydantic v2**, **pydantic-settings** | REST + WebSocket API, typed config from `.env` |
| Database | **SQLAlchemy 2.0**, **SQLite** (default), **PostgreSQL** via psycopg 3 (optional) | Raw candles, signals, trades |
| Market data | **Twelve Data** REST + WebSocket, **OANDA v20** (optional), **httpx** | Historical and live prices |
| Frontend | **Next.js 16** (App Router), **React 19**, **Tailwind CSS 4** | Dashboard |
| Charts | **TradingView Lightweight Charts** | Candles, EMAs, signal markers, SL/TP lines |
| Notifications | Web Notifications API, **Telegram Bot API** | Desktop and phone alerts |
| Testing / CI | **pytest** (282 tests), ESLint, `tsc`, **GitHub Actions** | Quality gates |
| Tooling | PowerShell / `.cmd` scripts | One-command setup on Windows |

---

## 🏗 System architecture

```mermaid
flowchart TB
    subgraph Provider[Market data]
        TD[Twelve Data REST]
        WS[Twelve Data WebSocket]
    end
    subgraph Backend[FastAPI backend]
        LIVE[Live engine<br/>candle loop · price stream]
        FEAT[Feature engineering]
        MODEL[ML model<br/>joblib]
        RISK[Risk rules &<br/>position sizing]
        COACH[Coach<br/>signals · trades · scoring]
        API[REST /api · WebSocket /api/ws]
        DB[(SQLite / PostgreSQL)]
    end
    subgraph Frontend[Next.js dashboard]
        LA[Live Assistant]
        MP[AI Model & Performance]
    end
    TG[Telegram]

    TD --> LIVE
    WS --> LIVE
    LIVE --> FEAT --> MODEL --> RISK --> COACH
    COACH <--> DB
    COACH --> API
    COACH --> TG
    API <--> LA
    API <--> MP
```

**Dashboard pages**

- **Live Assistant**: instrument selector, live candlestick chart with EMA 20/50/200 and SL/TP lines,
  current signal card with countdown, live probabilities for every pair, open trades and close advice, risk
  panel, track record.
- **AI Model & Performance**: model comparison, walk-forward folds, test results, feature importance,
  backtest equity curve and drawdown, data-validation reports.

---

## 📁 Project structure

```
forex-ai/
├── backend/
│   ├── app/
│   │   ├── api/            # FastAPI routes (system, market data, model, backtest, risk, coach) + schemas
│   │   ├── core/           # settings, instrument metadata (pips, units), market hours, logging
│   │   ├── data/           # provider clients, downloader, cleaning, validation, resampling, storage
│   │   ├── database/       # SQLAlchemy models, sessions, repositories
│   │   ├── features/       # indicators, sessions, feature engineering & store
│   │   ├── models/         # targets (labels), dataset & splits, training, evaluation, pipeline
│   │   ├── risk/           # position sizing
│   │   ├── signals/        # live decision engine
│   │   ├── trading/        # backtester, paper-trading coach
│   │   ├── live/           # live candle loop & price stream
│   │   ├── notify/         # Telegram notifications
│   │   ├── websocket/      # broadcast manager
│   │   └── main.py         # application factory
│   ├── training/           # CLI entry points: download, validate, features, targets, train, backtest…
│   ├── tests/              # 282 pytest tests
│   ├── data/               # (git-ignored) database, Parquet datasets, validation reports
│   └── models/             # (git-ignored) trained model versions + reports
├── frontend/
│   └── src/
│       ├── app/            # Next.js pages: / (Live Assistant), /model (AI Model & Performance)
│       ├── components/     # chart, signal card, panels, reports
│       └── lib/            # API client, live WebSocket state, formatting
├── scripts/                # Windows one-command scripts (setup, download, train, backtest, start, test…)
├── .github/workflows/      # CI: backend tests, frontend lint/type-check/build
├── .env.example            # every setting, documented
└── LICENSE
```

---

## 🚀 Getting started

### Prerequisites

- [Python 3.11+](https://www.python.org/downloads/)
- [Node.js 20+ LTS](https://nodejs.org/)
- A free [Twelve Data API key](https://twelvedata.com/) (sign up → *Dashboard → API Keys*)

### Windows (one-command scripts)

```powershell
git clone https://github.com/<your-username>/forex-ai.git
cd forex-ai
scripts\setup.cmd        # Python venv + packages, npm packages, creates .env from .env.example
notepad .env             # set TWELVEDATA_API_KEY=...
scripts\download.cmd     # download + clean + validate every instrument (~7 min per instrument on the free plan)
scripts\train.cmd        # train, compare, walk-forward, test and save a model (~5 min)
scripts\backtest.cmd     # backtest the current model's out-of-sample signals
scripts\start.cmd        # API on :8000 and dashboard on :3000
```

Open **http://localhost:3000**. The interactive API documentation is at **http://localhost:8000/docs**.

### macOS / Linux (manual)

```bash
cp .env.example .env                    # then set TWELVEDATA_API_KEY
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m training.download_data        # history + cleaning + validation
python -m training.train                # model training & evaluation
uvicorn app.main:app --port 8000        # API + live engine

cd ../frontend
npm install
npm run dev                             # http://localhost:3000
```

### All scripts

| Script | Purpose |
|--------|---------|
| `scripts\setup.cmd` | Create the virtual environment, install dependencies, create `.env` |
| `scripts\download.cmd [-i XAU_USD] [--full] [--check]` | Download, clean and validate history |
| `scripts\validate.cmd` | Re-run cleaning and validation on stored data |
| `scripts\features.cmd` | Feature summary per instrument |
| `scripts\targets.cmd` | Label statistics (the bar to beat) |
| `scripts\train.cmd` | Train, compare, walk-forward test, final test, save model |
| `scripts\evaluate.cmd` / `scripts\walkforward.cmd` | Print the current model's report / fold results |
| `scripts\backtest.cmd [--version V]` | Backtest out-of-sample signals with account rules |
| `scripts\resample.cmd [--to H1]` | Build 1-hour candles from 15-minute data |
| `scripts\telegram.cmd` | Link a Telegram bot for phone alerts |
| `scripts\start.cmd` | Start API + dashboard |
| `scripts\test.cmd` | Run the test suite |

---

## ⚙️ Configuration

All settings live in `.env` (see [`.env.example`](.env.example), where every variable is documented).
The main ones:

| Variable | Example | Meaning |
|----------|---------|---------|
| `DATA_PROVIDER` | `twelvedata` | `twelvedata` or `oanda` |
| `TWELVEDATA_API_KEY` | – | Free API key |
| `INSTRUMENTS` | `EUR_USD,GBP_USD,USD_JPY,AUD_USD,USD_CAD,XAU_USD` | Watchlist |
| `DATABASE_URL` | *(empty = SQLite)* | or `postgresql+psycopg://user:pass@localhost:5432/forex_ai` |
| `ACCOUNT_BALANCE` | `100` | Paper balance (USD) |
| `MAX_RISK_PERCENT` | `1` | Loss at the stop as % of balance; this sets the position size |
| `MAX_TRADE_ALLOCATION_PERCENT` | `25` | Maximum margin per trade (% of balance) |
| `MAX_OPEN_TRADES` | `3` | Concurrent trades (one per instrument) |
| `MAX_DAILY_LOSS_PERCENT` | `3` | Daily loss stop |
| `LEVERAGE_FOREX` / `LEVERAGE_METAL` | `30` / `20` | Regulated retail leverage |
| `STOP_LOSS_ATR_MULTIPLIER` | `1` | SL distance in ATRs |
| `TAKE_PROFIT_ATR_MULTIPLIER` | `1.5` | TP distance in ATRs |
| `MAX_HOLDING_CANDLES` | `4` | Maximum holding time (4 × 15 min) |
| `COACH_MODE` | `practice` | `proven` = signals only from a model that passed the gate |
| `PRACTICE_SIGNAL_THRESHOLD` | `0.50` | Minimum probability for a practice signal |
| `SIGNAL_EXPIRY_MINUTES` | `5` | How long a signal can still be taken |
| `SPREAD_PIPS_OVERRIDES` | `EUR_USD:0.8` | Override the modelled spread |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | – | Optional phone alerts |

**Position sizing** (`app/risk/position_sizing.py`): the largest whole number of units such that
`units × stop distance × pip value ≤ balance × MAX_RISK_PERCENT` **and** the margin stays under the
allocation cap. If even one unit breaks a limit, the answer is WAIT.

---

## 🔌 REST & WebSocket API

Base URL `http://localhost:8000/api`. Full OpenAPI docs are at `/docs`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health`, `/config` | Service status, effective settings |
| GET | `/instruments` | Watchlist with pip size, precision, asset class |
| GET | `/candles`, `/chart` | Candles; chart bundle with EMAs, signals and trades |
| GET | `/indicators` | Latest indicator values |
| GET / POST | `/data/summary`, `/data/validation` | Dataset summary; validation report (re-run with POST) |
| GET | `/model` | Current model report |
| GET | `/backtest` | Backtest summary for a model version and period |
| GET | `/risk/preview` | Position size for a hypothetical trade |
| GET | `/live/status` | Live engine status, last candles, API budget |
| GET | `/signals`, `/signals/current`, `/signals/latest` | Signal history and current calls |
| POST | `/signals/{id}/take`, `/signals/{id}/skip` | Confirm or skip a signal |
| GET | `/trades` | Open and closed paper trades |
| POST / DELETE | `/trades/{id}/close`, `/trades/{id}` | Close a trade / undo a mistaken entry |
| GET | `/coach/stats` | Track record of the model and of the user |
| WS | `/ws` | Push events: `signal`, `trade`, `price`, `status` |

---

## ✅ Testing

```powershell
scripts\test.cmd                 # or: cd backend && python -m pytest -q
```

**282 tests** cover: provider clients (mocked HTTP), resumable downloading, cleaning and validation rules,
market hours and DST, instrument pip maths, **look-ahead-free and scale-free features**, barrier labels,
the training pipeline, position sizing, the backtester, the coach, the API and Telegram notifications.
Tests run fully isolated (temporary database and model folder, no network).

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs the backend suite on Python 3.11 and 3.12,
plus frontend lint, type-check and production build, on every push and pull request.

---

## 🚧 Limitations

- **Mid prices only** on the free data plan: spreads are modelled, not observed, and real spreads widen
  around news and session opens.
- **Price-only features**: no order flow, volume, news, sentiment or macro data.
- **Multiple testing**: many thresholds and configurations were explored, and the test period has been
  looked at more than once. Small positive results should be treated as noise until confirmed on new data.
- **Short forward test**: weeks of live paper trading, not years.
- **Single granularity** for live use (M15). H1 was evaluated and rejected.
- The live engine runs only while the API process is running. Twelve Data's free plan limits real-time
  streaming to EUR/USD and gold.

## 🔭 Future work

- Bid/ask data (e.g. OANDA) for observed spreads, and execution-aware labels.
- Probability calibration analysis (reliability diagrams) and cost-sensitive learning.
- Sequence models (LSTM / Temporal Fusion Transformer) compared with gradient boosting under the same
  protocol.
- Regime detection (volatility / trend states) and meta-labelling.
- Additional information sources: economic calendar, cross-asset features, sentiment.
- A longer live forward test, then re-evaluation with the deployability gate.

---

## ⚠️ Disclaimer

This is an **academic project** for research and education. It runs in **paper-trading mode only** and
never places real orders. Signals are statistical model outputs, not financial advice, and the evaluation
above shows **no proven edge**. Trading leveraged products such as forex and CFDs carries a high risk of
losing money.

## 📜 License

Released under the [MIT License](LICENSE).

## 🙏 Acknowledgements

- [Twelve Data](https://twelvedata.com/) for the free market-data API
- [TradingView Lightweight Charts](https://github.com/tradingview/lightweight-charts)
- The open-source scientific Python stack: pandas, NumPy, scikit-learn, XGBoost, FastAPI
