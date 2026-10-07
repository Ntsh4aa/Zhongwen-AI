import os
import secrets

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for

from chatbots import (
    VOCABULARY,
    OllamaError,
    generate_vocabulary,
    lookup_words,
    lookup_with_ollama,
)
from models import Favorite, LearningEvent, Vocabulary, db

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
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

    for word in VOCABULARY:
        saved_word = Vocabulary.query.filter_by(hanzi=word["hanzi"]).first()
        if saved_word is None:
            db.session.add(Vocabulary(**word))
        else:
            if not saved_word.pinyin:
                saved_word.pinyin = word["pinyin"]
            if not saved_word.english:
                saved_word.english = word["english"]
    db.session.commit()

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
    return [
        {
            "hanzi": word.hanzi,
            "pinyin": word.pinyin,
            "meaning": word.meaning,
            "english": word.english,
        }
        for word in Vocabulary.query.order_by(Vocabulary.id).all()
    ]


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
            if not matches:
                try:
                    generated_matches = lookup_with_ollama(query)
                    matches = [
                        word for word in generated_matches
                        if not Vocabulary.query.filter_by(hanzi=word["hanzi"]).first()
                    ]
                    for word in matches:
                        db.session.add(Vocabulary(**word))
                    if matches:
                        db.session.commit()
                        vocabulary = get_vocabulary()
                except OllamaError as error:
                    flash(f"Pencarian AI gagal: {error}", "error")
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
        vocabulary=VOCABULARY,
        matches=matches,
        query=query,
        favorites=favorites,
        saved_words=saved_words,
        history=history,
        total_reviews=total_reviews,
        accuracy=round(correct_count / total_reviews * 100) if total_reviews else 0,
        active_view=view,
    )


@app.post("/vocabulary/generate")
def create_vocabulary():
    validate_csrf()
    topic = request.form.get("topic", "").strip()
    count_value = request.form.get("count", "10")
    if not topic or len(topic) > 80:
        flash("Masukkan topik sepanjang 1–80 karakter.", "error")
        return redirect(url_for("index", view="lookup"))
    try:
        count = int(count_value)
    except ValueError:
        count = 0
    if not 1 <= count <= 20:
        flash("Jumlah kosakata harus antara 1 dan 20.", "error")
        return redirect(url_for("index", view="lookup"))

    try:
        words = generate_vocabulary(topic, count)
    except OllamaError as error:
        flash(f"Pembuatan kosakata AI gagal: {error}", "error")
        return redirect(url_for("index", view="lookup"))

    existing_hanzi = {word.hanzi for word in Vocabulary.query.all()}
    new_words = [word for word in words if word["hanzi"] not in existing_hanzi]
    for word in new_words:
        existing_hanzi.add(word["hanzi"])
        db.session.add(Vocabulary(**word))
    db.session.commit()
    flash(f"{len(new_words)} kosakata baru ditambahkan untuk topik “{topic}”.", "success")
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
