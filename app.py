import os
import secrets

from dotenv import load_dotenv
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for

from chatbots import (
    VOCABULARY,
    TranslationError,
    contains_hanzi,
    lookup_words,
    meaning_is_pinyin,
    needs_pinyin_refresh,
    translate_text,
    translate_to_indonesian,
    translate_to_english,
    vocabulary_from_translation,
    pinyin_for_hanzi,
)
from models import Favorite, LearningEvent, Vocabulary, db

load_dotenv()

app = Flask(__name__)


def get_secret_key():
    configured_key = os.environ.get("SECRET_KEY")
    if configured_key:
        return configured_key

    os.makedirs(app.instance_path, exist_ok=True)
    key_path = os.path.join(app.instance_path, "flask_secret_key")
    try:
        with open(key_path, "x", encoding="utf-8") as key_file:
            key_file.write(secrets.token_hex(32))
    except FileExistsError:
        pass

    with open(key_path, encoding="utf-8") as key_file:
        secret_key = key_file.read().strip()
    if not secret_key:
        raise RuntimeError(f"Flask secret key file is empty: {key_path}")
    return secret_key


app.config.update(
    SECRET_KEY=get_secret_key(),
    SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///vocab.db"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=16 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
)
db.init_app(app)


@app.context_processor
def provide_csrf_token():
    def csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]

    return {"csrf_token": csrf_token}


def validate_csrf():
    submitted = request.form.get("csrf_token")
    if request.is_json:
        submitted = (request.get_json(silent=True) or {}).get("csrf_token")
    expected = session.get("csrf_token", "")
    if not submitted or not secrets.compare_digest(submitted, expected):
        abort(400, description="Invalid or missing CSRF token.")


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    return response


def seed_vocabulary():
    existing_words = {word.hanzi: word for word in Vocabulary.query.all()}
    for word in VOCABULARY:
        saved_word = existing_words.get(word["hanzi"])
        if saved_word is None:
            db.session.add(Vocabulary(**word))
        else:
            if needs_pinyin_refresh(saved_word.hanzi, saved_word.pinyin):
                saved_word.pinyin = word["pinyin"]
            if not saved_word.english:
                saved_word.english = word["english"]
    for saved_word in existing_words.values():
        if contains_hanzi(saved_word.hanzi) and needs_pinyin_refresh(
            saved_word.hanzi, saved_word.pinyin
        ):
            saved_word.pinyin = pinyin_for_hanzi(saved_word.hanzi)
    db.session.commit()


with app.app_context():
    db.create_all()
    vocabulary_columns = {
        column["name"] for column in db.inspect(db.engine).get_columns("vocabulary")
    }
    with db.engine.begin() as connection:
        if "pinyin" not in vocabulary_columns:
            connection.execute(db.text(
                "ALTER TABLE vocabulary ADD COLUMN pinyin VARCHAR(50) NOT NULL DEFAULT ''"
            ))
        if "english" not in vocabulary_columns:
            connection.execute(db.text(
                "ALTER TABLE vocabulary ADD COLUMN english VARCHAR(100) NOT NULL DEFAULT ''"
            ))

    seed_vocabulary()

    event_columns = {column["name"] for column in db.inspect(db.engine).get_columns("learning_event")}
    if "is_correct" not in event_columns:
        with db.engine.begin() as connection:
            connection.execute(db.text("ALTER TABLE learning_event ADD COLUMN is_correct BOOLEAN"))
    with db.engine.begin() as connection:
        connection.execute(db.text(
            "CREATE INDEX IF NOT EXISTS ix_learning_event_created_at "
            "ON learning_event (created_at)"
        ))


def get_vocabulary():
    vocabulary = [
        {
            "hanzi": word.hanzi,
            "pinyin": word.pinyin,
            "meaning": word.meaning,
            "english": word.english,
        }
        for word in Vocabulary.query.order_by(Vocabulary.id).all()
    ]
    if not vocabulary:
        seed_vocabulary()
        return get_vocabulary()
    return vocabulary


