from django.conf import settings
import json
import logging
from urllib import request as urllib_request
from urllib.error import URLError, HTTPError

logger = logging.getLogger(__name__)

try:
    import google.generativeai as genai
except Exception as e:
    logger.warning(f"Google generativeai library not available: {e}")
    genai = None

GEMINI_API_KEY = (getattr(settings, "GEMINI_API_KEY", "") or "").strip()
model = None

def _initialize_model():
    """Try to initialize Gemini model."""
    global model
    if model is not None:
        return model
    
    if genai is None:
        logger.warning("Google generativeai library not imported")
        return None
    
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not configured")
        return None
    
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # Try models that actually exist
        model_names = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
        for model_name in model_names:
            try:
                model = genai.GenerativeModel(model_name)
                logger.info(f"Gemini model {model_name} initialized successfully")
                return model
            except Exception as e:
                logger.debug(f"Model {model_name} not available: {e}")
                continue
        logger.debug("SDK models not available - will use REST API")
        model = None
        return None
    except Exception as e:
        logger.debug(f"Gemini SDK initialization: {e}")
        return None

# Try initial initialization
try:
    if genai is not None and GEMINI_API_KEY:
        _initialize_model()
except Exception as e:
    logger.error(f"Error during model initialization: {e}")


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
    """Detect emotion using Gemini SDK. Returns (emotion_text, success_flag)"""
    global model
    
    # Try to initialize if not already done
    if model is None:
        model = _initialize_model()
    
    if model is None:
        return None, False

    try:
        response = model.generate_content(prompt)
        text = getattr(response, "text", "") or ""
        return text, True
    except Exception as e:
        logger.debug(f"SDK emotion detection failed: {e}")
        return None, False


def _detect_with_gemini_rest(prompt):
    """Detect emotion using Gemini REST API. Returns (emotion_text, success_flag)"""
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not available")
        return None, False

    # Try models that actually work with this API
    models = [
        "gemini-2.0-flash-latest",
        "gemini-1.5-flash-latest", 
        "gemini-1.5-pro-latest",
    ]
    
    for model_name in models:
        try:
            # Use v1 endpoint for latest models instead of v1beta
            url = (
                "https://generativelanguage.googleapis.com/v1/models/"
                f"{model_name}:generateContent?key={GEMINI_API_KEY}"
            )
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0, "maxOutputTokens": 8},
            }

            req = urllib_request.Request(
                url=url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib_request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                
            if "error" in data:
                error_msg = data['error'].get('message', 'Error')
                logger.warning(f"Model {model_name}: {error_msg}")
                continue
                
            candidates = data.get("candidates") or []
            if not candidates:
                continue

            parts = candidates[0].get("content", {}).get("parts", [])
            text = " ".join((p.get("text", "") for p in parts if isinstance(p, dict))).strip()
            logger.info(f"REST emotion detection successful with {model_name}")
            return text, True
        except Exception as e:
            logger.debug(f"Model {model_name} failed: {e}")
            continue
    
    logger.debug("REST API models failed - using keyword fallback")
    return None, False


def detect_emotion(text):
    """
    Detect emotion from text using AI first, then keyword fallback.
    Returns: (emotion_label, emoji, source)
    source can be: "ai", "keyword", "empty", or "ai_unavailable"
    """
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

    # Try SDK first
    raw, sdk_success = _detect_with_gemini_sdk(prompt)
    
    # If SDK failed, try REST API
    if not sdk_success:
        raw, rest_success = _detect_with_gemini_rest(prompt)
    else:
        rest_success = False

    # If AI detection succeeded (either SDK or REST)
    if sdk_success or rest_success:
        label = _extract_emotion_from_raw(raw, "")
        if label and label in EMOTION_EMOJI_MAP:
            logger.info(f"AI emotion detection successful: {label}")
            return label, EMOTION_EMOJI_MAP[label], "ai"
        else:
            logger.warning(f"AI returned invalid emotion: {label}")

    # AI did not return a usable result, so fall back to keywords.
    keyword_emotion = _keyword_emotion(text)
    return keyword_emotion, EMOTION_EMOJI_MAP[keyword_emotion], "keyword"


def generate_summary(chat_text):
    """Generate summary using Gemini AI."""
    global model
    
    # Try to initialize if not already done
    if model is None:
        model = _initialize_model()
    
    if model is None:
        logger.error("Gemini model not available for summary generation")
        return "Summary service is currently unavailable."

    prompt = f"""
    Summarize this chat in short:
    {chat_text}
    """

    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        logger.error(f"Error generating summary: {e}")
        return "Summary generation failed. Please try again later."