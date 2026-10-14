# Lin Mandarin Studio

A small Flask-based Chinese vocabulary and practice app. It supports lookup by Hanzi, Pinyin (with or without tone marks), Indonesian, and English; saved vocabulary; recent lookup history; flashcards; a multiple-choice quiz; and Mandarin–Indonesian translation. The bundled lexicon seeds a local database. Translation uses `googletrans==4.0.0-rc1` and requires an internet connection.

## Run locally on Windows

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000. Dictionary search, flashcards, and quizzes run locally. Translation requires an internet connection and does not need an API key.

## Translation

Enter Hanzi, Pinyin, Indonesian, or English. New dictionary entries are saved with tone-marked Pinyin and Indonesian and English meanings. Translation is provided by the unofficial Google Translate client; network or service failures are shown in the app.

New Mandarin words are saved with tone-marked Pinyin and Indonesian and English meanings.

On Python 3.13 and newer, `legacy-cgi` is installed as a compatibility dependency for the pinned Google Translate client.

## Configuration

- `SECRET_KEY`: set a stable, random secret for sessions in any persistent deployment. If unset for local use, the app creates and reuses `instance/flask_secret_key` so sessions survive restarts.
- `DATABASE_URL`: optional SQLAlchemy URL; defaults to the existing SQLite database in `instance/vocab.db`.
- `COOKIE_SECURE=1`: enable secure-only session cookies when serving over HTTPS.
- `FLASK_DEBUG=1`: enable Flask debug mode for local development only.

The startup schema setup preserves the original `vocabulary` table and upgrades the existing history table additively. Back up the SQLite file before deployment. For multi-user deployments, use a managed database, formal Alembic migrations, per-user records, and a production secret manager.

## Production server

Install dependencies, set `SECRET_KEY`, and run the cross-platform Waitress server:

```powershell
$env:SECRET_KEY = "replace-with-a-long-random-value"
waitress-serve --host=127.0.0.1 app:app
```

Place a TLS-terminating reverse proxy in front of the app for public access and set `COOKIE_SECURE=1`.

## Tests

```powershell
python -m unittest discover -s tests -v
```
