import os
import tempfile
import unittest
from unittest.mock import patch

import httpx

os.environ["DATABASE_URL"] = "sqlite://"

from app import app, db, get_secret_key
from chatbots import (
    TranslationError,
    chatbot_response,
    lookup_words,
    translate_text,
    translate_to_english,
    vocabulary_from_translation,
)
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

    def test_translate_text_chooses_direction_from_hanzi(self):
        with patch("chatbots.Translator") as translator:
            translator.return_value.translate.return_value.text = "halo"
            self.assertEqual(translate_text("你好"), "halo")
            translator.return_value.translate.assert_called_once_with(
                "你好", src="zh-cn", dest="id"
            )

        with patch("chatbots.Translator") as translator:
            translator.return_value.translate.return_value.text = "你好"
            self.assertEqual(translate_text("selamat pagi"), "你好")
            translator.return_value.translate.assert_called_once_with(
                "selamat pagi", src="auto", dest="zh-cn"
            )

    def test_translate_text_reports_network_failures(self):
        for network_error in (httpx.NetworkError("offline"), httpx.ReadTimeout("timeout")):
            with self.subTest(error=type(network_error).__name__):
                with patch("chatbots.Translator") as translator:
                    translator.return_value.translate.side_effect = network_error
                    with self.assertRaisesRegex(TranslationError, "koneksi internet"):
                        translate_text("你好")

    def test_vocabulary_from_translation_requires_short_chinese_term(self):
        self.assertEqual(
            vocabulary_from_translation("飞机", "pesawat", "airplane"),
            {
                "hanzi": "飞机",
                "pinyin": "fēi jī",
                "meaning": "pesawat",
                "english": "airplane",
            },
        )
        self.assertEqual(
            vocabulary_from_translation("苹果", "apel", "apple")["meaning"],
            "apel",
        )
        self.assertIsNone(vocabulary_from_translation("飞机", "pesawat", ""))

    def test_translate_to_english_selects_chinese_or_indonesian_source(self):
        with patch("chatbots.Translator") as translator:
            translator.return_value.translate.return_value.text = "airplane"
            self.assertEqual(translate_to_english("飞机"), "airplane")
            translator.return_value.translate.assert_called_once_with(
                "飞机", src="zh-cn", dest="en"
            )

        with patch("chatbots.Translator") as translator:
            translator.return_value.translate.return_value.text = "airplane"
            self.assertEqual(translate_to_english("飞机"), "airplane")
            translator.return_value.translate.assert_called_once_with(
                "飞机", src="zh-cn", dest="en"
            )


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

    def test_secret_key_is_stable_without_environment_configuration(self):
        with tempfile.TemporaryDirectory() as instance_path:
            with patch.dict(os.environ, {"SECRET_KEY": ""}), patch.object(
                app, "instance_path", instance_path
            ):
                first_key = get_secret_key()
                self.assertEqual(get_secret_key(), first_key)
                self.assertEqual(len(first_key), 64)

    def test_lookup_is_recorded_and_history_uses_legacy_column(self):
        response = self.client.post("/", data={"csrf_token": self.csrf_token, "message": "water"})
        self.assertEqual(response.status_code, 200)
        event = LearningEvent.query.one()
        self.assertEqual(event.search_text, "water")
        self.assertEqual(event.matched_hanzi, "水")

    def test_unknown_lookup_stays_local(self):
        response = self.client.post(
            "/",
            data={"csrf_token": self.csrf_token, "message": "not in dictionary"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Kata belum ditemukan".encode(), response.data)
        self.assertEqual(Vocabulary.query.filter_by(hanzi="苹果").count(), 0)

    def test_translation_form_is_available(self):
        response = self.client.get("/")
        self.assertIn(b"Terjemahkan", response.data)
        self.assertIn(b"/translate", response.data)

    def test_translation_requires_csrf_token(self):
        response = self.client.post("/translate", data={"text": "你好"})
        self.assertEqual(response.status_code, 400)

    def test_translation_result_is_shown(self):
        with patch("app.translate_text", return_value="halo"), patch(
            "app.translate_to_english", return_value="hello"
        ):
            response = self.client.post("/translate", data={
                "csrf_token": self.csrf_token,
                "text": "你好",
            })
        self.assertEqual(response.status_code, 302)
        follow_up = self.client.get(response.headers["Location"])
        self.assertEqual(follow_up.status_code, 200)
        self.assertIn("Hasil terjemahan: halo".encode(), follow_up.data)

    def test_new_translation_is_saved_to_dictionary_once(self):
        with patch("app.translate_text", return_value="飞机"), patch(
            "app.translate_to_indonesian", return_value="pesawat"
        ), patch("app.translate_to_english", return_value="airplane"):
            response = self.client.post("/translate", data={
                "csrf_token": self.csrf_token,
                "text": "pesawat",
            })
            self.assertEqual(response.status_code, 302)
            word = Vocabulary.query.filter_by(hanzi="飞机").one()
            self.assertEqual(word.meaning, "pesawat")
            self.assertEqual(word.pinyin, "fēi jī")
            self.assertEqual(word.english, "airplane")

            self.client.post("/translate", data={
                "csrf_token": self.csrf_token,
                "text": "pesawat",
            })
        self.assertEqual(Vocabulary.query.filter_by(hanzi="飞机").count(), 1)

    def test_existing_word_is_enriched_when_translation_fills_missing_details(self):
        word = Vocabulary(hanzi="飞船", meaning="kapal terbang")
        db.session.add(word)
        db.session.commit()
        with patch("app.translate_text", return_value="kapal luar angkasa"), patch(
            "app.translate_to_english", return_value="spaceship"
        ):
            self.client.post("/translate", data={
                "csrf_token": self.csrf_token,
                "text": "飞船",
            })
        saved_word = Vocabulary.query.filter_by(hanzi="飞船").one()
        self.assertEqual(saved_word.pinyin, "fēi chuán")
        self.assertEqual(saved_word.meaning, "kapal terbang")
        self.assertEqual(saved_word.english, "spaceship")

    def test_pinyin_input_saves_correct_indonesian_and_english_details(self):
        with patch("app.translate_text", return_value="爱情片"), patch(
            "app.translate_to_indonesian", return_value="film romantis"
        ), patch("app.translate_to_english", return_value="romance movie"):
            self.client.post("/translate", data={
                "csrf_token": self.csrf_token,
                "text": "aiqingpian",
            })
        word = Vocabulary.query.filter_by(hanzi="爱情片").one()
        self.assertEqual(word.pinyin, "ài qíng piàn")
        self.assertEqual(word.meaning, "film romantis")
        self.assertEqual(word.english, "romance movie")

    def test_retranslation_repairs_old_plain_pinyin_as_meaning(self):
        word = Vocabulary(
            hanzi="爱情片",
            pinyin="",
            meaning="aiqingpian",
            english="",
        )
        db.session.add(word)
        db.session.commit()
        with patch("app.translate_text", return_value="film romantis"), patch(
            "app.translate_to_english", return_value="romance movie"
        ):
            self.client.post("/translate", data={
                "csrf_token": self.csrf_token,
                "text": "爱情片",
            })
        saved_word = Vocabulary.query.filter_by(hanzi="爱情片").one()
        self.assertEqual(saved_word.pinyin, "ài qíng piàn")
        self.assertEqual(saved_word.meaning, "film romantis")
        self.assertEqual(saved_word.english, "romance movie")

    def test_translation_error_is_reported(self):
        with patch("app.translate_text", side_effect=TranslationError("layanan gagal")):
            response = self.client.post("/translate", data={
                "csrf_token": self.csrf_token,
                "text": "你好",
            })
        self.assertEqual(response.status_code, 302)
        follow_up = self.client.get(response.headers["Location"])
        self.assertEqual(follow_up.status_code, 200)
        self.assertIn("layanan gagal".encode(), follow_up.data)

    def test_translation_rejects_input_over_limit(self):
        with patch("app.translate_text") as mocked_translate:
            response = self.client.post("/translate", data={
                "csrf_token": self.csrf_token,
                "text": "a" * 501,
            })
        self.assertEqual(response.status_code, 302)
        mocked_translate.assert_not_called()

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
