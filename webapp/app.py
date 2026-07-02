"""Entrypoint. All routes live in blueprints; the app is assembled by create_app().

    python webapp/app.py            # dev server on :5001
    gunicorn "webapp:create_app()"  # or a WSGI server
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webapp import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", "5057")))
