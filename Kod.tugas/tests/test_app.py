import os
import unittest
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite://"

from app import app, db
from chatbots import chatbot_response, generate_vocabulary, lookup_words
from models import Favorite, LearningEvent, Vocabulary


class LookupTests(unittest.TestCase):
    def test_lookup_accepts_hanzi_pinyin_and_meanings(self):
        self.assertEqual(lookup_words("水")[0]["pinyin"], "shuǐ")
        self.assertEqual(lookup_words("shui")[0]["hanzi"], "水")
        self.assertEqual(lookup_words("apa kabar")[0]["hanzi"], "你好")
        self.assertEqual(lookup_words("water")[0]["hanzi"], "水")

    def test_tone_marks_are_optional_and_ambiguous_pinyin_is_preserved(self):
        self.assertEqual(lookup_words("nǐ hǎo"), lookup_words("ni hao"))
        self.assertEqual({word["hanzi"] for word in lookup_words("tā")}, {"他", "她"})

    def test_legacy_chatbot_entry_point_remains_available(self):
        self.assertIn("你好", chatbot_response("hello"))
        self.assertIn("Belum ada", chatbot_response("unknown phrase"))

    def test_generated_vocabulary_filters_invalid_entries(self):
        with patch("chatbots._ollama_json", return_value={
            "words": [
                {"hanzi": "苹果", "pinyin": "píng guǒ", "meaning": "apel", "english": "apple"},
                {"hanzi": "not hanzi", "pinyin": "bad", "meaning": "tidak valid", "english": "invalid"},
            ],
        }):
            self.assertEqual(generate_vocabulary("makanan", 1), [{
                "hanzi": "苹果",
                "pinyin": "píng guǒ",
                "meaning": "apel",
                "english": "apple",
            }])


class AppTests(unittest.TestCase):
    def setUp(self):
        self.context = app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        self.client = app.test_client()
        self.client.get("/")
        with self.client.session_transaction() as session:
            self.csrf_token = session["csrf_token"]

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def test_all_views_render(self):
        for view in ("lookup", "practice", "saved", "history"):
            with self.subTest(view=view):
                self.assertEqual(self.client.get(f"/?view={view}").status_code, 200)

    def test_lookup_is_recorded_and_history_uses_legacy_column(self):
        response = self.client.post("/", data={"csrf_token": self.csrf_token, "message": "water"})
        self.assertEqual(response.status_code, 200)
        event = LearningEvent.query.one()
        self.assertEqual(event.search_text, "water")
        self.assertEqual(event.matched_hanzi, "水")

    def test_unknown_lookup_uses_ai_and_saves_the_word(self):
        with patch("app.lookup_with_ollama", return_value=[{
            "hanzi": "苹果",
            "pinyin": "píng guǒ",
            "meaning": "apel",
            "english": "apple",
        }]):
            response = self.client.post(
                "/",
                data={"csrf_token": self.csrf_token, "message": "apple"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("苹果".encode(), response.data)
        self.assertEqual(Vocabulary.query.filter_by(hanzi="苹果").one().meaning, "apel")

    def test_generated_vocabulary_is_saved_and_can_be_favorited(self):
        with patch("app.generate_vocabulary", return_value=[{
            "hanzi": "苹果",
            "pinyin": "píng guǒ",
            "meaning": "apel",
            "english": "apple",
        }]):
            response = self.client.post("/vocabulary/generate", data={
                "csrf_token": self.csrf_token,
                "topic": "makanan",
                "count": "5",
            })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Vocabulary.query.filter_by(hanzi="苹果").count(), 1)
        favorite_response = self.client.post(
            "/favorite/苹果",
            data={"csrf_token": self.csrf_token},
        )
        self.assertEqual(favorite_response.status_code, 302)
        self.assertEqual(Favorite.query.filter_by(hanzi="苹果").count(), 1)

    def test_favorites_toggle_and_saved_view(self):
        response = self.client.post("/favorite/水", data={"csrf_token": self.csrf_token, "view": "saved"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Favorite.query.count(), 1)
        self.assertIn("水".encode(), self.client.get("/?view=saved").data)
        self.client.post("/favorite/水", data={"csrf_token": self.csrf_token})
        self.assertEqual(Favorite.query.count(), 0)

    def test_quiz_records_accuracy_and_rejects_unknown_words(self):
        response = self.client.post("/practice/answer", json={
            "csrf_token": self.csrf_token,
            "hanzi": "水",
            "correct": True,
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["total_reviews"], 1)
        self.assertEqual(response.json["accuracy"], 100)
        self.assertTrue(LearningEvent.query.one().is_correct)
        invalid = self.client.post("/practice/answer", json={
            "csrf_token": self.csrf_token,
            "hanzi": "不存在",
            "correct": True,
        })
        self.assertEqual(invalid.status_code, 400)

    def test_mutations_require_csrf_and_response_has_security_headers(self):
        self.assertEqual(self.client.post("/favorite/水").status_code, 400)
        response = self.client.get("/")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")


if __name__ == "__main__":
    unittest.main()
