#!/usr/bin/env python3
"""
低買高賣波段操盤 Agent - 多指標共振版 v2
結合：布林通道 + RSI + MACD + 成交量確認
"""

import os
import sys
import smtplib
import yfinance as yf
import numpy as np
import pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ==================== 設定區 ====================
HOLDINGS = {
    "LITE": {"market": "US", "name": "Lumentum", "type": "high_volatility"},
    "GOOG": {"market": "US", "name": "谷歌-C", "type": "stable"},
    "NVDA": {"market": "US", "name": "英偉達", "type": "high_volatility"},
    "MCD":  {"market": "US", "name": "麥當勞", "type": "stable"},
    "SPCX": {"market": "US", "name": "SpaceX", "type": "high_volatility"},
    "BE":   {"market": "US", "name": "Bloom Energy", "type": "high_volatility"},
    "BRK-B": {"market": "US", "name": "伯克希爾-B", "type": "stable"},
    "TSM":  {"market": "US", "name": "台積電", "type": "stable"},
    "PLTR": {"market": "US", "name": "Palantir", "type": "high_volatility"},
    "PANW": {"market": "US", "name": "Palo Alto Networks", "type": "stable"},
    "GLW":  {"market": "US", "name": "康寧", "type": "stable"},
    "MU": {"market": "US", "name": "美光科技", "type": "high_volatility"},
    "1919.HK": {"market": "HK", "name": "中遠海控", "type": "cyclical"},
    "1088.HK": {"market": "HK", "name": "中國神華", "type": "cyclical"},
    "0941.HK": {"market": "HK", "name": "中國移動", "type": "stable"},
    "0300.HK": {"market": "HK", "name": "美的集團", "type": "stable"},
}

EMAIL_SENDER = os.environ.get('EMAIL_SENDER', 'shirleyliu0118@gmail.com')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', '')
EMAIL_RECEIVER = os.environ.get('EMAIL_RECEIVER', 'shirleyliu0118@gmail.com')
EMAIL_SMTP_SERVER = "smtp.gmail.com"
EMAIL_SMTP_PORT = 587

STOP_LOSS_PCT = 0.05
VOLUME_THRESHOLD = 1.5

# 指標門檻
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 70
BB_POSITION_LOW = 0.10
BB_POSITION_HIGH = 0.90

# ==================== 資料抓取 ====================
def fetch_stock_data(ticker, period="1y"):
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period=period)
        if df.empty:
            print(f"   ⚠️ {ticker} 無資料回傳（可能代碼錯誤或未上市）")
            return None
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
        df.columns = ['open', 'high', 'low', 'close', 'volume']
        return df
    except Exception as e:
        print(f"❌ {ticker} 資料抓取失敗: {e}")
        return None

# ==================== 技術指標計算 ====================
def calculate_bollinger_bands(df, window=20, num_std=2):
    sma = df['close'].rolling(window=window).mean()
    std = df['close'].rolling(window=window).std()
    upper = sma + (std * num_std)
    lower = sma - (std * num_std)
    bb_position = (df['close'] - lower) / (upper - lower)
    return {
        'sma20': sma,
        'upper': upper,
        'lower': lower,
        'bb_position': bb_position,
        'bandwidth': (upper - lower) / sma
    }

