import os
import sys

# Ensure project root is on sys.path for serverless imports
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Import the FastAPI ASGI app
from app.main import app

# Expose app for Vercel Serverless Function runtime
__all__ = ["app"]
