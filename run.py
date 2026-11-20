"""Start the site locally:  .venv\Scripts\python run.py"""
import os

from server.app import ENV_CREATED, app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    if ENV_CREATED:
        print("\nFirst run: created .env with a random admin password (see ADMIN_PASSWORD in that file).")
    print(f"\n  Site:   http://localhost:{port}\n  Admin:  http://localhost:{port}/admin\n")
    app.run(host="127.0.0.1", port=port, debug=os.environ.get("DEBUG") == "1")