def calculate_rsi(df, window=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_macd(df, fast=12, slow=26, signal=9):
    ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return {
        'macd': macd_line,
        'signal': signal_line,
        'histogram': histogram
    }

# ==================== 多指標共振分析 ====================
def analyze_multi_indicator(df):
    if df is None or len(df) < 60:
        return None
    
    bb = calculate_bollinger_bands(df)
    rsi = calculate_rsi(df)
    macd = calculate_macd(df)
    
    current = df['close'].iloc[-1]
    
    bb_pos = bb['bb_position'].iloc[-1]
    bb_lower = bb['lower'].iloc[-1]
    bb_upper = bb['upper'].iloc[-1]
    bb_sma = bb['sma20'].iloc[-1]
    rsi_val = rsi.iloc[-1]
    macd_val = macd['macd'].iloc[-1]
    signal_val = macd['signal'].iloc[-1]
    hist_val = macd['histogram'].iloc[-1]
    prev_hist = macd['histogram'].iloc[-2]
    
    # 買入共振條件
    buy_signals = []
    if bb_pos < BB_POSITION_LOW:
        buy_signals.append("觸及布林下軌")
    elif bb_pos < 0.20:
        buy_signals.append("接近布林下軌")
    if rsi_val < RSI_OVERSOLD:
        buy_signals.append(f"RSI超賣({rsi_val:.1f})")
    elif rsi_val < 40:
        buy_signals.append(f"RSI偏低({rsi_val:.1f})")
    if macd_val > signal_val and macd['macd'].iloc[-2] <= macd['signal'].iloc[-2]:
        buy_signals.append("MACD黃金交叉")
    elif hist_val > prev_hist and hist_val < 0:
        buy_signals.append("MACD柱狀翻正")
    if current < bb_sma * 0.95:
        buy_signals.append("低於均線5%")
    
    # 賣出共振條件
    sell_signals = []
    if bb_pos > BB_POSITION_HIGH:
        sell_signals.append("觸及布林上軌")
    elif bb_pos > 0.80:
        sell_signals.append("接近布林上軌")
    if rsi_val > RSI_OVERBOUGHT:
        sell_signals.append(f"RSI超買({rsi_val:.1f})")
    elif rsi_val > 65:
        sell_signals.append(f"RSI偏高({rsi_val:.1f})")
    if macd_val < signal_val and macd['macd'].iloc[-2] >= macd['signal'].iloc[-2]:
        sell_signals.append("MACD死亡交叉")
    elif hist_val < prev_hist and hist_val > 0:
        sell_signals.append("MACD柱狀翻負")
    if current > bb_sma * 1.05:
        sell_signals.append("高於均線5%")
    
    buy_strength = len(buy_signals)
    sell_strength = len(sell_signals)
    
    if buy_strength >= 3:
        stage = "strong_buy"
        stage_desc = "強烈買入信號"
    elif buy_strength >= 2:
        stage = "buy"
        stage_desc = "買入信號"
    elif buy_strength >= 1:
        stage = "weak_buy"
        stage_desc = "弱買入信號"
    elif sell_strength >= 3:
        stage = "strong_sell"
        stage_desc = "強烈賣出信號"
    elif sell_strength >= 2:
        stage = "sell"
        stage_desc = "賣出信號"
    elif sell_strength >= 1:
        stage = "weak_sell"
        stage_desc = "弱賣出信號"
    else:
        stage = "neutral"
        stage_desc = "中性觀望"
    
    mid = df.tail(90)
    support = np.percentile(mid['low'].values, 3)
    resistance = np.percentile(mid['high'].values, 97)
    
    return {
        'current': round(current, 2),
        'bb_lower': round(bb_lower, 2),
        'bb_upper': round(bb_upper, 2),
        'bb_sma': round(bb_sma, 2),
        'bb_position': round(bb_pos, 3),
        'rsi': round(rsi_val, 1),
        'macd': round(macd_val, 3),
        'macd_signal': round(signal_val, 3),
        'macd_histogram': round(hist_val, 3),
        'support': round(support, 2),
        'resistance': round(resistance, 2),
        'buy_signals': buy_signals,
        'sell_signals': sell_signals,
        'buy_strength': buy_strength,
        'sell_strength': sell_strength,
        'stage': stage,
        'stage_desc': stage_desc,
    }

# ==================== 真實 ADR ====================
def fetch_nyse_advances_declines():
    try:
        indices = {'NYSE': '^NYA', 'NASDAQ': '^IXIC', 'S&P500': '^GSPC', 'DOW': '^DJI', 'RUSSELL': '^RUT'}
        advances = 0
        declines = 0
        total = 0
        for name, ticker in indices.items():
            try:
                idx = yf.Ticker(ticker)
                df = idx.history(period="5d")
                if len(df) >= 2:
                    today = df['Close'].iloc[-1]
                    yesterday = df['Close'].iloc[-2]
                    total += 1
                    if today > yesterday:
                        advances += 1
                    elif today < yesterday:
                        declines += 1
            except:
                continue
        if declines == 0 or total == 0:
            return 1.0
        return advances / declines
    except:
        return 1.0

def get_adr_status(adr_value):
    if adr_value >= 1.5:
        return {"emoji": "🔥", "description": "極度過熱", "action": "準備獲利了結"}
    elif adr_value >= 1.2:
        return {"emoji": "🌡️", "description": "買過頭", "action": "考慮減碼"}
    elif adr_value <= 0.6:
        return {"emoji": "❄️", "description": "極度超賣", "action": "觀察買進機會"}
    elif adr_value <= 0.8:
        return {"emoji": "🧊", "description": "賣過頭", "action": "可考慮買進"}
    else:
        return {"emoji": "⚖️", "description": "中性", "action": "正常操作"}

# ==================== 止損機制 ====================
def check_stop_loss(current_price, support_line, stop_loss_pct=STOP_LOSS_PCT):
    stop_price = support_line * (1 - stop_loss_pct)
    if current_price < stop_price:
        return {
            'triggered': True,
            'stop_price': round(stop_price, 2),
            'loss_pct': round((current_price / support_line - 1) * 100, 2)
        }
    return {'triggered': False}

# ==================== 成交量確認 ====================
def check_volume_confirmation(df, lookback=20):
    if df is None or len(df) < lookback + 5:
        return False, 0.0
    recent_volume = df['volume'].iloc[-5:].mean()
    avg_volume = df['volume'].iloc[-lookback:-5].mean()
    if avg_volume == 0:
        return False, 0.0
    volume_ratio = recent_volume / avg_volume
    return volume_ratio > VOLUME_THRESHOLD, round(volume_ratio, 2)

# ==================== 回測功能 ====================
def backtest_strategy(ticker, info, period="2y"):
    print(f"\n📈 回測: {ticker} ({info.get('name', '')}) - 過去 {period}")
    print("-" * 40)
    df = fetch_stock_data(ticker, period=period)
    if df is None or len(df) < 200:
        print("   ❌ 資料不足")
        return None
    signals = []
    for i in range(60, len(df) - 30, 5):
        window = df.iloc[:i]
        current = df['close'].iloc[i]
        bb = calculate_bollinger_bands(window)
        rsi = calculate_rsi(window)
        macd = calculate_macd(window)
        bb_pos = bb['bb_position'].iloc[-1]
        rsi_val = rsi.iloc[-1]
        macd_val = macd['macd'].iloc[-1]
        signal_val = macd['signal'].iloc[-1]
        buy_count = 0
        if bb_pos < 0.20: buy_count += 1
        if rsi_val < 40: buy_count += 1
        if macd_val > signal_val and macd['macd'].iloc[-2] <= macd['signal'].iloc[-2]: buy_count += 1
        sell_count = 0
        if bb_pos > 0.80: sell_count += 1
        if rsi_val > 65: sell_count += 1
        if macd_val < signal_val and macd['macd'].iloc[-2] >= macd['signal'].iloc[-2]: sell_count += 1
        future_idx = min(i + 30, len(df) - 1)
        future_price = df['close'].iloc[future_idx]
        ret = (future_price - current) / current * 100
        if buy_count >= 2:
            signals.append({'type': 'buy', 'return': round(ret, 2)})
        elif sell_count >= 2:
            signals.append({'type': 'sell', 'return': round(ret, 2)})
    if not signals:
        print("   ⚠️ 無明確交易信號")
        return None
    returns = [s['return'] for s in signals]
    buy_signals = [s for s in signals if s['type'] == 'buy']
    sell_signals = [s for s in signals if s['type'] == 'sell']
    result = {
        'ticker': ticker,
        'name': info.get('name', ticker),
        'total_signals': len(signals),
        'buy_signals': len(buy_signals),
        'sell_signals': len(sell_signals),
        'win_rate': round(sum(1 for r in returns if r > 0) / len(returns) * 100, 1),
        'avg_return': round(np.mean(returns), 2),
        'buy_avg': round(np.mean([s['return'] for s in buy_signals]), 2) if buy_signals else 0,
        'sell_avg': round(np.mean([s['return'] for s in sell_signals]), 2) if sell_signals else 0,
    }
    print(f"   總信號: {result['total_signals']} (買{result['buy_signals']}/賣{result['sell_signals']})")
    print(f"   勝率: {result['win_rate']}%")
    print(f"   平均報酬: {result['avg_return']}%")
    return result

# ==================== 郵件通知 ====================
def send_email(subject, body):
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        print("⚠️ 郵件設定不完整")
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = EMAIL_RECEIVER
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        server = smtplib.SMTP(EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        server.quit()
        print("✅ 郵件發送成功")
        return True
    except Exception as e:
        print(f"❌ 郵件發送失敗: {e}")
        return False

def format_daily_report(results, adr_info=None):
    now = datetime.now().strftime("%Y/%m/%d %H:%M")
    lines = [f"📊 波段管家日報（多指標共振版）{now}", "=" * 50]
    if adr_info:
        lines.append(f"🌡️ 市場情緒 (真實 ADR): {adr_info['emoji']} {adr_info['adr']:.2f}")
        lines.append(f"   {adr_info['description']}")
        lines.append(f"   💡 {adr_info['action']}")
    
    # 止損提醒
    stop_loss = [r for r in results if r.get('stop_loss_alert')]
    if stop_loss:
        lines.append("\n🚨【止損提醒 - 立即行動】")
        for r in stop_loss:
            lines.append(f"   {r['ticker']} ({r['name']})")
            lines.append(f"   現價: ${r['current']:.2f} | 止損價: ${r['stop_price']}")
            lines.append(f"   已跌破中期支撐 5%，建議立即止損！")
    
    # 強烈買入
    strong_buy = [r for r in results if r['stage'] == 'strong_buy']
    if strong_buy:
        lines.append("\n🟢🟢【強烈買入 - 多指標共振】")
        for r in strong_buy:
            lines.append(f"   {r['ticker']} ({r['name']})")
            lines.append(f"   現價: ${r['current']:.2f}")
            lines.append(f"   共振信號: {' + '.join(r['buy_signals'])}")
            lines.append(f"   RSI: {r['rsi']} | 布林位置: {r['bb_position']*100:.1f}%")
    
    # 買入信號
    buy = [r for r in results if r['stage'] == 'buy']
    if buy:
        lines.append("\n🟢【買入信號】")
        for r in buy:
            lines.append(f"   {r['ticker']} ({r['name']})")
            lines.append(f"   現價: ${r['current']:.2f}")
            lines.append(f"   信號: {' + '.join(r['buy_signals'])}")
    
    # 強烈賣出
    strong_sell = [r for r in results if r['stage'] == 'strong_sell']
    if strong_sell:
        lines.append("\n🔴🔴【強烈賣出 - 多指標共振】")
        for r in strong_sell:
            lines.append(f"   {r['ticker']} ({r['name']})")
            lines.append(f"   現價: ${r['current']:.2f}")
            lines.append(f"   共振信號: {' + '.join(r['sell_signals'])}")
            lines.append(f"   RSI: {r['rsi']} | 布林位置: {r['bb_position']*100:.1f}%")
    
    # 賣出信號
    sell = [r for r in results if r['stage'] == 'sell']
    if sell:
        lines.append("\n🔴【賣出信號】")
        for r in sell:
            lines.append(f"   {r['ticker']} ({r['name']})")
            lines.append(f"   現價: ${r['current']:.2f}")
            lines.append(f"   信號: {' + '.join(r['sell_signals'])}")
    
    # 其他持倉
    others = [r for r in results if r['stage'] in ['weak_buy', 'weak_sell', 'neutral']]
    if others:
        lines.append("\n📊 其他持倉:")
        lines.append("-" * 50)
        for r in others:
            lines.append(f"\n{r['stage_emoji']} {r['ticker']} ({r['name']})")
            lines.append(f"   現價: ${r['current']:.2f}")
            lines.append(f"   📊 技術指標:")
            lines.append(f"      RSI: {r['rsi']} (30超賣/70超買)")
            lines.append(f"      布林: 下軌${r['bb_lower']:.2f} | 上軌${r['bb_upper']:.2f}")
            lines.append(f"      位置: {r['bb_position']*100:.1f}% (0=下軌, 100=上軌)")
            lines.append(f"      MACD: {r['macd_histogram']:.3f}")
            if r['buy_signals']:
                lines.append(f"   🟢 買入條件滿足: {', '.join(r['buy_signals'])}")
            if r['sell_signals']:
                lines.append(f"   🔴 賣出條件滿足: {', '.join(r['sell_signals'])}")
            if 'volume_ratio' in r:
                if r.get('volume_confirmed'):
                    lines.append(f"   ✅ 成交量: {r['volume_ratio']}倍放量")
                else:
                    lines.append(f"   📊 成交量: {r['volume_ratio']}倍")
            if r['stage'] == 'weak_buy':
                lines.append(f"   ⏳ 建議: 弱買入信號，可觀察等待更強信號")
            elif r['stage'] == 'weak_sell':
                lines.append(f"   ⏳ 建議: 弱賣出信號，可觀察等待更強信號")
            else:
                lines.append(f"   ⏳ 建議: 中性觀望，等待指標共振")
    
    lines.append("\n" + "=" * 50)
    lines.append("💡 心法: 不焦急、不貪心，等待多指標共振")
    lines.append("📚 來源: 布林通道 + RSI + MACD 多指標共振系統")
    lines.append("🔧 布林通道 | RSI | MACD | 真實 ADR | 止損 | 成交量確認")
    return "\n".join(lines)

def format_backtest_report(backtest_results):
    now = datetime.now().strftime("%Y/%m/%d")
    lines = [f"📊 波段管家 - 回測報告 {now}", "=" * 40]
    total_wins = 0
    total_trades = 0
    for result in backtest_results:
        if result is None:
            continue
        lines.append(f"\n📈 {result['ticker']} ({result['name']})")
        lines.append(f"   總信號: {result['total_signals']} (買{result['buy_signals']}/賣{result['sell_signals']})")
        lines.append(f"   勝率: {result['win_rate']}%")
        lines.append(f"   平均報酬: {result['avg_return']}%")
        lines.append(f"   買入平均: {result['buy_avg']}% | 賣出平均: {result['sell_avg']}%")
        total_wins += int(result['win_rate'] * result['total_signals'] / 100)
        total_trades += result['total_signals']
    if total_trades > 0:
        overall_win_rate = total_wins / total_trades * 100
        lines.append(f"\n{'=' * 40}")
        lines.append(f"📊 綜合勝率: {overall_win_rate:.1f}% ({total_wins}/{total_trades})")
    lines.append(f"\n💡 回測僅供參考，過去績效不代表未來結果")
    return "\n".join(lines)

# ==================== 主程式 ====================
def get_stage_emoji(stage):
    return {
        "strong_buy": "🟢🟢",
        "buy": "🟢",
        "weak_buy": "🟡🟢",
        "neutral": "⚪",
        "weak_sell": "🟡🔴",
        "sell": "🔴",
        "strong_sell": "🔴🔴"
    }.get(stage, "⚪")

def analyze_single_stock(ticker, info):
    print(f"\n📊 分析: {ticker} ({info.get('name', '')})")
    df = fetch_stock_data(ticker, period="1y")
    if df is None:
        print(f"   ❌ {ticker} 無法取得資料，跳過")
        return None
    
    result = analyze_multi_indicator(df)
    if result is None:
        print(f"   ❌ {ticker} 指標計算失敗，跳過")
        return None
    
    result['ticker'] = ticker
    result['name'] = info.get('name', ticker)
    result['stage_emoji'] = get_stage_emoji(result['stage'])
    
    # 止損檢查
    stop_check = check_stop_loss(result['current'], result['support'])
    if stop_check['triggered']:
        result['stop_loss_alert'] = True
        result['stop_price'] = stop_check['stop_price']
        print(f"   🚨 止損提醒：跌破中期支撐 5%！止損價 ${stop_check['stop_price']}")
    else:
        result['stop_loss_alert'] = False
    
    # 成交量確認
    vol_confirmed, vol_ratio = check_volume_confirmation(df)
    result['volume_confirmed'] = vol_confirmed
    result['volume_ratio'] = vol_ratio
    
    print(f"   現價: ${result['current']:.2f}")
    print(f"   📊 指標: RSI:{result['rsi']} | 布林:{result['bb_position']*100:.1f}% | MACD:{result['macd_histogram']:.3f}")
    if result['buy_signals']:
        print(f"   🟢 買入: {' + '.join(result['buy_signals'])}")
    if result['sell_signals']:
        print(f"   🔴 賣出: {' + '.join(result['sell_signals'])}")
    print(f"   狀態: {result['stage_emoji']} {result['stage_desc']}")
    
    return result

def run_daily_check():
    print("=" * 60)
    print("📊 低買高賣波段管家（多指標共振版）")
    print(f"🕐 {datetime.now().strftime('%Y/%m/%d %H:%M')}")
    print("=" * 60)
    
    results = []
    failed_tickers = []
    
    for ticker, info in HOLDINGS.items():
        result = analyze_single_stock(ticker, info)
        if result:
            results.append(result)
        else:
            failed_tickers.append(ticker)
    
    if failed_tickers:
        print(f"\n⚠️ 以下股票無法取得資料: {', '.join(failed_tickers)}")
        print("   可能原因: 代碼錯誤、未上市、或資料源問題")
    
    if not results:
        print("❌ 所有股票分析失敗")
        return
    
    adr_value = fetch_nyse_advances_declines()
    adr_status = get_adr_status(adr_value)
    adr_info = {'adr': adr_value, **adr_status}
    
    print(f"\n🌡️ 市場情緒 (真實 ADR): {adr_info['emoji']} {adr_value:.2f}")
    print(f"   {adr_info['description']} - {adr_info['action']}")
    
    print(f"\n{'=' * 60}")
    print("📋 今日摘要")
    print(f"{'=' * 60}")
    
    strong_buy = [r for r in results if r['stage'] == 'strong_buy']
    buy = [r for r in results if r['stage'] == 'buy']
    strong_sell = [r for r in results if r['stage'] == 'strong_sell']
    sell = [r for r in results if r['stage'] == 'sell']
    stop_loss = [r for r in results if r.get('stop_loss_alert')]
    
    if strong_buy:
        print(f"\n🟢🟢 強烈買入 ({len(strong_buy)} 檔): {', '.join(r['ticker'] for r in strong_buy)}")
    if buy:
        print(f"\n🟢 買入信號 ({len(buy)} 檔): {', '.join(r['ticker'] for r in buy)}")
    if strong_sell:
        print(f"\n🔴🔴 強烈賣出 ({len(strong_sell)} 檔): {', '.join(r['ticker'] for r in strong_sell)}")
    if sell:
        print(f"\n🔴 賣出信號 ({len(sell)} 檔): {', '.join(r['ticker'] for r in sell)}")
    if stop_loss:
        print(f"\n🚨 止損提醒 ({len(stop_loss)} 檔): {', '.join(r['ticker'] for r in stop_loss)}")
    
    print(f"\n💡 心法: 不焦急、不貪心，等待多指標共振")
    print(f"{'=' * 60}")
    
    report = format_daily_report(results, adr_info)
    subject = f"📊 波段管家日報 {datetime.now().strftime('%Y/%m/%d %H:%M')}"
    send_email(subject, report)

def run_backtest():
    print("=" * 60)
    print("📊 波段管家 - 回測模式")
    print(f"🕐 {datetime.now().strftime('%Y/%m/%d %H:%M')}")
    print("=" * 60)
    
    backtest_results = []
    for ticker, info in HOLDINGS.items():
        result = backtest_strategy(ticker, info, period="2y")
        if result:
            backtest_results.append(result)
    
    if backtest_results:
        report = format_backtest_report(backtest_results)
        subject = f"📊 波段管家 - 回測報告 {datetime.now().strftime('%Y/%m/%d')}"
        send_email(subject, report)

if __name__ == "__main__":
    if '--backtest' in sys.argv:
        run_backtest()
    else:
        run_daily_check()
