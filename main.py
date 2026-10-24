import requests
import time
import json
import os
from datetime import datetime, timedelta, timezone

GET_URL = "https://contract.mexc.com/api/v1/contract/detail"
PRICE_URL = "https://contract.mexc.com/api/v1/contract/ticker?symbol={}"

POST_URL = os.getenv("POST_URL")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

TRACKED_TOKENS_FILE = "tracked_tokens.json"
AEST = timezone(timedelta(hours=10))


def is_stock_symbol(symbol):
    if not isinstance(symbol, str):
        return False
    return "STOCK" in symbol.upper()


def format_aest_time(value):
    if value is None:
        return "Unknown"

    if isinstance(value, str):
        value = datetime.fromisoformat(value)

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(AEST).strftime("%Y-%m-%d %H:%M:%S AEST")


def is_divergence_monitor_active(tracked_at, current_time=None, window_hours=48):
    if current_time is None:
        current_time = datetime.now(timezone.utc)

    if isinstance(tracked_at, str):
        tracked_at = datetime.fromisoformat(tracked_at)

    if tracked_at.tzinfo is None:
        tracked_at = tracked_at.replace(tzinfo=timezone.utc)

    return (current_time - tracked_at) < timedelta(hours=window_hours)


def load_tracked_tokens():
    try:
        with open(TRACKED_TOKENS_FILE, "r") as file:
            content = file.read().strip()

            if content:
                return json.loads(content)

            return {}

    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"Error loading tracked tokens: {e}",
            flush=True
        )
        return {}


def save_tracked_tokens(tokens):
    try:
        with open(TRACKED_TOKENS_FILE, "w") as file:
            json.dump(tokens, file, indent=4)

    except Exception as e:
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"Error saving tokens to file: {e}",
            flush=True
        )


def get_tokens():
    try:
        response = requests.get(GET_URL, timeout=15)
        response.raise_for_status()

        data = response.json()

        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"MEXC response type: {type(data).__name__}",
            flush=True
        )

        if isinstance(data, dict):
            print(
                f"[{datetime.now(timezone.utc).isoformat()}] "
                f"MEXC response keys: {list(data.keys())}",
                flush=True
            )

        tokens = data if isinstance(data, list) else data.get("data", [])

        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"Parsed {len(tokens)} tokens",
            flush=True
        )

        return tokens

    except requests.RequestException as e:
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"Error fetching tokens: {e}",
            flush=True
        )
        return []

    except Exception as e:
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"Unexpected error parsing MEXC response: {e}",
            flush=True
        )
        return []


def get_token_price(symbol):
    try:
        response = requests.get(
            PRICE_URL.format(symbol),
            timeout=15
        )
        response.raise_for_status()

        data = response.json()

        if isinstance(data, dict):
            ticker_data = data.get("data", data)

            if isinstance(ticker_data, dict):
                price = ticker_data.get("lastPrice")
            else:
                price = None
        else:
            price = None

        if price is None:
            print(
                f"[{datetime.now(timezone.utc).isoformat()}] "
                f"No price returned for {symbol}: {data}",
                flush=True
            )
            return None

        return float(price)

    except requests.RequestException as e:
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"Error fetching price for {symbol}: {e}",
            flush=True
        )
        return None

    except (ValueError, TypeError) as e:
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"Invalid price for {symbol}: {e}",
            flush=True
        )
        return None

    except Exception as e:
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"Unexpected price error for {symbol}: {e}",
            flush=True
        )
        return None


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

        avg_gain = ((avg_gain * (period - 1)) + gains[index]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[index]) / period

    if len(rsi_values) < len(closes):
        while len(rsi_values) < len(closes):
            rsi_values.append(rsi_values[-1])

    return rsi_values[:len(closes)]


def detect_bearish_divergence(prices, rsi_values):
    if len(prices) < 6 or len(rsi_values) < 6:
        return None

    earlier_prices = prices[:-3]
    later_prices = prices[-3:]
    earlier_rsi = rsi_values[:-3]
    later_rsi = rsi_values[-3:]

    earlier_price_high = max(earlier_prices)
    later_price_high = max(later_prices)
    earlier_rsi_high = max(earlier_rsi)
    later_rsi_high = max(later_rsi)

    if later_price_high > earlier_price_high and later_rsi_high < earlier_rsi_high:
        return "regular"

    earlier_price_low = min(earlier_prices)
    later_price_low = min(later_prices)
    earlier_rsi_low = min(earlier_rsi)
    later_rsi_low = min(later_rsi)

    if later_price_low < earlier_price_low and later_rsi_low > earlier_rsi_low:
        return "hidden"

    return None


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

        if not isinstance(data, list):
            print(
                f"[{datetime.now(timezone.utc).isoformat()}] "
                f"Unexpected spot klines response for {symbol}: {data}",
                flush=True,
            )
            return []

        return data

    except requests.RequestException as e:
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"Error fetching spot klines for {symbol}: {e}",
            flush=True,
        )
        return []


