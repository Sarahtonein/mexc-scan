
import requests
import time
import json
import os
from datetime import datetime, timedelta, timezone

# ============================================================
# CONFIGURATION
# ============================================================

MEXC_GET_URL = "https://contract.mexc.com/api/v1/contract/detail"
MEXC_PRICE_URL = "https://contract.mexc.com/api/v1/contract/ticker?symbol={}"

OURBIT_GET_URL = "https://futures.ourbit.com/api/v1/contract/detail"
OURBIT_PRICE_URL = "https://futures.ourbit.com/api/v1/contract/ticker?symbol={}"

POST_URL = os.getenv("POST_URL")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

TRACKED_TOKENS_FILE = "tracked_tokens.json"
KNOWN_CONTRACTS_FILE = "known_contracts.json"

AEST = timezone(timedelta(hours=10))

POLL_INTERVAL = 25
TRACKING_HOURS = 8
DIVERGENCE_HOURS = 48


# ============================================================
# GENERAL HELPERS
# ============================================================

def log(message):
    print(
        f"[{datetime.now(timezone.utc).isoformat()}] {message}",
        flush=True
    )


def is_stock_symbol(symbol):
    return isinstance(symbol, str) and "STOCK" in symbol.upper()


def format_aest_time(value):
    if value is None:
        return "Unknown"

    if isinstance(value, str):
        value = datetime.fromisoformat(value)

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(AEST).strftime("%Y-%m-%d %H:%M:%S AEST")


def is_divergence_monitor_active(
    tracked_at,
    current_time=None,
    window_hours=48
):
    if current_time is None:
        current_time = datetime.now(timezone.utc)

    if isinstance(tracked_at, str):
        tracked_at = datetime.fromisoformat(tracked_at)

    if tracked_at.tzinfo is None:
        tracked_at = tracked_at.replace(tzinfo=timezone.utc)

    return (
        current_time - tracked_at
    ) < timedelta(hours=window_hours)


# ============================================================
# FILE STORAGE
# ============================================================

def load_tracked_tokens():
    try:
        with open(TRACKED_TOKENS_FILE, "r") as file:
            content = file.read().strip()
            return json.loads(content) if content else {}

    except (FileNotFoundError, json.JSONDecodeError) as e:
        log(f"Error loading tracked tokens: {e}")
        return {}


def save_tracked_tokens(tokens):
    try:
        with open(TRACKED_TOKENS_FILE, "w") as file:
            json.dump(tokens, file, indent=4)

    except Exception as e:
        log(f"Error saving tracked tokens: {e}")


def load_known_contracts():
    try:
        with open(KNOWN_CONTRACTS_FILE, "r") as file:
            return json.load(file)

    except (FileNotFoundError, json.JSONDecodeError):
        return {"ourbit": []}


def save_known_contracts(contracts):
    try:
        with open(KNOWN_CONTRACTS_FILE, "w") as file:
            json.dump(contracts, file, indent=4)

    except Exception as e:
        log(f"Error saving known contracts: {e}")


# ============================================================
# EXCHANGE API
# ============================================================

def get_tokens(exchange):
    urls = {
        "mexc": MEXC_GET_URL,
        "ourbit": OURBIT_GET_URL,
    }

    try:
        response = requests.get(
            urls[exchange],
            timeout=15
        )

        response.raise_for_status()
        data = response.json()

        tokens = (
            data.get("data", [])
            if isinstance(data, dict)
            else []
        )

        if not isinstance(tokens, list):
            log(f"{exchange.upper()}: Unexpected contract response")
            return []

        log(
            f"{exchange.upper()}: Retrieved "
            f"{len(tokens)} contracts"
        )

        return tokens

    except Exception as e:
        log(f"{exchange.upper()} contract fetch error: {e}")
        return []


def get_token_price(symbol, exchange="mexc"):
    urls = {
        "mexc": MEXC_PRICE_URL.format(symbol),
        "ourbit": OURBIT_PRICE_URL.format(symbol),
    }

    try:
        response = requests.get(
            urls[exchange],
            timeout=15
        )

        response.raise_for_status()
        data = response.json()

        ticker = (
            data.get("data", data)
            if isinstance(data, dict)
            else {}
        )

        if isinstance(ticker, list):
            ticker = ticker[0] if ticker else {}

        if not isinstance(ticker, dict):
            return None

        price = (
            ticker.get("lastPrice")
            or ticker.get("last")
            or ticker.get("price")
        )

        if price is None:
            log(
                f"{exchange.upper()}: No price for "
                f"{symbol}: {data}"
            )
            return None

        return float(price)

    except Exception as e:
        log(
            f"{exchange.upper()} price error "
            f"for {symbol}: {e}"
        )
        return None


