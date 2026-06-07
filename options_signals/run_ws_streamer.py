"""
Run the Upstox WebSocket price streamer as a background process.

Usage:
    python run_ws_streamer.py [--instruments NSE_INDEX|Nifty 50,...]

Prices are written to the local store (ws_prices key) and read by ws_client.py.
Run this in a separate terminal alongside the Streamlit app.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from data.ws_streamer import main

if __name__ == "__main__":
    main()
