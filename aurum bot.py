import os
import time
import requests
from datetime import datetime

# ============================================================
# CONFIG
# ============================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8805244480:AAF0s1b3CEyeK8jGUGEotxBq8UjCJeHd4lc")
CHAT_ID = os.environ.get("CHAT_ID", "")
GOLDAPI_KEY = os.environ.get("GOLDAPI_KEY", "goldapi-3dd6aedf40575a54357f39ec3927b19b-io")

INITIAL_CAPITAL = 300
RISK_PER_TRADE = 0.01  # 1% par trade (prudent sur petit capital = 3€ risqué par trade)
TICK_INTERVAL = 60     # secondes entre chaque analyse

# ============================================================
# STATE
# ============================================================
capital = INITIAL_CAPITAL
price_history = []
current_position = None
trades = []

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
    """Récupère le chat_id du premier message reçu"""
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
# PRIX RÉEL XAU/USD
# ============================================================
def fetch_price():
    try:
        r = requests.get(
            "https://api.metals.live/v1/spot/gold",
            timeout=10
        )
        data = r.json()
        if data and data[0].get("price"):
            return round(data[0]["price"], 2)
    except:
        pass

    # Fallback Goldapi
    try:
        r = requests.get(
            "https://www.goldapi.io/api/XAU/USD",
            headers={"x-access-token": GOLDAPI_KEY},
            timeout=10
        )
        data = r.json()
        if data.get("price"):
            return round(data["price"], 2)
    except:
        pass

    # Fallback simulation si APIs indisponibles
    if price_history:
        import random
        last = price_history[-1]
        return round(last * (1 + (random.random() - 0.5) * 0.002), 2)
    return 3320.0

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
        return 1.0
    trs = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
    trs = trs[-period:]
    return round(sum(trs) / len(trs), 2)

# ============================================================
# SIGNAL
# ============================================================
def compute_signal():
    if len(price_history) < 55:
        return None

    e20 = ema(price_history[-25:], 20)
    e50 = ema(price_history[-55:], 50)
    r = rsi(price_history[-20:], 14)
    a = atr(price_history[-20:], 14)
    price = price_history[-1]

    score = 0
    if e20 > e50: score += 2
    else: score -= 2
    if r < 35: score += 3
    elif r > 65: score -= 3
    if price > e20: score += 1
    else: score -= 1

    signal = "HOLD"
    if score >= 3: signal = "BUY"
    elif score <= -3: signal = "SELL"

    sl = round(price - a * 1.5, 2) if signal == "BUY" else round(price + a * 1.5, 2)
    tp = round(price + a * 2.5, 2) if signal == "BUY" else round(price - a * 2.5, 2)
    conf = min(95, abs(score) * 15 + 30)

    return {"signal": signal, "price": price, "sl": sl, "tp": tp, "conf": conf, "rsi": r, "e20": e20, "e50": e50}

# ============================================================
# POSITIONS
# ============================================================
def open_position(sig):
    global current_position, capital
    risk = capital * RISK_PER_TRADE
    size = round(risk / abs(sig["price"] - sig["sl"]), 4)
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
        f"{emoji} <b>NOUVEAU TRADE — {sig['signal']}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💰 Entrée : <b>{sig['price']}</b>\n"
        f"🛑 Stop Loss : {sig['sl']}\n"
        f"🎯 Take Profit : {sig['tp']}\n"
        f"📊 Confiance : {sig['conf']}%\n"
        f"📈 RSI : {sig['rsi']}\n"
        f"⏰ {current_position['time']}"
    )

def check_position(price):
    global current_position, capital, trades
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
        trades.append({"type": pos["type"], "entry": pos["entry"], "close": price, "pnl": pnl, "reason": reason})
        current_position = None

        wins = len([t for t in trades if t["pnl"] > 0])
        losses = len([t for t in trades if t["pnl"] <= 0])
        winrate = round(wins / len(trades) * 100) if trades else 0
        emoji = "✅" if pnl > 0 else "❌"

        send_telegram(
            f"{emoji} <b>TRADE FERMÉ [{reason}]</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📍 Entrée : {pos['entry']} → Sortie : {price}\n"
            f"{'🟢' if pnl > 0 else '🔴'} P&L : <b>{'+'if pnl>0 else ''}{pnl}$</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💼 Capital : {capital}$\n"
            f"📊 Win rate : {winrate}% ({wins}W / {losses}L)"
        )

# ============================================================
# MAIN LOOP
# ============================================================
def main():
    global capital

    print("🚀 AURUM BOT démarré")
    print(f"Capital initial : ${INITIAL_CAPITAL}")

    # Récupérer le chat_id automatiquement
    chat_id = CHAT_ID
    if not chat_id:
        print("En attente d'un message Telegram pour récupérer le chat_id...")
        print(f"Envoie /start à @Kint180_bot sur Telegram")
        while not chat_id:
            chat_id = get_chat_id()
            if chat_id:
                os.environ["CHAT_ID"] = chat_id
                # Patch global
                import builtins
                globals()["CHAT_ID"] = chat_id
                print(f"Chat ID récupéré : {chat_id}")
                break
            time.sleep(3)

    send_telegram(
        "🤖 <b>AURUM BOT démarré</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💰 Capital : 300€\n"
        f"⚠️ Risque par trade : 1% = ~3€\n"
        f"📊 Marché : XAU/USD\n"
        f"⚙️ Stratégie : EMA 20/50 + RSI + ATR\n"
        f"🔄 Analyse toutes les {TICK_INTERVAL}s\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Le bot trade en paper trading automatiquement."
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

            if sig and sig["signal"] != "HOLD" and not current_position and sig["conf"] > 50:
                open_position(sig)

            # Résumé toutes les heures (60 ticks)
            if tick > 0 and tick % 60 == 0:
                wins = len([t for t in trades if t["pnl"] > 0])
                losses = len([t for t in trades if t["pnl"] <= 0])
                pnl_total = round(capital - INITIAL_CAPITAL, 2)
                pos_info = f"Position ouverte : {current_position['type']} @ {current_position['entry']}" if current_position else "Aucune position ouverte"

                send_telegram(
                    f"📊 <b>RÉSUMÉ HORAIRE</b>\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"💰 Capital : {capital}$\n"
                    f"{'🟢' if pnl_total >= 0 else '🔴'} P&L : {'+'if pnl_total>=0 else ''}{pnl_total}$\n"
                    f"📈 XAU/USD : {price}\n"
                    f"🏆 Trades : {wins}W / {losses}L\n"
                    f"📍 {pos_info}"
                )

            tick += 1
            time.sleep(TICK_INTERVAL)

        except KeyboardInterrupt:
            print("\nBot arrêté.")
            break
        except Exception as e:
            print(f"Erreur : {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