def get_contract_link(exchange, symbol):
    if exchange == "ourbit":
        return f"https://www.ourbit.com/futures/{symbol}"

    return (
        f"https://futures.mexc.com/exchange/"
        f"{symbol}?type=linear_swap"
    )


# ============================================================
# RSI
# ============================================================

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return []

    deltas = [
        float(closes[i]) - float(closes[i - 1])
        for i in range(1, len(closes))
    ]

    gains = [max(delta, 0.0) for delta in deltas]
    losses = [abs(min(delta, 0.0)) for delta in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    rsi_values = [50.0]

    for index in range(period, len(deltas)):

        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        rsi_values.append(rsi)

        avg_gain = (
            (avg_gain * (period - 1)) + gains[index]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1)) + losses[index]
        ) / period

    while len(rsi_values) < len(closes):
        rsi_values.append(rsi_values[-1])

    return rsi_values[:len(closes)]


def detect_bearish_divergence(prices, rsi_values):
    if len(prices) < 10 or len(rsi_values) < 10:
        return None

    def pivot_indexes(values, is_high):
        pivots = []

        for index in range(1, len(values) - 1):
            current = values[index]
            previous = values[index - 1]
            next_value = values[index + 1]

            if is_high:
                if (
                    current >= previous
                    and current >= next_value
                    and (
                        current > previous
                        or current > next_value
                    )
                ):
                    pivots.append(index)

            else:
                if (
                    current <= previous
                    and current <= next_value
                    and (
                        current < previous
                        or current < next_value
                    )
                ):
                    pivots.append(index)

        return pivots

    price_highs = pivot_indexes(prices, True)
    rsi_highs = pivot_indexes(rsi_values, True)

    price_lows = pivot_indexes(prices, False)
    rsi_lows = pivot_indexes(rsi_values, False)

    for earlier in price_highs:
        for later in price_highs:

            if later <= earlier:
                continue

            if prices[later] <= prices[earlier]:
                continue

            if rsi_values[later] >= rsi_values[earlier]:
                continue

            return "regular"

    for earlier in price_lows:
        for later in price_lows:

            if later <= earlier:
                continue

            if prices[later] >= prices[earlier]:
                continue

            if rsi_values[later] <= rsi_values[earlier]:
                continue

            return "hidden"

    return None


# ============================================================
# MEXC SPOT KLINES / DIVERGENCE
# ============================================================

def fetch_spot_klines(symbol, interval="15m", limit=200):
    spot_url = "https://api.mexc.com/api/v3/klines"

    try:
        response = requests.get(
            spot_url,
            params={
                "symbol": symbol,
                "interval": interval,
                "limit": limit,
            },
            timeout=15,
        )

        response.raise_for_status()
        data = response.json()

        return data if isinstance(data, list) else []

    except Exception as e:
        log(f"Spot klines error for {symbol}: {e}")
        return []


def check_spot_bearish_divergence(
    symbol,
    tracked_since=None,
    current_time=None
):
    if not symbol or is_stock_symbol(symbol):
        return None

    if tracked_since is not None:
        if not is_divergence_monitor_active(
            tracked_since,
            current_time or datetime.now(timezone.utc),
            DIVERGENCE_HOURS,
        ):
            return None

    candles = fetch_spot_klines(symbol, interval="15m")

    if len(candles) < 30:
        return None

    closes = []

    for candle in candles:
        if not isinstance(candle, (list, tuple)) or len(candle) < 5:
            continue

        try:
            closes.append(float(candle[4]))
        except (TypeError, ValueError):
            continue

    if len(closes) < 30:
        return None

    rsi_values = calculate_rsi(closes, period=14)

    if len(rsi_values) < 6:
        return None

    divergence = detect_bearish_divergence(
        closes,
        rsi_values
    )

    if divergence is None:
        return None

    current_price = get_token_price(symbol, "mexc")

    if current_price is None:
        current_price = closes[-1]

    send_discord_bearish_divergence_alert(
        symbol,
        divergence,
        current_price
    )

    send_divergence_post_notification(
        symbol,
        divergence,
        current_price,
        timeframe="15m"
    )

    return divergence


