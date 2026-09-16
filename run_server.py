import os
from dotenv import load_dotenv
load_dotenv()
import uvicorn
# PORT/AURIC_PORT let launchers and the Electron shell pick a free port.
port = int(os.getenv("PORT", os.getenv("AURIC_PORT", "8000")))
uvicorn.run('server:app', host='127.0.0.1', port=port, log_level='info')
