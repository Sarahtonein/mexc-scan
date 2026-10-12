import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from collections import deque
import random
import time

# ---- Settings ----
MAX_CANDLES = 120
BASE_PRICE = 100.0

prices = deque([BASE_PRICE], maxlen=MAX_CANDLES)
times = deque([0], maxlen=MAX_CANDLES)

# ---- Price generator (random walk with drift) ----
def next_price(last):
    drift = 0.02
    volatility = 0.8
    change = drift + random.uniform(-volatility, volatility)
    return max(1, last + change)

# ---- Figure ----
fig, ax = plt.subplots()

def update(frame):
    last_price = prices[-1]
    new_price = next_price(last_price)

    prices.append(new_price)
    times.append(times[-1] + 1)

    ax.clear()

    ax.plot(times, prices, linewidth=1.5)
    ax.set_title("Live Market Simulation (Runs Until Closed)")
    ax.set_xlabel("Time")
    ax.set_ylabel("Price")

    # keep chart visually stable
    ax.set_ylim(min(prices) * 0.98, max(prices) * 1.02)

    ax.grid(True)

# ---- Animation loop (THIS is what keeps it running) ----
ani = animation.FuncAnimation(
    fig,
    update,
    interval=100,   # ms between updates (10 ticks/sec)
    cache_frame_data=False
)

plt.show()