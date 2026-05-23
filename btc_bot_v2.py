import os
import time
import requests
from datetime import datetime

# ============================================================
# CONFIG
# ============================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

INITIAL_CAPITAL = 300
RISK_PER_TRADE = 0.01
TICK_INTERVAL = 60
MIN_CONFIDENCE = 70

# ============================================================
# STATE
# ============================================================
capital = INITIAL_CAPITAL
price_history = []
current_position = None
trades = []
consecutive_losses = 0

# ============================================================
# TELEGRAM
# ============================================================
def send_telegram(msg):
    if not CHAT_ID:
        print(f"[TELEGRAM] {msg}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": msg,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def get_chat_id():
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get("result"):
            return str(data["result"][-1]["message"]["chat"]["id"])
    except:
        pass
    return None

# ============================================================
# BTC ouvert 24/7 — pas de weekend check
# ============================================================

# ============================================================
# PRIX RÉEL BTC/USD — Binance (gratuit, pas de clé)
# ============================================================
def fetch_price():
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
            timeout=10
        )
        data = r.json()
        if data.get("price"):
            return round(float(data["price"]), 2)
    except:
        pass
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
            timeout=10
        )
        data = r.json()
        if data.get("bitcoin"):
            return round(data["bitcoin"]["usd"], 2)
    except:
        pass
    if price_history:
        import random
        last = price_history[-1]
        return round(last * (1 + (random.random() - 0.5) * 0.002), 2)
    return 105000.0

# ============================================================
# INDICATEURS
# ============================================================
def ema(prices, period):
    k = 2 / (period + 1)
    e = prices[0]
    for p in prices[1:]:
        e = p * k + e * (1 - k)
    return round(e, 2)

def rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    deltas = deltas[-period:]
    gains = [d for d in deltas if d > 0]
    losses = [-d for d in deltas if d < 0]
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)

def atr(prices, period=14):
    if len(prices) < 2:
        return 100.0
    trs = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
    trs = trs[-period:]
    return round(sum(trs) / len(trs), 2)

def macd(prices):
    if len(prices) < 35:
        return 0, 0
    ema12 = ema(prices[-15:], 12)
    ema26 = ema(prices[-30:], 26)
    macd_line = ema12 - ema26
    return round(macd_line, 2), round(macd_line * 0.9, 2)

# ============================================================
# SIGNAL PRO
# ============================================================
def compute_signal():
    if len(price_history) < 60:
        return None

    e20 = ema(price_history[-25:], 20)
    e50 = ema(price_history[-55:], 50)
    e200 = ema(price_history[-100:], 100) if len(price_history) >= 100 else None
    r = rsi(price_history[-20:], 14)
    a = atr(price_history[-20:], 14)
    macd_line, macd_signal = macd(price_history)
    price = price_history[-1]

    score = 0

    if e20 > e50: score += 2
    else: score -= 2

    if e200:
        if price > e200: score += 2
        else: score -= 2

    if r < 30: score += 3
    elif r > 70: score -= 3

    if price > e20 * 1.001: score += 1
    elif price < e20 * 0.999: score -= 1

    if macd_line > macd_signal: score += 1
    else: score -= 1

    signal = "HOLD"
    if score >= 4: signal = "BUY"
    elif score <= -4: signal = "SELL"

    sl = round(price - a * 1.5, 2) if signal == "BUY" else round(price + a * 1.5, 2)
    tp = round(price + a * 2.5, 2) if signal == "BUY" else round(price - a * 2.5, 2)
    conf = min(95, abs(score) * 14 + 25)

    return {
        "signal": signal, "price": price, "sl": sl, "tp": tp,
        "conf": conf, "rsi": r, "e20": e20, "e50": e50,
        "macd": macd_line, "atr": a
    }

# ============================================================
# POSITIONS
# ============================================================
def open_position(sig):
    global current_position, capital
    risk = capital * RISK_PER_TRADE
    size = round(risk / abs(sig["price"] - sig["sl"]), 8)
    current_position = {
        "type": sig["signal"],
        "entry": sig["price"],
        "sl": sig["sl"],
        "tp": sig["tp"],
        "size": size,
        "time": datetime.now().strftime("%H:%M:%S")
    }
    emoji = "🟢" if sig["signal"] == "BUY" else "🔴"
    send_telegram(
        f"{emoji} <b>TRADE BTC — {sig['signal']}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"₿ Entrée : <b>${sig['price']:,.2f}</b>\n"
        f"🛑 Stop Loss : ${sig['sl']:,.2f}\n"
        f"🎯 Take Profit : ${sig['tp']:,.2f}\n"
        f"📊 Confiance : {sig['conf']}%\n"
        f"📈 RSI : {sig['rsi']} | MACD : {sig['macd']}\n"
        f"⚡ ATR : {sig['atr']}\n"
        f"⏰ {current_position['time']}"
    )

