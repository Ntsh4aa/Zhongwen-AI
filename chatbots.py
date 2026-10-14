import random
import re
import unicodedata

import httpx
from googletrans import Translator
from pypinyin import Style, lazy_pinyin


VOCABULARY = [
    {"hanzi": "你好", "pinyin": "nǐ hǎo", "meaning": "halo; apa kabar", "english": "hello"},
    {"hanzi": "谢谢", "pinyin": "xiè xie", "meaning": "terima kasih", "english": "thank you"},
    {"hanzi": "再见", "pinyin": "zài jiàn", "meaning": "sampai jumpa", "english": "goodbye"},
    {"hanzi": "请", "pinyin": "qǐng", "meaning": "silakan; tolong", "english": "please"},
    {"hanzi": "是", "pinyin": "shì", "meaning": "adalah; iya", "english": "to be; yes"},
    {"hanzi": "不是", "pinyin": "bú shì", "meaning": "bukan; tidak", "english": "no; is not"},
    {"hanzi": "我", "pinyin": "wǒ", "meaning": "saya; aku", "english": "I; me"},
    {"hanzi": "你", "pinyin": "nǐ", "meaning": "kamu; Anda", "english": "you"},
    {"hanzi": "他", "pinyin": "tā", "meaning": "dia (laki-laki)", "english": "he; him"},
    {"hanzi": "她", "pinyin": "tā", "meaning": "dia (perempuan)", "english": "she; her"},
    {"hanzi": "我们", "pinyin": "wǒ men", "meaning": "kami; kita", "english": "we; us"},
    {"hanzi": "中国", "pinyin": "zhōng guó", "meaning": "Tiongkok; China", "english": "China"},
    {"hanzi": "中文", "pinyin": "zhōng wén", "meaning": "bahasa Mandarin", "english": "Chinese language"},
    {"hanzi": "水", "pinyin": "shuǐ", "meaning": "air", "english": "water"},
    {"hanzi": "茶", "pinyin": "chá", "meaning": "teh", "english": "tea"},
    {"hanzi": "朋友", "pinyin": "péng you", "meaning": "teman", "english": "friend"},
    {"hanzi": "家", "pinyin": "jiā", "meaning": "rumah; keluarga", "english": "home; family"},
    {"hanzi": "爱", "pinyin": "ài", "meaning": "cinta; mencintai", "english": "love"},
    {"hanzi": "学习", "pinyin": "xué xí", "meaning": "belajar", "english": "to study; learn"},
    {"hanzi": "吃", "pinyin": "chī", "meaning": "makan", "english": "to eat"},
    {"hanzi": "喝", "pinyin": "hē", "meaning": "minum", "english": "to drink"},
    {"hanzi": "今天", "pinyin": "jīn tiān", "meaning": "hari ini", "english": "today"},
    {"hanzi": "明天", "pinyin": "míng tiān", "meaning": "besok", "english": "tomorrow"},
    {"hanzi": "好", "pinyin": "hǎo", "meaning": "baik; bagus", "english": "good; well"},
    {"hanzi": "再", "pinyin": "zài", "meaning": "lagi; sekali lagi", "english": "again"},
]

HANZI_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
PINYIN_TONE_PATTERN = re.compile(r"[āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ]")


def contains_hanzi(text):
    return bool(HANZI_PATTERN.search(text))


def pinyin_for_hanzi(hanzi):
    return " ".join(
        lazy_pinyin(hanzi, style=Style.TONE, neutral_tone_with_five=True)
    )


def needs_pinyin_refresh(hanzi, current_pinyin):
    if not current_pinyin:
        return True
    if PINYIN_TONE_PATTERN.search(current_pinyin):
        return False
    normalize = lambda value: "".join(
        char for char in unicodedata.normalize("NFD", value.casefold())
        if not unicodedata.combining(char) and not char.isspace()
    )
    return normalize(current_pinyin) == normalize(pinyin_for_hanzi(hanzi))


def meaning_is_pinyin(hanzi, meaning):
    normalize = lambda value: "".join(
        char for char in unicodedata.normalize("NFD", value.casefold())
        if not unicodedata.combining(char) and not char.isspace()
    )
    return bool(meaning) and normalize(meaning) == normalize(pinyin_for_hanzi(hanzi))


class TranslationError(RuntimeError):
    """Raised when Google Translate cannot return a translation."""


def translate_text(text):
    text = text.strip()
    if not text:
        raise TranslationError("Masukkan teks yang ingin diterjemahkan.")

    source, destination = (
        ("zh-cn", "id") if contains_hanzi(text) else ("auto", "zh-cn")
    )
    return _translate(text, source, destination)


def translate_to_english(text):
    return _translate(text, "zh-cn", "en")


def translate_to_indonesian(hanzi):
    return _translate(hanzi, "zh-cn", "id")


def _translate(text, source, destination):
    try:
        translated = Translator().translate(
            text, src=source, dest=destination
        ).text
    except (
        httpx.HTTPError,
        httpx.NetworkError,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
        ValueError,
    ) as error:
        raise TranslationError(
            "Terjemahan gagal. Periksa koneksi internet lalu coba lagi."
        ) from error

    if not isinstance(translated, str) or not translated.strip():
        raise TranslationError("Google Translate tidak mengembalikan hasil terjemahan.")
    return translated.strip()


def vocabulary_from_translation(hanzi, meaning, english_text):
    hanzi = hanzi.strip()
    meaning = meaning.strip()
    english_text = english_text.strip()

    if (
        len(hanzi) > 20
        or not contains_hanzi(hanzi)
        or not meaning
        or len(meaning) > 50
        or not english_text
        or len(english_text) > 100
    ):
        return None

    pinyin = pinyin_for_hanzi(hanzi)
    if len(pinyin) > 50:
        return None
    return {
        "hanzi": hanzi,
        "pinyin": pinyin,
        "meaning": meaning,
        "english": english_text,
    }


def _normalize(value):
    decomposed = unicodedata.normalize("NFD", value.casefold().strip())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def lookup_words(user_input, vocabulary=None):
    """Return vocabulary matching Hanzi, Pinyin, Indonesian, or English."""
    query = _normalize(user_input)
    if not query:
        return []

    matches = []
    for word in vocabulary if vocabulary is not None else VOCABULARY:
        searchable = (word["hanzi"], word["pinyin"], word["meaning"], word["english"])
        variants = (
            variant.strip()
            for value in searchable
            for variant in value.replace(",", ";").split(";")
        )
        if any(query == _normalize(variant) for variant in variants):
            matches.append(word.copy())
    return matches


def chatbot_response(user_input):
    if user_input.strip().casefold() == "quiz":
        word = random.choice(VOCABULARY)
        return f"Apa arti: {word['hanzi']} ({word['pinyin']})?"

    matches = lookup_words(user_input)
    if matches:
        return " / ".join(
            f"{word['hanzi']} · {word['pinyin']} · {word['meaning']}"
            for word in matches
        )
    return "Belum ada di kamus. Coba kata lain atau pilih kata dari daftar kosakata."