# ============================================================
# NEW TOKEN POST NOTIFICATION
# ============================================================

def send_new_token_post_notification(
    token_name,
    initial_price,
    create_time,
    token_link,
    exchange="mexc",
):
    if is_stock_symbol(token_name):
        return False

    if not POST_URL:
        log("POST_URL not configured. Skipping notification.")
        return False

    payload = {
        "event": "new_token",
        "token_name": token_name,
        "initial_price": initial_price,
        "created_at": create_time.isoformat(),
        "token_link": token_link,
        "market": f"{exchange}_futures",
        "exchange": exchange,
    }

    try:
        response = requests.post(
            POST_URL,
            json=payload,
            timeout=15,
        )

        response.raise_for_status()

        log(
            f"{exchange.upper()} new-token POST sent "
            f"for {token_name}"
        )

        return True

    except Exception as e:
        log(f"New-token POST error for {token_name}: {e}")
        return False


# ============================================================
# DISCORD NEW TOKEN NOTIFICATION
# ============================================================

def send_discord_start_notification(
    token_name,
    initial_price,
    create_time,
    token_link,
    exchange="mexc",
):
    if is_stock_symbol(token_name):
        return False

    if not DISCORD_WEBHOOK_URL:
        log("DISCORD_WEBHOOK_URL not configured.")
        return False

    message = {
        "content": (
            f"🚨 **NEW {exchange.upper()} FUTURES TOKEN**\n\n"
            f"**Token:** `{token_name}`\n"
            f"**Exchange:** `{exchange.upper()}`\n"
            f"**Initial Price:** `{initial_price}`\n"
            f"**Created / Detected:** "
            f"`{format_aest_time(create_time)}`\n\n"
            f"🔗 <{token_link}>\n\n"
            f"⏱️ Tracking for {TRACKING_HOURS} hours..."
        )
    }

    try:
        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json=message,
            timeout=15,
        )

        response.raise_for_status()

        log(
            f"Discord notification sent for "
            f"{exchange.upper()} {token_name}"
        )

        return True

    except Exception as e:
        log(f"Discord notification error: {e}")
        return False


# ============================================================
# DISCORD DIVERGENCE ALERT
# ============================================================

def send_discord_bearish_divergence_alert(
    symbol,
    divergence_type,
    current_price
):
    if is_stock_symbol(symbol):
        return False

    if not DISCORD_WEBHOOK_URL:
        return False

    label = (
        divergence_type.upper()
        if divergence_type
        else "BEARISH"
    )

    message = {
        "content": (
            f"🚨 **SHORT SETUP: {label} DIVERGENCE**\n\n"
            f"**Token:** `{symbol}`\n"
            f"**Bias:** `Short`\n"
            f"**Market:** `MEXC Spot + Futures`\n"
            f"**Price:** `{current_price}`\n\n"
            f"**Reason:** Spot RSI bearish divergence detected "
            f"on an asset that recently listed on MEXC futures."
        )
    }

    try:
        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json=message,
            timeout=15,
        )

        response.raise_for_status()

        log(f"Discord divergence alert sent for {symbol}")
        return True

    except Exception as e:
        log(f"Divergence Discord error: {e}")
        return False


# ============================================================
# DIVERGENCE POST
# ============================================================

def send_divergence_post_notification(
    symbol,
    divergence_type,
    current_price,
    timeframe="15m"
):
    if is_stock_symbol(symbol):
        return False

    if not POST_URL:
        return False

    payload = {
        "event": "bearish_divergence",
        "token_name": symbol,
        "divergence_type": divergence_type,
        "timeframe": timeframe,
        "direction": "short",
        "current_price": current_price,
        "market": "spot + new futures listing",
        "exchange": "mexc",
    }

    try:
        response = requests.post(
            POST_URL,
            json=payload,
            timeout=15,
        )

        response.raise_for_status()

        log(f"Divergence POST sent for {symbol}")
        return True

    except Exception as e:
        log(f"Divergence POST error: {e}")
        return False


# ============================================================
# 8-HOUR PRICE CHANGE POST
# ============================================================

