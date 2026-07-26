# Research Knowledge Base — Extracted from Academic Papers, Books & Blogs

## 1. Crypto TSMOM (Time-Series Momentum)
**Source:** Huang, Sangiorgi, Urquhart (2024) - SSRN; Yang (2025) - Finance Research Letters
**Findings:**
- Volume-weighted TSMOM generates 0.94% per day with Sharpe 2.17
- Volatility management is critical for crypto momentum (crashes can be -255%)
- Risk-managed strategies increase weekly returns by 200%+ vs plain strategy
- 4-week rolling vol window: 2.40% per week, 8-week window: 1.86% per week
- Top 30 market-cap coins recommended for liquidity

## 2. Adaptive Trend Following with Ensemble Donchian Channels
**Source:** SSRN 5209907 - "Catching Crypto Trends" (2025)
**Findings:**
- Ensemble of Donchian channel trend models with different lookbacks
- Volatility-based position sizing
- Rotational portfolio of top 20 liquid coins
- Sharpe > 1.5, annualized alpha 10.8% vs Bitcoin
- Net-of-fees returns positive with proper cost management

## 3. Machine Learning Statistical Arbitrage
**Source:** MDPI Journal of Risk and Financial Management; Frontiers in Applied Mathematics
**Findings:**
- Random Forest on lagged returns of 40 coins: 7.1 bps/day after transaction costs
- Deep Learning pairs trading with dynamic cointegration: MSE 0.012
- Dynamic cointegration + LSTM ensemble generates timely buy/sell decisions
- Key: execution delay kills alpha (drops 20.5bps -> 3.8bps with 1 min delay)
- Short-term mean reversion over 60 min windows is most predictive

## 4. CTREND Factor (Aggregate Price + Volume Signal)
**Source:** Journal of Financial and Quantitative Analysis (2025)
**Findings:**
- Aggregates price and volume information across multiple time horizons
- Machine learning on 3000+ coins
- Predicts returns reliably across subperiods and market states
- Survives transaction costs
- Outperforms competing factor models

## 5. Momentum and Network Design (PoW vs PoS)
**Source:** Lindroos & Meijanen - Aalto University Thesis
**Findings:**
- Strong short-term momentum (1-4 week formation periods)
- PoW coins: stronger momentum, longer reversals
- PoS coins: weaker momentum, faster mean reversion
- 3% per week zero-cost long-short momentum strategy
- Momentum fades quickly after 4 weeks

## 6. LLM-Based Alpha Discovery
**Source:** EMNLP 2025 - "Automate Strategy Finding with LLM in Quant Investment"
**Findings:**
- Three-stage framework: alpha mining -> multi-agent evaluation -> dynamic weight optimization
- 53.17% cumulative return on SSE50 (Jan 2023-Jan 2024)
- Multi-agent architecture with Confidence Score Agent + Risk Preference Agent
- Combines momentum, volume, RSI, MACD, ATR, Bollinger Bands

## 7. Deep Reinforcement Learning for Portfolio Optimization
**Source:** Scientific Reports 2025; NeurIPS 2025
**Findings:**
- Graph attention + heterogeneous multi-agent DRL: 16.8% annual returns, Sharpe 1.34, max DD 8.2%
- Multi-agent: risk assessment agent + return prediction agent + market perception agent
- OPHR framework for volatility trading: RL for options, outperforms all baselines on BTC/ETH

## 8. Risk Management Essentials
**Source:** Barroso & Santa-Clara (2015); Moreira & Muir (2017); Multiple Papers
**Findings:**
- Volatility scaling reduces crash risk dramatically
- Trailing stops at 15% protect against tail events
- Portfolio DD > 10% -> reduce exposure by 50%
- Cash-only regime when no clear signals
- Transaction costs in crypto: 0.1% commission + 0.05% slippage minimum
- Capacity constraints: 5% participation rate, ~$2100/min per strategy

## 9. Key Parameters from Research
- TSMOM lookbacks: Fast 7-15d, Slow 28-120d
- T-stat thresholds: Enter > 2.0, Exit < 1.0 (for momentum)
- Yang-Zhang vol estimation window: 14-20 periods
- Annual vol target per asset: 30-50%
- Portfolio vol target: 20-35%
- Max leverage: 1.0-1.5x
- Max position: 15-25% per asset
- Rebalance frequency: weekly for momentum, intraday for stat arb
