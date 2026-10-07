import json
import os
import random
import re
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


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


class OllamaError(RuntimeError):
    """Raised when Ollama cannot provide a valid vocabulary response."""


def _ollama_json(prompt):
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    payload = json.dumps({
        "model": os.environ.get("OLLAMA_MODEL", "qwen2.5:3b"),
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a careful Mandarin vocabulary tutor for Indonesian learners. "
                    "Return only valid JSON matching the requested schema."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "format": "json",
        "stream": False,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("OLLAMA_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = Request(f"{base_url}/api/chat", data=payload, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise OllamaError(f"Ollama returned HTTP {error.code}.") from error
    except URLError as error:
        raise OllamaError(f"Could not connect to Ollama: {error.reason}.") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OllamaError("Ollama returned an invalid JSON response.") from error

    content = result.get("message", {}).get("content")
    if not isinstance(content, str):
        raise OllamaError("Ollama response did not contain a chat message.")
    try:
        return json.loads(content)
    except json.JSONDecodeError as error:
        raise OllamaError("Ollama returned invalid vocabulary JSON.") from error


def _validated_word(value):
    if not isinstance(value, dict):
        return None
    fields = ("hanzi", "pinyin", "meaning", "english")
    word = {field: value.get(field) for field in fields}
    if any(not isinstance(word[field], str) or not word[field].strip() for field in fields):
        return None
    word = {field: word[field].strip() for field in fields}
    if (
        len(word["hanzi"]) > 20
        or not HANZI_PATTERN.search(word["hanzi"])
        or len(word["pinyin"]) > 50
        or len(word["meaning"]) > 120
        or len(word["english"]) > 100
    ):
        return None
    return word


def lookup_with_ollama(query):
    result = _ollama_json(
        "Give one Mandarin vocabulary entry for the learner's search term below. "
        "Return a JSON object with string fields hanzi, pinyin (with tone marks), "
        "meaning (Indonesian), and english. Do not translate a full sentence; "
        "if the term is not a vocabulary item, return an empty object.\n"
        f"Search term: {query}"
    )
    word = _validated_word(result)
    return [word] if word else []


def generate_vocabulary(topic, count=10):
    result = _ollama_json(
        f"Create exactly {count} beginner-friendly Mandarin vocabulary entries about "
        f"this topic: {topic!r}. Return a JSON object with a 'words' array. Every array "
        "item must have string fields hanzi, pinyin (with tone marks), meaning "
        "(Indonesian), and english. Use individual words or short common expressions, "
        "not sentences."
    )
    if not isinstance(result, dict) or not isinstance(result.get("words"), list):
        raise OllamaError("Ollama did not return a vocabulary list.")
    words = [word for item in result["words"] if (word := _validated_word(item))]
    if not words:
        raise OllamaError("Ollama did not return any valid vocabulary entries.")
    return words


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