def post_price_change(
    token_name,
    initial_price,
    current_price,
    price_change,
    exchange="mexc",
):
    if is_stock_symbol(token_name):
        return False

    if not POST_URL:
        return False

    payload = {
        "token_name": token_name,
        "initial_price": initial_price,
        "current_price": current_price,
        "price_change": price_change,
        "exchange": exchange,
        "market": f"{exchange}_futures",
    }

    try:
        response = requests.post(
            POST_URL,
            json=payload,
            timeout=15,
        )

        response.raise_for_status()

        log(
            f"{exchange.upper()} price-change POST successful "
            f"for {token_name}"
        )

        return True

    except Exception as e:
        log(f"Price-change POST error for {token_name}: {e}")
        return False


# ============================================================
# CHECK TRACKED TOKENS
# ============================================================

def check_price_changes(tracked_tokens):
    current_time = datetime.now(timezone.utc)
    to_remove = []

    for tracking_key, data in list(tracked_tokens.items()):

        exchange = data.get("exchange", "mexc")
        token_name = data.get("symbol", tracking_key)

        if is_stock_symbol(token_name):
            to_remove.append(tracking_key)
            continue

        try:
            initial_time = datetime.fromisoformat(data["time"])

        except (KeyError, ValueError, TypeError) as e:
            log(f"Invalid tracking data for {tracking_key}: {e}")
            to_remove.append(tracking_key)
            continue

        # MEXC spot divergence monitoring only.
        if exchange == "mexc":

            divergence_alerted = data.get(
                "divergence_alerted",
                False
            )

            if (
                not divergence_alerted
                and is_divergence_monitor_active(
                    initial_time,
                    current_time,
                    DIVERGENCE_HOURS,
                )
            ):

                divergence = check_spot_bearish_divergence(
                    token_name,
                    initial_time,
                    current_time
                )

                if divergence:

                    data["divergence_alerted"] = True
                    data["divergence_signal"] = divergence

                    save_tracked_tokens(tracked_tokens)

                    log(
                        f"Divergence {divergence} detected "
                        f"for {token_name}"
                    )

        # 8-hour price tracking.
        if current_time >= initial_time + timedelta(
            hours=TRACKING_HOURS
        ):

            initial_price = data.get("price")

            if not initial_price:
                to_remove.append(tracking_key)
                continue

            current_price = get_token_price(
                token_name,
                exchange
            )

            if current_price is None:
                continue

            price_change = (
                (current_price - initial_price)
                / initial_price
            ) * 100

            log(
                f"{exchange.upper()} 8-hour result: "
                f"{token_name} | "
                f"Initial: {initial_price} | "
                f"Current: {current_price} | "
                f"Change: {price_change:.2f}%"
            )

            success = post_price_change(
                token_name,
                initial_price,
                current_price,
                price_change,
                exchange,
            )

            if success:
                to_remove.append(tracking_key)

    for tracking_key in to_remove:
        tracked_tokens.pop(tracking_key, None)

        log(f"Removed completed token: {tracking_key}")

    if to_remove:
        save_tracked_tokens(tracked_tokens)


# ============================================================
# MAIN EXCHANGE MONITOR
# ============================================================