def check_spot_bearish_divergence(symbol, tracked_since=None, current_time=None):
    if not symbol or is_stock_symbol(symbol):
        return None

    if tracked_since is not None and not is_divergence_monitor_active(
        tracked_since,
        current_time or datetime.now(timezone.utc),
    ):
        return None

    candles = fetch_spot_klines(symbol)
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

    divergence = detect_bearish_divergence(closes, rsi_values)
    if divergence is None:
        return None

    current_price = get_token_price(symbol)
    if current_price is None:
        current_price = closes[-1]

    send_discord_bearish_divergence_alert(symbol, divergence, current_price)
    return divergence


def send_discord_start_notification(
    token_name,
    initial_price,
    create_time,
    token_link
):
    if is_stock_symbol(token_name):
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"Ignoring stock ticker for Discord notification: {token_name}",
            flush=True
        )
        return False

    if not DISCORD_WEBHOOK_URL:
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"DISCORD_WEBHOOK_URL is not configured. "
            f"Skipping Discord notification.",
            flush=True
        )
        return False

    message = {
        "content": (
            f"🚨 **NEW MEXC FUTURES TOKEN**\n\n"
            f"**Token:** `{token_name}`\n"
            f"**Created:** `{format_aest_time(create_time)}`\n\n"
            f"🔗 <{token_link}>\n\n"
            f"⏱️ Tracking for 8 hours..."
        )
    }

    try:
        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json=message,
            timeout=15
        )

        response.raise_for_status()

        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"Discord notification sent for {token_name}",
            flush=True
        )

        return True

    except requests.RequestException as e:
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"Error sending Discord notification for "
            f"{token_name}: {e}",
            flush=True
        )
        return False


def send_discord_bearish_divergence_alert(symbol, divergence_type, current_price):
    if is_stock_symbol(symbol):
        return False

    if not DISCORD_WEBHOOK_URL:
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"DISCORD_WEBHOOK_URL is not configured. "
            f"Skipping bearish divergence alert for {symbol}",
            flush=True,
        )
        return False

    label = divergence_type.upper() if divergence_type else "BEARISH"
    message = {
        "content": (
            f"🚨 **SHORT SETUP: {label} DIVERGENCE**\n\n"
            f"**Token:** `{symbol}`\n"
            f"**Bias:** `Short`\n"
            f"**Market:** `Spot + new futures listing`\n"
            f"**Price:** `{current_price}`\n\n"
            f"**Reason:** spot RSI bearish divergence detected on an asset that also recently listed on MEXC futures."
        )
    }

    try:
        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json=message,
            timeout=15,
        )
        response.raise_for_status()
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"Discord bearish divergence alert sent for {symbol}",
            flush=True,
        )
        return True
    except requests.RequestException as e:
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"Error sending divergence alert for {symbol}: {e}",
            flush=True,
        )
        return False


def post_price_change(
    token_name,
    initial_price,
    current_price,
    price_change
):
    if is_stock_symbol(token_name):
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"Ignoring stock ticker for POST: {token_name}",
            flush=True
        )
        return False

    if not POST_URL:
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"POST_URL is not configured. "
            f"Skipping POST for {token_name}",
            flush=True
        )
        return False

    payload = {
        "token_name": token_name,
        "initial_price": initial_price,
        "current_price": current_price,
        "price_change": price_change,
    }

    try:
        response = requests.post(
            POST_URL,
            json=payload,
            timeout=15
        )

        response.raise_for_status()

        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"POST successful for {token_name}: "
            f"{response.status_code}",
            flush=True
        )

        return True

    except requests.RequestException as e:
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"Error sending POST request for {token_name}: {e}",
            flush=True
        )
        return False


