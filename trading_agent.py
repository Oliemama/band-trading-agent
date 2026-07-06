#!/usr/bin/env python3
import os
import smtplib
import yfinance as yf
import numpy as np
import pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

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

def fetch_stock_data(ticker, period="6mo"):
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period=period)
        if df.empty:
            return None
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
        df.columns = ['open', 'high', 'low', 'close', 'volume']
        return df
    except:
        return None

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

def simulate_adr_from_stocks(stock_data_dict):
    advances = 0
    declines = 0
    for ticker, df in stock_data_dict.items():
        if df is not None and len(df) > 1:
            today = df['close'].iloc[-1]
            yesterday = df['close'].iloc[-2]
            if today > yesterday:
                advances += 1
            elif today < yesterday:
                declines += 1
    if declines == 0:
        return 1.5 if advances > 0 else 1.0
    return advances / declines

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

def send_email(subject, body):
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
    lines = [f"📊 波段管家日報 {now}", "=" * 35]
    if adr_info:
        lines.append(f"🌡️ ADR={adr_info['adr']:.2f} {adr_info['description']}")
    for r in results:
        lines.append(f"\n{r['stage_emoji']} {r['ticker']} ({r['name']})")
        lines.append(f"   現價: ${r['current']:.2f}")
        lines.append(f"   支撐: ${r['support']:.2f} | 壓力: ${r['resistance']:.2f}")
        lines.append(f"   狀態: {r['stage_desc']}")
    lines.append("\n💡 心法: 不焦急、不貪心")
    return "\n".join(lines)

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
    print(f"   現價: ${result['current']:.2f}")
    print(f"   支撐: ${result['support']:.2f} | 壓力: ${result['resistance']:.2f}")
    print(f"   位置: {result['position']*100:.1f}%")
    print(f"   狀態: {result['stage_emoji']} {result['stage_desc']}")
    return result

def run_daily_check():
    print("=" * 50)
    print("📊 低買高賣波段管家")
    print(f"🕐 {datetime.now().strftime('%Y/%m/%d %H:%M')}")
    print("=" * 50)
    
    results = []
    all_data = {}
    
    for ticker, info in HOLDINGS.items():
        result = analyze_single_stock(ticker, info)
        if result:
            results.append(result)
            df = fetch_stock_data(ticker, period="6mo")
            if df is not None:
                all_data[ticker] = df
    
    if not results:
        print("❌ 分析失敗")
        return
    
    adr_value = simulate_adr_from_stocks(all_data)
    adr_status = get_adr_status(adr_value)
    adr_info = {'adr': adr_value, **adr_status}
    
    print(f"\n🌡️ 市場情緒: {adr_info['emoji']} ADR={adr_value:.2f}")
    print(f"   {adr_info['description']} - {adr_info['action']}")
    
    print(f"\n{'=' * 50}")
    print("📋 摘要")
    low_buy = [r for r in results if r['stage'] == 'low_buy']
    high_sell = [r for r in results if r['stage'] == 'high_sell']
    if low_buy:
        print(f"🟢 低買區: {', '.join(r['ticker'] for r in low_buy)}")
    if high_sell:
        print(f"🔴 高賣區: {', '.join(r['ticker'] for r in high_sell)}")
    print(f"💡 心法: 不焦急、不貪心")
    
    report = format_daily_report(results, adr_info)
    subject = f"📊 波段管家日報 {datetime.now().strftime('%Y/%m/%d %H:%M')}"
    send_email(subject, report)

if __name__ == "__main__":
    run_daily_check()
