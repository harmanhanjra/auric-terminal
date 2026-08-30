from dotenv import load_dotenv
load_dotenv()
import uvicorn
uvicorn.run('server:app', host='127.0.0.1', port=8000, log_level='info')