@app.route("/", methods=["GET", "POST"])
def index():
    matches = []
    query = ""
    vocabulary = get_vocabulary()
    if request.method == "POST":
        validate_csrf()
        query = request.form.get("message", "").strip()
        if not query or len(query) > 120:
            flash("Masukkan kata dengan panjang 1–120 karakter.", "error")
        else:
            matches = lookup_words(query, vocabulary)
            db.session.add(LearningEvent(
                search_text=query,
                matched_hanzi=matches[0]["hanzi"] if matches else None,
            ))
            db.session.commit()
            if not matches:
                flash(
                    "Kata belum ditemukan. Coba Hanzi, Pinyin, Indonesia, atau Inggris.",
                    "info",
                )

    view = request.args.get("view", "lookup")
    if view not in {"lookup", "practice", "saved", "history"}:
        view = "lookup"
    favorites = {item.hanzi for item in Favorite.query.all()}
    saved_words = [word for word in vocabulary if word["hanzi"] in favorites]
    history = LearningEvent.query.order_by(LearningEvent.created_at.desc()).limit(12).all()
    total_reviews = LearningEvent.query.filter(LearningEvent.is_correct.isnot(None)).count()
    correct_count = LearningEvent.query.filter_by(is_correct=True).count()
    return render_template(
        "index.html",
        vocabulary=vocabulary,
        matches=matches,
        query=query,
        favorites=favorites,
        saved_words=saved_words,
        history=history,
        total_reviews=total_reviews,
        accuracy=round(correct_count / total_reviews * 100) if total_reviews else 0,
        active_view=view,
    )


@app.post("/translate")
def translate():
    validate_csrf()
    text = request.form.get("text", "").strip()
    if not text or len(text) > 500:
        flash("Masukkan teks sepanjang 1–500 karakter.", "error")
        return redirect(url_for("index", view="lookup"))

    try:
        translated = translate_text(text)
        if contains_hanzi(text):
            hanzi = text
            meaning = translated
        else:
            hanzi = translated
            meaning = translate_to_indonesian(hanzi)
        english = translate_to_english(hanzi)
    except TranslationError as error:
        flash(str(error), "error")
    else:
        word = vocabulary_from_translation(hanzi, meaning, english)
        if word is None:
            flash(f"Hasil terjemahan: {translated}", "success")
            flash("Kosakata tidak muat di kamus.", "info")
        else:
            existing = Vocabulary.query.filter_by(hanzi=word["hanzi"]).first()
            if existing:
                changed = False
                if needs_pinyin_refresh(existing.hanzi, existing.pinyin):
                    existing.pinyin = word["pinyin"]
                    changed = True
                if not existing.meaning or meaning_is_pinyin(existing.hanzi, existing.meaning):
                    existing.meaning = word["meaning"]
                    changed = True
                if not existing.english:
                    existing.english = word["english"]
                    changed = True
                if changed:
                    db.session.commit()
                    flash(
                        f"Hasil terjemahan: {translated} "
                        "(keterangan kamus diperbarui)",
                        "success",
                    )
                else:
                    flash(
                        f"Hasil terjemahan: {translated} "
                        "(sudah ada di kamus)",
                        "success",
                    )
            else:
                db.session.add(Vocabulary(**word))
                db.session.commit()
                flash(
                    f"Hasil terjemahan: {translated} (disimpan di kamus)",
                    "success",
                )
    return redirect(url_for("index", view="lookup"))


@app.post("/favorite/<hanzi>")
def toggle_favorite(hanzi):
    validate_csrf()
    if not Vocabulary.query.filter_by(hanzi=hanzi).first():
        abort(404)
    favorite = Favorite.query.filter_by(hanzi=hanzi).first()
    if favorite:
        db.session.delete(favorite)
    else:
        db.session.add(Favorite(hanzi=hanzi))
    db.session.commit()
    view = request.form.get("view", "lookup")
    return redirect(url_for("index", view=view))


@app.post("/practice/answer")
def record_practice_answer():
    validate_csrf()
    data = request.get_json(silent=True) or {}
    hanzi = data.get("hanzi", "")
    if not Vocabulary.query.filter_by(hanzi=hanzi).first():
        abort(400, description="Unknown vocabulary item.")
    is_correct = data.get("correct") is True
    db.session.add(LearningEvent(
        search_text="quiz",
        matched_hanzi=hanzi,
        is_correct=is_correct,
    ))
    db.session.commit()
    total_reviews = LearningEvent.query.filter(LearningEvent.is_correct.isnot(None)).count()
    correct_count = LearningEvent.query.filter_by(is_correct=True).count()
    return jsonify({
        "saved": True,
        "total_reviews": total_reviews,
        "accuracy": round(correct_count / total_reviews * 100) if total_reviews else 0,
    }), 201

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
