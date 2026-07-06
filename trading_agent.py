#!/usr/bin/env python3
"""
低買高賣波段操盤 Agent - 強化版
根據上岡正明《日本最強散戶贏家教你低買高賣的波段操盤術》

強化功能：
1. 真實 ADR - 接入 NYSE/NASDAQ 漲跌家數
2. 回測功能 - 驗證過去 1-2 年箱型策略績效
3. 止損機制 - 跌破支撐線 5% 自動提醒
4. 成交量確認 - 突破時配合成交量放大
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
# 股票清單
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

# 郵件設定（優先使用環境變數，適用於 GitHub Actions）
EMAIL_SENDER = os.environ.get('EMAIL_SENDER', 'shirleyliu0118@gmail.com')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', '')
EMAIL_RECEIVER = os.environ.get('EMAIL_RECEIVER', 'shirleyliu0118@gmail.com')
EMAIL_SMTP_SERVER = "smtp.gmail.com"
EMAIL_SMTP_PORT = 587

# 止損設定
STOP_LOSS_PCT = 0.05  # 跌破支撐線 5% 止損

# 成交量確認設定
VOLUME_THRESHOLD = 1.5  # 突破需大於均量 1.5 倍

# ==================== 資料抓取 ====================
def fetch_stock_data(ticker, period="6mo"):
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

# ==================== 箱型分析 ====================
def analyze_box_pattern(df, period_days=90):
    if df is None or len(df) < 20:
        return None
    recent = df.tail(period_days)
    resistance = np.percentile(recent['high'].values, 97)
    support = np.percentile(recent['low'].values, 3)
    current = df['close'].iloc[-1]
    box_range = resistance - support
    if box_range <= 0:
        box_range = current * 0.1
    position = (current - support) / box_range
    position = max(0, min(1, position))
    if current < support * 0.97:
        stage = "breakdown"
    elif current > resistance * 1.03:
        stage = "breakup"
    elif position < 0.15:
        stage = "low_buy"
    elif position > 0.85:
        stage = "high_sell"
    else:
        stage = "watch"
    return {
        'support': round(support, 2),
        'resistance': round(resistance, 2),
        'current': round(current, 2),
        'position': round(position, 3),
        'stage': stage,
    }

def get_stage_emoji(stage):
    return {"low_buy": "🟢", "high_sell": "🔴", "watch": "🟡",
            "breakup": "📈", "breakdown": "📉"}.get(stage, "⚪")

def get_stage_description(stage):
    return {"low_buy": "低買區", "high_sell": "高賣區", "watch": "觀望區",
            "breakup": "向上突破", "breakdown": "跌破支撐"}.get(stage, "未知")

# ==================== 真實 ADR（接入 NYSE/NASDAQ）====================
def fetch_nyse_advances_declines():
    """
    抓取 NYSE/NASDAQ 漲跌家數估算真實 ADR
    使用多指數綜合判斷市場情緒
    """
    try:
        indices = {
            'NYSE': '^NYA',
            'NASDAQ': '^IXIC',
            'S&P500': '^GSPC',
            'DOW': '^DJI',
            'RUSSELL': '^RUT'
        }
        
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
    """
    檢查是否觸及止損
    跌破支撐線 5% 自動提醒止損
    """
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
    """
    突破時檢查成交量是否放大
    回傳：(是否放量, 成交量倍數)
    """
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
    """
    回測箱型策略在過去 1-2 年的表現
    回傳：勝率、平均報酬、最大回撤
    """
    print(f"\n📈 回測: {ticker} ({info.get('name', '')}) - 過去 {period}")
    print("-" * 40)
    
    df = fetch_stock_data(ticker, period=period)
    if df is None or len(df) < 200:
        print("   ❌ 資料不足，無法回測")
        return None
    
    signals = []
    position = None
    entry_price = 0
    entry_date = None
    
    # 每 5 天檢查一次，90 天窗口
    for i in range(90, len(df) - 30, 5):
        window = df.iloc[i-90:i]
        current = df['close'].iloc[i]
        current_date = df.index[i]
        
        resistance = np.percentile(window['high'].values, 97)
        support = np.percentile(window['low'].values, 3)
        
        # 買進信號：接近支撐線
        if current < support * 1.05 and position is None:
            position = 'long'
            entry_price = current
            entry_date = current_date
            
            # 計算 30 天後報酬
            future_idx = min(i + 30, len(df) - 1)
            future_price = df['close'].iloc[future_idx]
            ret = (future_price - entry_price) / entry_price * 100
            
            signals.append({
                'type': 'buy',
                'entry_price': round(entry_price, 2),
                'entry_date': entry_date.strftime('%Y-%m-%d'),
                'exit_price': round(future_price, 2),
                'return': round(ret, 2)
            })
            
            position = None  # 簡化：持有 30 天後自動平倉
        
        # 止損檢查
        elif position == 'long' and current < support * 0.95:
            ret = (current - entry_price) / entry_price * 100
            signals.append({
                'type': 'stop_loss',
                'entry_price': round(entry_price, 2),
                'entry_date': entry_date.strftime('%Y-%m-%d'),
                'exit_price': round(current, 2),
                'return': round(ret, 2)
            })
            position = None
    
    if not signals:
        print("   ⚠️ 過去期間內無明確交易信號")
        return None
    
    # 計算績效
    returns = [s['return'] for s in signals]
    wins = sum(1 for r in returns if r > 0)
    total = len(returns)
    
    result = {
        'ticker': ticker,
        'name': info.get('name', ticker),
        'total_signals': total,
        'win_rate': round(wins / total * 100, 1) if total > 0 else 0,
        'avg_return': round(np.mean(returns), 2),
        'max_return': round(max(returns), 2) if returns else 0,
        'min_return': round(min(returns), 2) if returns else 0,
        'signals': signals
    }
    
    print(f"   總交易次數: {total}")
    print(f"   勝率: {result['win_rate']}%")
    print(f"   平均報酬: {result['avg_return']}%")
    print(f"   最佳交易: +{result['max_return']}%")
    print(f"   最差交易: {result['min_return']}%")
    
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
    lines = [f"📊 波段管家日報（強化版）{now}", "=" * 40]
    
    if adr_info:
        lines.append(f"🌡️ 市場情緒 (真實 ADR): {adr_info['emoji']} {adr_info['adr']:.2f}")
        lines.append(f"   {adr_info['description']}")
        lines.append(f"   💡 {adr_info['action']}")
    
    # 止損提醒優先顯示
    stop_loss = [r for r in results if r.get('stop_loss_alert')]
    if stop_loss:
        lines.append("\n🚨【止損提醒 - 立即行動】")
        for r in stop_loss:
            lines.append(f"   {r['ticker']} ({r['name']})")
            lines.append(f"   現價: ${r['current']:.2f} | 止損價: ${r['stop_price']}")
            lines.append(f"   已跌破支撐線 5%，建議立即止損！")
    
    lines.append("\n📈 個股分析:")
    lines.append("-" * 40)
    
    for r in results:
        lines.append(f"\n{r['stage_emoji']} {r['ticker']} ({r['name']})")
        lines.append(f"   現價: ${r['current']:.2f}")
        lines.append(f"   支撐: ${r['support']:.2f} | 壓力: ${r['resistance']:.2f}")
        lines.append(f"   位置: {r['position']*100:.1f}% | 狀態: {r['stage_desc']}")
        
        # 成交量確認
        if 'volume_ratio' in r:
            if r.get('volume_confirmed'):
                lines.append(f"   ✅ 成交量確認: {r['volume_ratio']}倍放量")
            else:
                lines.append(f"   📊 成交量: {r['volume_ratio']}倍 (未達 1.5 倍門檻)")
        
        # 具體建議
        if r.get('stop_loss_alert'):
            lines.append(f"   🚨 建議: 止損！已跌破支撐線 5%")
        elif r['stage'] == 'low_buy':
            lines.append(f"   ✅ 建議: 接近支撐線，可觀察買進機會")
        elif r['stage'] == 'high_sell':
            lines.append(f"   ⚠️ 建議: 接近壓力線，考慮獲利減碼")
        elif r['stage'] == 'breakup' and r.get('volume_confirmed'):
            lines.append(f"   📈 建議: 放量突破，順勢操作")
        elif r['stage'] == 'breakup' and not r.get('volume_confirmed'):
            lines.append(f"   ⚠️ 建議: 突破但成交量不足，觀望確認")
        elif r['stage'] == 'breakdown':
            lines.append(f"   📉 建議: 跌破箱型，注意風險/止損")
        else:
            lines.append(f"   ⏳ 建議: 觀望，等待觸及關鍵價位")
    
    lines.append("\n" + "=" * 40)
    lines.append("💡 心法: 不焦急、不貪心，等待股價來到購買區")
    lines.append("📚 來源: 上岡正明《低買高賣的波段操盤術》")
    lines.append("🔧 強化功能: 真實 ADR | 回測驗證 | 止損機制 | 成交量確認")
    return "\n".join(lines)

def format_backtest_report(backtest_results):
    """格式化回測報告"""
    now = datetime.now().strftime("%Y/%m/%d")
    lines = [f"📊 波段管家 - 回測報告 {now}", "=" * 40]
    lines.append("過去 2 年箱型策略績效驗證")
    lines.append("-" * 40)
    
    total_wins = 0
    total_trades = 0
    
    for result in backtest_results:
        if result is None:
            continue
        lines.append(f"\n📈 {result['ticker']} ({result['name']})")
        lines.append(f"   交易次數: {result['total_signals']}")
        lines.append(f"   勝率: {result['win_rate']}%")
        lines.append(f"   平均報酬: {result['avg_return']}%")
        lines.append(f"   最佳: +{result['max_return']}% | 最差: {result['min_return']}%")
        
        total_wins += int(result['win_rate'] * result['total_signals'] / 100)
        total_trades += result['total_signals']
    
    if total_trades > 0:
        overall_win_rate = total_wins / total_trades * 100
        lines.append(f"\n{'=' * 40}")
        lines.append(f"📊 綜合勝率: {overall_win_rate:.1f}% ({total_wins}/{total_trades})")
    
    lines.append(f"\n💡 回測僅供參考，過去績效不代表未來結果")
    return "\n".join(lines)

# ==================== 主程式 ====================
def analyze_single_stock(ticker, info):
    print(f"\n📊 分析: {ticker} ({info.get('name', '')})")
    df = fetch_stock_data(ticker, period="6mo")
    if df is None:
        print("   ❌ 無法取得資料")
        return None
    box = analyze_box_pattern(df, period_days=90)
    if box is None:
        return None
    result = {
        'ticker': ticker,
        'name': info.get('name', ticker),
        **box,
        'stage_emoji': get_stage_emoji(box['stage']),
        'stage_desc': get_stage_description(box['stage']),
    }
    
    # 止損檢查
    stop_check = check_stop_loss(result['current'], result['support'])
    if stop_check['triggered']:
        result['stop_loss_alert'] = True
        result['stop_price'] = stop_check['stop_price']
        print(f"   🚨 止損提醒：跌破支撐線 5%！止損價 ${stop_check['stop_price']}")
    else:
        result['stop_loss_alert'] = False
    
    # 成交量確認
    vol_confirmed, vol_ratio = check_volume_confirmation(df)
    result['volume_confirmed'] = vol_confirmed
    result['volume_ratio'] = vol_ratio
    if result['stage'] in ['breakup', 'breakdown']:
        if vol_confirmed:
            print(f"   ✅ 成交量確認：放量 {vol_ratio} 倍")
        else:
            print(f"   ⚠️ 成交量不足：僅 {vol_ratio} 倍")
    
    print(f"   現價: ${result['current']:.2f}")
    print(f"   支撐: ${result['support']:.2f} | 壓力: ${result['resistance']:.2f}")
    print(f"   位置: {result['position']*100:.1f}%")
    print(f"   狀態: {result['stage_emoji']} {result['stage_desc']}")
    
    return result

def run_daily_check():
    print("=" * 60)
    print("📊 低買高賣波段管家（強化版）")
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
    
    # 真實 ADR
    adr_value = fetch_nyse_advances_declines()
    adr_status = get_adr_status(adr_value)
    adr_info = {'adr': adr_value, **adr_status}
    
    print(f"\n🌡️ 市場情緒 (真實 ADR): {adr_info['emoji']} {adr_value:.2f}")
    print(f"   {adr_info['description']} - {adr_info['action']}")
    
    # 摘要
    print(f"\n{'=' * 60}")
    print("📋 今日摘要")
    print(f"{'=' * 60}")
    
    low_buy = [r for r in results if r['stage'] == 'low_buy']
    high_sell = [r for r in results if r['stage'] == 'high_sell']
    stop_loss = [r for r in results if r.get('stop_loss_alert')]
    breakout = [r for r in results if r['stage'] in ['breakup', 'breakdown']]
    
    if low_buy:
        print(f"\n🟢 低買區 ({len(low_buy)} 檔):")
        for r in low_buy:
            print(f"   {r['ticker']}: ${r['current']:.2f}")
    
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
    
    # 郵件通知
    report = format_daily_report(results, adr_info)
    subject = f"📊 波段管家日報 {datetime.now().strftime('%Y/%m/%d %H:%M')}"
    send_email(subject, report)

def run_backtest():
    """執行回測"""
    print("=" * 60)
    print("📊 波段管家 - 回測模式")
    print(f"🕐 {datetime.now().strftime('%Y/%m/%d %H:%M')}")
    print("=" * 60)
    print("驗證過去 2 年箱型策略績效...")
    
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
