#!/usr/bin/env python3
"""
低買高賣波段操盤 Agent - 中期支撐線版
根據上岡正明《日本最強散戶贏家教你低買高賣的波段操盤術》
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
    "BRK.B": {"market": "US", "name": "伯克希爾-B", "type": "stable"},
    "TSM":  {"market": "US", "name": "台積電", "type": "stable"},
    "PLTR": {"market": "US", "name": "Palantir", "type": "high_volatility"},
    "PANW": {"market": "US", "name": "Palo Alto Networks", "type": "stable"},
    "GLW":  {"market": "US", "name": "康寧", "type": "stable"},
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

# 門檻設定
LOW_BUY_THRESHOLD = 0.15      # 15% 以下為低買區（更嚴格）
HIGH_SELL_THRESHOLD = 0.80    # 80% 以上為高賣區
NEAR_HIGH_ALERT = 0.70        # 70% 以上提醒接近高賣區

# ==================== 資料抓取 ====================
def fetch_stock_data(ticker, period="1y"):
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period=period)
        if df.empty:
            return None
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
        df.columns = ['open', 'high', 'low', 'close', 'volume']
        return df
    except Exception as e:
        print(f"❌ {ticker} 資料抓取失敗: {e}")
        return None

# ==================== 箱型分析（強制中期支撐線）====================
def analyze_box_pattern(df):
    """
    使用中期（90天）支撐/壓力線
    更保守，低買區價格更低
    """
    if df is None or len(df) < 90:
        return None
    
    current = df['close'].iloc[-1]
    
    # 中期（90天）- 主要分析框架
    mid = df.tail(90)
    support = np.percentile(mid['low'].values, 3)
    resistance = np.percentile(mid['high'].values, 97)
    
    # 長期（180天）- 僅供參考
    long_period = min(180, len(df))
    long = df.tail(long_period)
    long_support = np.percentile(long['low'].values, 3)
    long_resistance = np.percentile(long['high'].values, 97)
    
    # 均線 - 僅供參考
    ma20 = df['close'].rolling(20).mean().iloc[-1]
    ma60 = df['close'].rolling(60).mean().iloc[-1]
    
    # 計算在箱型中的位置
    box_range = resistance - support
    if box_range <= 0:
        box_range = current * 0.1
    
    position = (current - support) / box_range
    position = max(0, min(1, position))
    
    # 計算距離支撐/壓力的百分比
    distance_to_support = (current - support) / support * 100
    distance_to_resistance = (resistance - current) / resistance * 100
    
    return {
        'current': round(current, 2),
        'support': round(support, 2),
        'resistance': round(resistance, 2),
        'long_support': round(long_support, 2),
        'long_resistance': round(long_resistance, 2),
        'ma20': round(ma20, 2),
        'ma60': round(ma60, 2),
        'position': round(position, 3),
        'distance_to_support': round(distance_to_support, 1),
        'distance_to_resistance': round(distance_to_resistance, 1),
    }

def get_stage(box_result):
    """判斷階段"""
    position = box_result['position']
    current = box_result['current']
    support = box_result['support']
    resistance = box_result['resistance']
    
    # 止損檢查
    if current < support * 0.95:
        return "breakdown", "跌破支撐"
    
    # 突破檢查
    if current > resistance * 1.03:
        return "breakup", "突破壓力線"
    
    # 位置判斷
    if position < LOW_BUY_THRESHOLD:
        return "low_buy", "低買區"
    elif position > HIGH_SELL_THRESHOLD:
        return "high_sell", "高賣區"
    elif position > NEAR_HIGH_ALERT:
        return "near_high", "接近高賣區"
    else:
        return "watch", "觀望區"

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
def backtest_box_strategy(ticker, info, period="2y"):
    print(f"\n📈 回測: {ticker} ({info.get('name', '')}) - 過去 {period}")
    print("-" * 40)
    
    df = fetch_stock_data(ticker, period=period)
    if df is None or len(df) < 200:
        print("   ❌ 資料不足")
        return None
    
    signals = []
    
    for i in range(90, len(df) - 30, 5):
        window = df.iloc[i-90:i]
        current = df['close'].iloc[i]
        
        support = np.percentile(window['low'].values, 3)
        resistance = np.percentile(window['high'].values, 97)
        
        box_range = resistance - support
        if box_range <= 0:
            continue
        
        position = (current - support) / box_range
        
        # 買進信號
        if position < LOW_BUY_THRESHOLD:
            future_idx = min(i + 30, len(df) - 1)
            future_price = df['close'].iloc[future_idx]
            ret = (future_price - current) / current * 100
            
            signals.append({
                'type': 'buy',
                'entry_price': round(current, 2),
                'exit_price': round(future_price, 2),
                'return': round(ret, 2)
            })
        
        # 賣出信號
        elif position > HIGH_SELL_THRESHOLD:
            future_idx = min(i + 30, len(df) - 1)
            future_price = df['close'].iloc[future_idx]
            ret = (future_price - current) / current * 100
            
            signals.append({
                'type': 'sell',
                'entry_price': round(current, 2),
                'exit_price': round(future_price, 2),
                'return': round(ret, 2)
            })
    
    if not signals:
        print("   ⚠️ 無明確交易信號")
        return None
    
    returns = [s['return'] for s in signals]
    buy_signals = [s for s in signals if s['type'] == 'buy']
    sell_signals = [s for s in signals if s['type'] == 'sell']
    
    buy_returns = [s['return'] for s in buy_signals]
    sell_returns = [s['return'] for s in sell_signals]
    
    result = {
        'ticker': ticker,
        'name': info.get('name', ticker),
        'total_signals': len(signals),
        'buy_signals': len(buy_signals),
        'sell_signals': len(sell_signals),
        'win_rate': round(sum(1 for r in returns if r > 0) / len(returns) * 100, 1) if returns else 0,
        'avg_return': round(np.mean(returns), 2) if returns else 0,
        'buy_avg_return': round(np.mean(buy_returns), 2) if buy_returns else 0,
        'sell_avg_return': round(np.mean(sell_returns), 2) if sell_returns else 0,
    }
    
    print(f"   總信號: {result['total_signals']} (買{result['buy_signals']}/賣{result['sell_signals']})")
    print(f"   勝率: {result['win_rate']}%")
    print(f"   平均報酬: {result['avg_return']}%")
    print(f"   買入平均: {result['buy_avg_return']}%")
    print(f"   賣出平均: {result['sell_avg_return']}%")
    
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
    lines = [f"📊 波段管家日報（中期支撐線版）{now}", "=" * 45]
    
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
    
    # 高賣區
    high_sell = [r for r in results if r['stage'] == 'high_sell']
    if high_sell:
        lines.append("\n🔴【高賣區 - 考慮獲利了結】")
        for r in high_sell:
            lines.append(f"   {r['ticker']} ({r['name']})")
            lines.append(f"   現價: ${r['current']:.2f} | 壓力線: ${r['resistance']:.2f}")
            lines.append(f"   位置: {r['position']*100:.1f}% | 距離壓力: {r['distance_to_resistance']}%")
    
    # 接近高賣區
    near_high = [r for r in results if r['stage'] == 'near_high']
    if near_high:
        lines.append("\n🟠【接近高賣區 - 準備減碼】")
        for r in near_high:
            lines.append(f"   {r['ticker']} ({r['name']})")
            lines.append(f"   現價: ${r['current']:.2f} | 壓力線: ${r['resistance']:.2f}")
            lines.append(f"   位置: {r['position']*100:.1f}% | 再漲{r['distance_to_resistance']}% 到壓力線")
    
    # 低買區
    low_buy = [r for r in results if r['stage'] == 'low_buy']
    if low_buy:
        lines.append("\n🟢【低買區 - 考慮買進】")
        for r in low_buy:
            lines.append(f"   {r['ticker']} ({r['name']})")
            lines.append(f"   現價: ${r['current']:.2f} | 中期支撐: ${r['support']:.2f}")
            lines.append(f"   位置: {r['position']*100:.1f}% | 距離支撐: +{r['distance_to_support']}%")
    
    # 其他個股
    others = [r for r in results if r['stage'] not in ['high_sell', 'near_high', 'low_buy']]
    if others:
        lines.append("\n📊 其他持倉:")
        lines.append("-" * 45)
        for r in others:
            lines.append(f"\n{r['stage_emoji']} {r['ticker']} ({r['name']})")
            lines.append(f"   現價: ${r['current']:.2f}")
            lines.append(f"   📊 中期箱型:")
            lines.append(f"      支撐: ${r['support']:.2f}")
            lines.append(f"      壓力: ${r['resistance']:.2f}")
            lines.append(f"      長期支撐: ${r['long_support']:.2f}")
            lines.append(f"      MA20: ${r['ma20']:.2f} | MA60: ${r['ma60']:.2f}")
            lines.append(f"   位置: {r['position']*100:.1f}% | 狀態: {r['stage_desc']}")
            
            if 'volume_ratio' in r:
                if r.get('volume_confirmed'):
                    lines.append(f"   ✅ 成交量: {r['volume_ratio']}倍放量")
                else:
                    lines.append(f"   📊 成交量: {r['volume_ratio']}倍")
            
            if r['stage'] == 'breakup' and r.get('volume_confirmed'):
                lines.append(f"   📈 建議: 放量突破，順勢操作")
            elif r['stage'] == 'breakup':
                lines.append(f"   ⚠️ 建議: 突破但成交量不足，觀望確認")
            elif r['stage'] == 'breakdown':
                lines.append(f"   📉 建議: 跌破箱型，注意風險")
            else:
                lines.append(f"   ⏳ 建議: 觀望，等待觸及關鍵價位")
    
    lines.append("\n" + "=" * 45)
    lines.append("💡 心法: 不焦急、不貪心，等待股價來到購買區")
    lines.append("📚 來源: 上岡正明《低買高賣的波段操盤術》")
    lines.append("🔧 中期支撐線 | 真實 ADR | 回測 | 止損 | 成交量確認")
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
        lines.append(f"   買入平均: {result['buy_avg_return']}% | 賣出平均: {result['sell_avg_return']}%")
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
        "low_buy": "🟢", 
        "high_sell": "🔴", 
        "near_high": "🟠",
        "watch": "🟡",
        "breakup": "📈", 
        "breakdown": "📉"
    }.get(stage, "⚪")

def analyze_single_stock(ticker, info):
    print(f"\n📊 分析: {ticker} ({info.get('name', '')})")
    df = fetch_stock_data(ticker, period="1y")
    if df is None:
        print("   ❌ 無法取得資料")
        return None
    
    box = analyze_box_pattern(df)
    if box is None:
        return None
    
    stage, stage_desc = get_stage(box)
    
    result = {
        'ticker': ticker,
        'name': info.get('name', ticker),
        **box,
        'stage': stage,
        'stage_emoji': get_stage_emoji(stage),
        'stage_desc': stage_desc,
    }
    
    # 止損檢查（基於中期支撐）
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
    print(f"   📊 中期箱型:")
    print(f"      支撐: ${result['support']:.2f}")
    print(f"      壓力: ${result['resistance']:.2f}")
    print(f"      長期支撐: ${result['long_support']:.2f}")
    print(f"      MA20: ${result['ma20']:.2f}")
    print(f"   位置: {result['position']*100:.1f}% | 狀態: {result['stage_emoji']} {result['stage_desc']}")
    
    return result

def run_daily_check():
    print("=" * 60)
    print("📊 低買高賣波段管家（中期支撐線版）")
    print(f"🕐 {datetime.now().strftime('%Y/%m/%d %H:%M')}")
    print("=" * 60)
    
    results = []
    
    for ticker, info in HOLDINGS.items():
        result = analyze_single_stock(ticker, info)
        if result:
            results.append(result)
    
    if not results:
        print("❌ 分析失敗")
        return
    
    adr_value = fetch_nyse_advances_declines()
    adr_status = get_adr_status(adr_value)
    adr_info = {'adr': adr_value, **adr_status}
    
    print(f"\n🌡️ 市場情緒 (真實 ADR): {adr_info['emoji']} {adr_value:.2f}")
    print(f"   {adr_info['description']} - {adr_info['action']}")
    
    print(f"\n{'=' * 60}")
    print("📋 今日摘要")
    print(f"{'=' * 60}")
    
    low_buy = [r for r in results if r['stage'] == 'low_buy']
    near_high = [r for r in results if r['stage'] == 'near_high']
    high_sell = [r for r in results if r['stage'] == 'high_sell']
    stop_loss = [r for r in results if r.get('stop_loss_alert')]
    breakout = [r for r in results if r['stage'] in ['breakup', 'breakdown']]
    
    if low_buy:
        print(f"\n🟢 低買區 ({len(low_buy)} 檔):")
        for r in low_buy:
            print(f"   {r['ticker']}: ${r['current']:.2f} (中期支撐 ${r['support']:.2f})")
    
    if near_high:
        print(f"\n🟠 接近高賣區 ({len(near_high)} 檔):")
        for r in near_high:
            print(f"   {r['ticker']}: ${r['current']:.2f} (壓力 ${r['resistance']:.2f})")
    
    if high_sell:
        print(f"\n🔴 高賣區 ({len(high_sell)} 檔):")
        for r in high_sell:
            print(f"   {r['ticker']}: ${r['current']:.2f}")
    
    if stop_loss:
        print(f"\n🚨 止損提醒 ({len(stop_loss)} 檔):")
        for r in stop_loss:
            print(f"   {r['ticker']}: 現價 ${r['current']:.2f} < 止損價 ${r['stop_price']}")
    
    if breakout:
        print(f"\n📈 突破訊號 ({len(breakout)} 檔):")
        for r in breakout:
            vol_status = "放量確認" if r.get('volume_confirmed') else "成交量不足"
            print(f"   {r['ticker']}: {r['stage_desc']} ({vol_status})")
    
    print(f"\n💡 心法: 不焦急、不貪心")
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
        result = backtest_box_strategy(ticker, info, period="2y")
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
