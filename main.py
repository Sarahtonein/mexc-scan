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


def send_discord_start_notification(
    token_name,
    initial_price,
    create_time,
    token_link
):
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
            f"**Initial Price:** `{initial_price}`\n"
            f"**Created:** `{create_time.isoformat()}`\n\n"
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


def post_price_change(
    token_name,
    initial_price,
    current_price,
    price_change
):
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
