"""AI SEO Autopilot - Production entry point."""
import os
import sys

# Ensure project root is on path
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from app import create_app

if __name__ == "__main__":
    app = create_app()
    host = os.environ.get("APP_HOST", "127.0.0.1")
    port = int(os.environ.get("APP_PORT", "5000"))
    debug = os.environ.get("APP_DEBUG", "1") == "1"
    print(f"\n  AI SEO Autopilot running at http://{host}:{port}\n")
    app.run(host=host, port=port, debug=debug, use_reloader=False)