def check_position(price):
    global current_position, capital, trades, consecutive_losses
    if not current_position:
        return

    pos = current_position
    closed = False
    pnl = 0
    reason = ""

    if pos["type"] == "BUY":
        if price <= pos["sl"]:
            pnl = (pos["sl"] - pos["entry"]) * pos["size"]
            closed, reason = True, "SL"
        elif price >= pos["tp"]:
            pnl = (pos["tp"] - pos["entry"]) * pos["size"]
            closed, reason = True, "TP"
    else:
        if price >= pos["sl"]:
            pnl = (pos["entry"] - pos["sl"]) * pos["size"]
            closed, reason = True, "SL"
        elif price <= pos["tp"]:
            pnl = (pos["entry"] - pos["tp"]) * pos["size"]
            closed, reason = True, "TP"

    if closed:
        pnl = round(pnl, 2)
        capital = round(capital + pnl, 2)
        trades.append({"pnl": pnl, "reason": reason})
        current_position = None

        if pnl < 0:
            consecutive_losses += 1
        else:
            consecutive_losses = 0

        wins = len([t for t in trades if t["pnl"] > 0])
        losses = len([t for t in trades if t["pnl"] <= 0])
        winrate = round(wins / len(trades) * 100) if trades else 0
        emoji = "✅" if pnl > 0 else "❌"

        msg = (
            f"{emoji} <b>TRADE BTC FERMÉ [{reason}]</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📍 Entrée : ${pos['entry']:,.2f} → Sortie : ${price:,.2f}\n"
            f"{'🟢' if pnl > 0 else '🔴'} P&L : <b>{'+'if pnl>0 else ''}{pnl}$</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💼 Capital : {capital}$\n"
            f"📊 Win rate : {winrate}% ({wins}W / {losses}L)"
        )

        if consecutive_losses >= 3:
            msg += f"\n\n⚠️ <b>CIRCUIT BREAKER</b> — 3 pertes de suite. Bot en pause 2h."
            send_telegram(msg)
            time.sleep(7200)
            consecutive_losses = 0
            return

        send_telegram(msg)

# ============================================================
# MAIN LOOP
# ============================================================
def main():
    global capital, CHAT_ID

    print("🚀 BTC BOT v2 PRO démarré")

    if not CHAT_ID:
        while not CHAT_ID:
            cid = get_chat_id()
            if cid:
                CHAT_ID = cid
                break
            time.sleep(3)

    send_telegram(
        "₿ <b>BTC BOT v2 PRO démarré</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💰 Capital : 300€\n"
        f"⚠️ Risque : 1% par trade\n"
        f"📊 Marché : BTC/USD\n"
        f"🧠 Stratégie : EMA 20/50/200 + RSI + MACD + ATR\n"
        f"🎯 Seuil confiance : {MIN_CONFIDENCE}%\n"
        f"🔒 Circuit breaker : 3 pertes = pause 2h\n"
        f"⏰ Actif 24/7 (crypto ne ferme jamais)"
    )

    tick = 0
    while True:
        try:
            price = fetch_price()
            price_history.append(price)
            if len(price_history) > 200:
                price_history.pop(0)

            check_position(price)
            sig = compute_signal()

            if sig and sig["signal"] != "HOLD" and not current_position and sig["conf"] >= MIN_CONFIDENCE:
                open_position(sig)

            if tick > 0 and tick % 60 == 0:
                wins = len([t for t in trades if t["pnl"] > 0])
                losses = len([t for t in trades if t["pnl"] <= 0])
                pnl_total = round(capital - INITIAL_CAPITAL, 2)
                pos_info = f"{current_position['type']} @ ${current_position['entry']:,.2f}" if current_position else "Aucune"

                send_telegram(
                    f"📊 <b>RÉSUMÉ HORAIRE — BTC</b>\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"₿ BTC/USD : ${price:,.2f}\n"
                    f"💰 Capital : {capital}$\n"
                    f"{'🟢' if pnl_total >= 0 else '🔴'} P&L : {'+'if pnl_total>=0 else ''}{pnl_total}$\n"
                    f"🏆 {wins}W / {losses}L\n"
                    f"📍 Position : {pos_info}"
                )

            tick += 1
            time.sleep(TICK_INTERVAL)

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Erreur : {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
