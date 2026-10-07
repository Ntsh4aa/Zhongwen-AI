from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Vocabulary(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    hanzi = db.Column(db.String(20), nullable=False)
    pinyin = db.Column(db.String(50), nullable=False, default="")
    meaning = db.Column(db.String(120), nullable=False)
    english = db.Column(db.String(100), nullable=False, default="")


class Favorite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    hanzi = db.Column(db.String(20), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class LearningEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    search_text = db.Column("query", db.String(120), nullable=False)
    matched_hanzi = db.Column(db.String(20))
    is_correct = db.Column(db.Boolean)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
