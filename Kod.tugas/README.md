# Lin Mandarin Studio

A small Flask-based Chinese vocabulary and practice app. It supports lookup by Hanzi, Pinyin (with or without tone marks), Indonesian, and English; saved vocabulary; recent lookup history; flashcards; and a multiple-choice quiz. Ollama can complete vocabulary searches that miss the local dictionary and generate new vocabulary lists by topic. AI-generated entries are saved to the app database and become available in search, favorites, flashcards, and quizzes.

## Run locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000. The bundled lexicon is used to seed the local database. Ollama-generated translations can be inaccurate, so review AI-generated entries before relying on them.

## Ollama configuration

For local Ollama, install and start Ollama, then download the default model:

```powershell
ollama pull qwen2.5:3b
$env:OLLAMA_BASE_URL = "http://localhost:11434"
$env:OLLAMA_MODEL = "qwen2.5:3b"
python app.py
```

To use an Ollama-compatible hosted endpoint, set its URL, model, and token instead:

```powershell
$env:OLLAMA_BASE_URL = "https://ollama.com"
$env:OLLAMA_MODEL = "your-model-name"
$env:OLLAMA_API_KEY = "replace-with-your-token"
python app.py
```

`OLLAMA_API_KEY` is optional for a local Ollama server. The app reads it from the environment and sends it as a bearer token; never put a real token in source code or commit it. `OLLAMA_BASE_URL` defaults to `http://localhost:11434`, and `OLLAMA_MODEL` defaults to `qwen2.5:3b`. Set these variables in the same PowerShell session used to run the app.

## Configuration

- `SECRET_KEY`: set a stable, random secret for sessions in any persistent deployment.
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
