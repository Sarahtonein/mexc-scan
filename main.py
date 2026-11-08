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
    # OURBIT + BINGX INITIAL BASELINES
    # --------------------------------------------------------
    # Existing contracts are recorded without alerts. Newly
    # appearing symbols are detected on subsequent iterations.

    for baseline_exchange in ("ourbit", "bingx"):
        if baseline_exchange not in known_contracts:
            baseline_tokens = get_tokens(baseline_exchange)

            if baseline_tokens:
                known_contracts[baseline_exchange] = [
                    token["symbol"]
                    for token in baseline_tokens
                    if isinstance(token, dict) and token.get("symbol")
                ]
                save_known_contracts(known_contracts)
                log(
                    f"{baseline_exchange.upper()} baseline established: "
                    f"{len(known_contracts[baseline_exchange])} contracts"
                )
            else:
                log(
                    f"{baseline_exchange.upper()} baseline unavailable. "
                    "Will retry next iteration."
                )

    # --------------------------------------------------------
    # MAIN LOOP
    # --------------------------------------------------------

    while True:

        current_time = datetime.now(timezone.utc)

        log("Starting exchange monitoring iteration")

        # Process each exchange independently.
        for exchange in ("mexc", "ourbit", "bingx"):

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