def check_price_changes(tracked_tokens):
    current_time = datetime.now(timezone.utc)
    to_remove = []

    for token_name, data in list(tracked_tokens.items()):

        if is_stock_symbol(token_name):
            print(
                f"[{datetime.now(timezone.utc).isoformat()}] "
                f"Ignoring stock ticker in tracking check: {token_name}",
                flush=True
            )
            to_remove.append(token_name)
            continue

        try:
            initial_time = datetime.fromisoformat(data["time"])

        except (KeyError, ValueError, TypeError) as e:

            print(
                f"[{datetime.now(timezone.utc).isoformat()}] "
                f"Invalid tracking data for {token_name}: {e}",
                flush=True
            )

            to_remove.append(token_name)
            continue

        divergence_alerted = data.get("divergence_alerted", False)
        if not divergence_alerted and is_divergence_monitor_active(
            initial_time,
            current_time,
            window_hours=48,
        ):
            divergence = check_spot_bearish_divergence(token_name, initial_time, current_time)
            if divergence:
                data["divergence_alerted"] = True
                data["divergence_signal"] = divergence
                print(
                    f"[{datetime.now(timezone.utc).isoformat()}] "
                    f"Divergence signal {divergence} alert armed for {token_name}",
                    flush=True,
                )
                save_tracked_tokens(tracked_tokens)

        if current_time >= initial_time + timedelta(hours=8):

            initial_price = data.get("price")

            if not initial_price:

                print(
                    f"[{datetime.now(timezone.utc).isoformat()}] "
                    f"Invalid initial price for {token_name}",
                    flush=True
                )

                to_remove.append(token_name)
                continue

            current_price = get_token_price(token_name)

            if current_price is not None:

                price_change = (
                    (current_price - initial_price)
                    / initial_price
                ) * 100

                print(
                    f"[{datetime.now(timezone.utc).isoformat()}] "
                    f"8-hour result: "
                    f"{token_name} | "
                    f"Initial: {initial_price} | "
                    f"Current: {current_price} | "
                    f"Change: {price_change:.2f}%",
                    flush=True
                )

                success = post_price_change(
                    token_name,
                    initial_price,
                    current_price,
                    price_change
                )

                if success:
                    to_remove.append(token_name)

    for token_name in to_remove:

        if token_name in tracked_tokens:

            del tracked_tokens[token_name]

            print(
                f"[{datetime.now(timezone.utc).isoformat()}] "
                f"Removed completed token: {token_name}",
                flush=True
            )

    if to_remove:
        save_tracked_tokens(tracked_tokens)


def find_new_tokens():

    tracked_tokens = load_tracked_tokens()

    print(
        f"[{datetime.now(timezone.utc).isoformat()}] "
        f"Loaded {len(tracked_tokens)} tracked tokens",
        flush=True
    )

    while True:

        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"Starting new iteration",
            flush=True
        )

        tokens = get_tokens()

        if not tokens:

            print(
                f"[{datetime.now(timezone.utc).isoformat()}] "
                f"MEXC returned no tokens",
                flush=True
            )

        else:

            current_time = datetime.now(timezone.utc)
            one_hour_ago = current_time - timedelta(hours=1)

            new_tokens_found = 0
            recently_created = 0

            for token in tokens:

                if not isinstance(token, dict):

                    print(
                        f"Unexpected token format: {token}",
                        flush=True
                    )
                    continue

                create_time_ms = token.get("createTime", 0)

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
                ) as e:

                    print(
                        f"[{datetime.now(timezone.utc).isoformat()}] "
                        f"Invalid createTime: {e}",
                        flush=True
                    )
                    continue

                if create_time >= one_hour_ago:

                    recently_created += 1

                    token_name = token.get("symbol")

                    if not token_name:
                        continue

                    if is_stock_symbol(token_name):
                        print(
                            f"[{datetime.now(timezone.utc).isoformat()}] "
                            f"Ignoring stock ticker: {token_name}",
                            flush=True
                        )
                        continue

                    token_link = (
                        "https://futures.mexc.com/exchange/"
                        f"{token_name}?type=linear_swap"
                    )

                    if token_name not in tracked_tokens:

                        current_price = get_token_price(token_name)

                        if current_price is not None:

                            tracked_tokens[token_name] = {
                                "price": current_price,
                                "time": current_time.isoformat(),
                                "divergence_alerted": False,
                            }

                            print(
                                f"[{datetime.now(timezone.utc).isoformat()}] "
                                f"🚨 Tracking new token: "
                                f"{token_name} "
                                f"at price {current_price}",
                                flush=True
                            )

                            print(
                                f"Token link: {token_link}",
                                flush=True
                            )

                            save_tracked_tokens(tracked_tokens)

                            send_discord_start_notification(
                                token_name,
                                current_price,
                                create_time,
                                token_link
                            )

                            new_tokens_found += 1

            print(
                f"[{datetime.now(timezone.utc).isoformat()}] "
                f"Recently created tokens "
                f"(last hour): {recently_created}",
                flush=True
            )

            if new_tokens_found == 0:

                print(
                    f"[{datetime.now(timezone.utc).isoformat()}] "
                    f"No new tokens found",
                    flush=True
                )

            else:

                print(
                    f"[{datetime.now(timezone.utc).isoformat()}] "
                    f"Found and tracking "
                    f"{new_tokens_found} new token(s)",
                    flush=True
                )

        check_price_changes(tracked_tokens)

        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"Currently tracking "
            f"{len(tracked_tokens)} token(s)",
            flush=True
        )

        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"Sleeping for 25 seconds...",
            flush=True
        )

        time.sleep(25)


if __name__ == "__main__":
    find_new_tokens()