def find_new_tokens():

    tracked_tokens = load_tracked_tokens()
    known_contracts = load_known_contracts()

    log(
        f"Loaded {len(tracked_tokens)} tracked tokens"
    )

    # --------------------------------------------------------
    # OURBIT INITIAL BASELINE
    # --------------------------------------------------------
    # Existing Ourbit contracts are recorded without alerts.
    # Subsequent newly appearing symbols trigger notifications.

    if "ourbit" not in known_contracts:

        ourbit_tokens = get_tokens("ourbit")

        if ourbit_tokens:

            known_contracts["ourbit"] = [
                token["symbol"]
                for token in ourbit_tokens
                if (
                    isinstance(token, dict)
                    and token.get("symbol")
                )
            ]

            save_known_contracts(known_contracts)

            log(
                f"OURBIT baseline established: "
                f"{len(known_contracts['ourbit'])} contracts"
            )

        else:
            log(
                "OURBIT baseline unavailable. "
                "Will retry next iteration."
            )

    # --------------------------------------------------------
    # MAIN LOOP
    # --------------------------------------------------------

    while True:

        current_time = datetime.now(timezone.utc)

        log("Starting exchange monitoring iteration")

        # Process both exchanges independently.
        for exchange in ("mexc", "ourbit"):

            tokens = get_tokens(exchange)

            if not tokens:
                log(
                    f"{exchange.upper()} returned no contracts. "
                    f"Skipping this iteration."
                )
                continue

            new_tokens_found = 0

            # Existing Ourbit symbols are stored persistently.
            known = set(
                known_contracts.get(exchange, [])
            )

            for token in tokens:

                if not isinstance(token, dict):
                    continue

                token_name = token.get("symbol")

                if not token_name:
                    continue

                if is_stock_symbol(token_name):
                    continue

                tracking_key = f"{exchange}:{token_name}"

                # ------------------------------------------------
                # MEXC DETECTION
                # ------------------------------------------------

                if exchange == "mexc":

                    create_time_ms = token.get(
                        "createTime",
                        0
                    )

                    if not create_time_ms:
                        continue

                    try:
                        create_time = datetime.fromtimestamp(
                            create_time_ms / 1000,
                            timezone.utc
                        )

                    except (
                        ValueError,
                        TypeError,
                        OverflowError
                    ):
                        continue

                    one_hour_ago = (
                        current_time - timedelta(hours=1)
                    )

                    if create_time < one_hour_ago:
                        continue

                # ------------------------------------------------
                # OURBIT DETECTION
                # ------------------------------------------------

                else:

                    # Ignore contracts already seen.
                    if token_name in known:
                        continue

                    # Ourbit detection timestamp.
                    # This is when our monitor first detects it,
                    # not necessarily the actual listing time.
                    create_time = current_time

                # ------------------------------------------------
                # DUPLICATE TRACKING CHECK
                # ------------------------------------------------

                if tracking_key in tracked_tokens:

                    known.add(token_name)
                    continue

                # ------------------------------------------------
                # INITIAL PRICE
                # ------------------------------------------------

                current_price = get_token_price(
                    token_name,
                    exchange
                )

                if current_price is None:
                    log(
                        f"Unable to obtain initial price for "
                        f"{exchange.upper()} {token_name}. "
                        f"Will retry."
                    )
                    continue

                token_link = get_contract_link(
                    exchange,
                    token_name
                )

                # ------------------------------------------------
                # SAVE TOKEN
                # ------------------------------------------------

                tracked_tokens[tracking_key] = {
                    "exchange": exchange,
                    "symbol": token_name,
                    "price": current_price,
                    "time": current_time.isoformat(),
                    "divergence_alerted": False,
                }

                known.add(token_name)

                log(
                    f"🚨 NEW {exchange.upper()} FUTURES TOKEN: "
                    f"{token_name} @ {current_price}"
                )

                log(f"Token link: {token_link}")

                save_tracked_tokens(tracked_tokens)

                # ------------------------------------------------
                # POST NOTIFICATION
                # ------------------------------------------------

                send_new_token_post_notification(
                    token_name,
                    current_price,
                    create_time,
                    token_link,
                    exchange,
                )

                # ------------------------------------------------
                # DISCORD NOTIFICATION
                # ------------------------------------------------

                send_discord_start_notification(
                    token_name,
                    current_price,
                    create_time,
                    token_link,
                    exchange,
                )

                new_tokens_found += 1

            # ----------------------------------------------------
            # SAVE OURBIT CONTRACT HISTORY
            # ----------------------------------------------------

            if exchange == "ourbit":
                known_contracts["ourbit"] = sorted(known)
                save_known_contracts(known_contracts)

            log(
                f"{exchange.upper()}: "
                f"Found {new_tokens_found} new contract(s)"
            )

        # --------------------------------------------------------
        # CHECK EXISTING TRACKED TOKENS
        # --------------------------------------------------------

        check_price_changes(tracked_tokens)

        log(
            f"Currently tracking "
            f"{len(tracked_tokens)} contract(s)"
        )

        log(f"Sleeping for {POLL_INTERVAL} seconds...")

        time.sleep(POLL_INTERVAL)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    log("Starting MEXC + OURBIT Futures Monitor")

    try:
        find_new_tokens()

    except KeyboardInterrupt:
        log("Monitor stopped manually.")

    except Exception as e:
        log(f"Fatal monitor error: {e}")
        raise
