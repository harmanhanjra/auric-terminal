import os

os.environ["MARKET_DATA_SOURCE"] = "web"
os.environ["TWELVE_DATA_API_KEY"] = ""
os.environ["ENABLE_LIVE_TRADING"] = "false"
os.environ["MAX_LOT"] = "1.0"
os.environ["MAX_DAILY_LOSS"] = "500.0"

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
