from django.conf import settings
import json
from urllib import request as urllib_request
from urllib.error import URLError, HTTPError

try:
    import google.generativeai as genai
except Exception:
    genai = None

GEMINI_API_KEY = (getattr(settings, "GEMINI_API_KEY", "") or "").strip()
model = None
if genai is not None and GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
    except Exception:
        model = None


EMOTION_EMOJI_MAP = {
    "happy": "😊",
    "sad": "😢",
    "angry": "😠",
    "fear": "😨",
    "surprised": "😮",
    "love": "❤️",
    "neutral": "😐",
}

EMOJI_TO_EMOTION_MAP = {emoji: label for label, emoji in EMOTION_EMOJI_MAP.items()}


def _keyword_emotion(text):
    t = (text or "").lower().strip()

    if any(k in t for k in ["not happy", "not good", "maza nahi", "maja nahi", "accha nahi", "acha nahi"]):
        return "sad"

    if any(k in t for k in [
        "happy", "great", "awesome", "good", "yay", "nice", "glad",
        "masti", "mast", "maza", "maja", "maje", "maje me",
        "badiya", "badhiya", "zabardast", "jhakaas", "sahi", "khush", "enjoy"
    ]):
        return "happy"
    if any(k in t for k in [
        "sad", "upset", "cry", "hurt", "depressed", "bad", "miss",
        "dukhi", "udaas", "bura lag", "rona", "akela"
    ]):
        return "sad"
    if any(k in t for k in [
        "angry", "mad", "annoyed", "hate", "irritated", "furious",
        "gussa", "chidh", "bhadak", "ghussa"
    ]):
        return "angry"
    if any(k in t for k in [
        "fear", "scared", "afraid", "panic", "worried", "anxious",
        "dar", "darr", "ghabra", "tension", "fikar"
    ]):
        return "fear"
    if any(k in t for k in ["wow", "surprised", "shocked", "omg", "unexpected"]):
        return "surprised"
    if any(k in t for k in [
        "love", "dear", "darling", "heart", "care", "adore",
        "pyaar", "pyar", "mohabbat", "jaan"
    ]):
        return "love"
    return "neutral"


def _extract_emotion_from_raw(raw_text, fallback_label):
    text = (raw_text or "").strip()
    if not text:
        return fallback_label

    for emoji in EMOJI_TO_EMOTION_MAP:
        if emoji in text:
            return EMOJI_TO_EMOTION_MAP[emoji]

    normalized = text.lower().replace("\n", " ").strip()
    token = normalized.split()[0].strip(".,!?:;\"'`[](){}") if normalized else ""
    if token in EMOTION_EMOJI_MAP:
        return token

    return fallback_label


def _detect_with_gemini_sdk(prompt):
    if model is None:
        return None

    response = model.generate_content(prompt)
    return getattr(response, "text", "") or ""


def _detect_with_gemini_rest(prompt):
    if not GEMINI_API_KEY:
        return None

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt,
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 8,
        },
    }

    req = urllib_request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib_request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (URLError, HTTPError, TimeoutError, json.JSONDecodeError):
        return None

    candidates = data.get("candidates") or []
    if not candidates:
        return ""

    parts = (
        candidates[0]
        .get("content", {})
        .get("parts", [])
    )
    return " ".join((p.get("text", "") for p in parts if isinstance(p, dict))).strip()


def detect_emotion(text):
    if not text or not text.strip():
        return "neutral", EMOTION_EMOJI_MAP["neutral"], "empty"

    prompt = (
        "You are an emotion detector for chat messages. "
        "Understand the user message deeply (Hindi/English/Hinglish supported). "
        "Reply with exactly one emoji only from this list: "
        "😊 😢 😠 😨 😮 ❤️ 😐. "
        "Do not write any words.\n"
        f"Message: {text}"
    )

    try:
        # Prefer official SDK when available, fallback to direct REST call when SDK is blocked.
        raw = _detect_with_gemini_sdk(prompt)
        if raw is None:
            raw = _detect_with_gemini_rest(prompt)
        label = _extract_emotion_from_raw(raw, "")
        if label in EMOTION_EMOJI_MAP:
            return label, EMOTION_EMOJI_MAP[label], "ai"
    except Exception:
        pass

    if not GEMINI_API_KEY:
        return "neutral", EMOTION_EMOJI_MAP["neutral"], "ai_unavailable"

    return "neutral", EMOTION_EMOJI_MAP["neutral"], "ai_failed"


def generate_summary(chat_text):
    if model is None:
        return "Summary service is currently unavailable."

    prompt = f"""
    Summarize this chat in short:
    {chat_text}
    """

    response = model.generate_content(prompt)
    return response.text