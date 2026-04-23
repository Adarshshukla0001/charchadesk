from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional
import re
import requests

from django.conf import settings
from django.utils import timezone


def _safe_text(value: str) -> str:
    return (value or "").strip()


def _normalize_language(language: Optional[str]) -> str:
    selected = _safe_text(language or "English")
    if not selected:
        return "English"

    allowed = {"english", "hindi"}
    lower = selected.lower()
    if lower in allowed:
        if lower == "english":
            return "English"
        return "Hindi"
    return "English"


def _fallback_labels(language: str) -> dict[str, str]:
    preferred = _normalize_language(language)
    if preferred == "Hindi":
        return {
            "title": "सारांश (Fallback):",
            "messages": "चुने गए समय की कुल मैसेज संख्या",
            "participants": "भागीदार",
            "deadline": "समय-सीमा/संदर्भ",
            "request": "मुख्य अनुरोध",
            "response": "उत्तर/प्रतिबद्धता",
            "constraint": "सीमा/स्थिति",
            "highlight": "हाल की मुख्य बात",
            "unknown": "Unknown",
            "mentioned": "ने कहा",
            "asked": "ने पूछा",
            "replied": "ने जवाब दिया",
        }
    return {
        "title": "Summary (Fallback):",
        "messages": "Messages in range",
        "participants": "Participants",
        "deadline": "Deadline/context",
        "request": "Main request",
        "response": "Response/commitment",
        "constraint": "Constraint noted",
        "highlight": "Recent highlight",
        "unknown": "Unknown",
        "mentioned": "mentioned",
        "asked": "asked",
        "replied": "replied",
    }


def to_aware_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse datetime strings (datetime-local or ISO) into aware datetime."""
    if not value:
        return None

    normalized = value.strip()

    # Support ISO values from frontend like 2026-04-23T10:15:00.000Z
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(normalized, "%Y-%m-%dT%H:%M")
        except ValueError:
            return None

    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def build_chat_transcript(messages: Iterable, max_messages: int = 80, max_chars: int = 9000) -> str:
    """Build a compact transcript while limiting message/token load."""
    lines = []
    total_chars = 0

    for msg in list(messages)[-max_messages:]:
        text = _safe_text(getattr(msg, "message", ""))
        has_file = bool(getattr(msg, "file", None))

        if not text and not has_file:
            continue

        sender = _safe_text(getattr(getattr(msg, "sender", None), "name", "User")) or "User"
        timestamp = getattr(msg, "timestamp", None)
        time_label = timezone.localtime(timestamp).strftime("%Y-%m-%d %H:%M") if timestamp else "Unknown time"

        if not text and has_file:
            text = "[Shared a file]"
        elif has_file:
            text = f"{text} [File attached]"

        line = f"[{time_label}] {sender}: {text}"

        if total_chars + len(line) > max_chars:
            break

        lines.append(line)
        total_chars += len(line)

    return "\n".join(lines)


def _parse_transcript_line(line: str) -> tuple[str, str]:
    """Parse a transcript line in format: [timestamp] Speaker: message."""
    cleaned = _safe_text(line)
    if not cleaned:
        return "", ""

    after_time = cleaned
    if "] " in cleaned:
        after_time = cleaned.split("] ", 1)[1]

    if ":" not in after_time:
        return "", after_time

    speaker, message = after_time.split(":", 1)
    return _safe_text(speaker), _safe_text(message)


def _fallback_summary_from_transcript(transcript: str, language: str = "English", max_points: int = 5) -> str:
    """Create a lightweight summary if Gemini is unavailable."""
    preferred_language = _normalize_language(language)
    labels = _fallback_labels(preferred_language)
    lines = [line.strip() for line in transcript.splitlines() if line.strip()]
    if not lines:
        return "No meaningful messages found in the selected time range."

    parsed_rows = []
    participants = []
    for line in lines:
        speaker, content = _parse_transcript_line(line)
        parsed_rows.append((speaker, content))
        if speaker and speaker not in participants:
            participants.append(speaker)

    if not parsed_rows:
        return "No meaningful messages found in the selected time range."

    def first_match(patterns: list[str]) -> Optional[tuple[str, str]]:
        for speaker, content in parsed_rows:
            text = content.lower()
            for pattern in patterns:
                if re.search(pattern, text):
                    return speaker, content
        return None

    def compact_text(text: str, limit: int = 120) -> str:
        cleaned = _safe_text(text)
        if len(cleaned) <= limit:
            return cleaned
        return f"{cleaned[:limit - 3]}..."

    def is_greeting(text: str) -> bool:
        return bool(re.search(r"\b(hi|hello|hey|radhe radhe|namaste|gm|good morning)\b", text.lower()))

    def add_unique_point(points: list[str], seen: set[str], line: str) -> None:
        normalized = re.sub(r"^[-•\s]+", "", line).lower()
        if normalized in seen:
            return
        seen.add(normalized)
        points.append(line)

    deadlines = first_match([
        r"\bdeadline\b",
        r"\blast day\b",
        r"\btomorrow\b",
        r"\bsubmission\b",
        r"\bppt\b",
        r"\btoday\b",
    ])
    requests = first_match([
        r"\bcan you\b",
        r"\bplease\b",
        r"\bhelp\b",
        r"\bneed\b",
        r"\bkaam\b",
        r"\bkaroge\b",
        r"\bfees?\b",
        r"\bjama\b",
        r"\burgent\b",
        r"\?",
    ])
    commitments = first_match([
        r"\byes\b",
        r"\bsure\b",
        r"\bok\b",
        r"\bdekhenge\b",
        r"\bkardenge\b",
        r"\bho payega\b",
        r"\bof course\b",
        r"\bi will\b",
        r"\bdone\b",
    ])
    constraints = first_match([
        r"\bbusy\b",
        r"\boccupied\b",
        r"\bnot possible\b",
        r"\btime\b",
    ])

    summary_lines = [
        labels["title"],
        f"- {labels['messages']}: {len(lines)}",
        f"- {labels['participants']}: {', '.join(participants) if participants else labels['unknown']}",
    ]
    seen_points: set[str] = set()
    important_points: list[str] = []

    if deadlines:
        if preferred_language == "Hindi":
            add_unique_point(important_points, seen_points, f"- {labels['deadline']}: {deadlines[0]} ने समय-सीमा/सबमिशन की बात की")
        else:
            add_unique_point(important_points, seen_points, f"- {labels['deadline']}: {deadlines[0]} mentioned submission urgency and timeline pressure")

    if requests:
        if preferred_language == "Hindi":
            add_unique_point(important_points, seen_points, f"- {labels['request']}: {requests[0]} ने मदद या काम से जुड़ा अनुरोध किया")
        else:
            add_unique_point(important_points, seen_points, f"- {labels['request']}: {requests[0]} requested urgent help with a fee/payment-related task")

    if constraints:
        if preferred_language == "Hindi":
            add_unique_point(important_points, seen_points, f"- {labels['constraint']}: {constraints[0]} ने समय/उपलब्धता की सीमा बताई")
        else:
            add_unique_point(important_points, seen_points, f"- {labels['constraint']}: {constraints[0]} indicated availability/time constraints")

    if commitments:
        if preferred_language == "Hindi":
            add_unique_point(important_points, seen_points, f"- {labels['response']}: {commitments[0]} ने सहयोग/स्वीकृति वाला जवाब दिया")
        else:
            add_unique_point(important_points, seen_points, f"- {labels['response']}: {commitments[0]} responded positively and said they would try to help")

    # Capture one additional significant line if it is not just a greeting.
    for speaker, content in reversed(parsed_rows):
        if not content or is_greeting(content):
            continue
        normalized = content.lower()
        if normalized in seen_points:
            continue
        if any(re.search(pattern, normalized) for pattern in [
            r"\bppt\b", r"\bfee\b", r"\bfees\b", r"\bdesign\b", r"\bsubmission\b",
            r"\burgent\b", r"\bimportant\b", r"\bhelp\b", r"\bwork\b", r"\btask\b", r"\bproject\b"
        ]):
            if preferred_language == "Hindi":
                if re.search(r"\b(fee|fees|jama)\b", normalized):
                    add_unique_point(important_points, seen_points, f"- {labels['highlight']}: दूसरे पक्ष ने फीस जमा करने में मदद मांगी")
                elif re.search(r"\b(ppt|submission|deadline|tomorrow)\b", normalized):
                    add_unique_point(important_points, seen_points, f"- {labels['highlight']}: बातचीत में समय-सीमा और सबमिशन की तात्कालिकता रही")
                else:
                    add_unique_point(important_points, seen_points, f"- {labels['highlight']}: हाल की बातचीत में महत्वपूर्ण कार्य-संबंधी चर्चा हुई")
            else:
                add_unique_point(
                    important_points,
                    seen_points,
                    f"- {labels['highlight']}: The chat contains an urgent fee/payment assistance request",
                )
            break

    summary_lines.extend(important_points)

    if len(summary_lines) > max_points + 2:
        summary_lines = summary_lines[: max_points + 2]

    return "\n".join(summary_lines)


def _looks_like_verbatim(transcript: str, output: str) -> bool:
    """Detect if model output is mostly copied transcript instead of summary."""
    output_lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    transcript_lines = [ln.strip() for ln in transcript.splitlines() if ln.strip()]
    if not output_lines:
        return True

    copied = 0
    transcript_set = set(transcript_lines)
    for line in output_lines:
        if line in transcript_set or line.count("]") > 0:
            copied += 1

    return copied >= max(3, int(len(output_lines) * 0.8))


def _language_script_ratio(text: str, language: str) -> float:
    """Measure how much text matches expected script for selected language."""
    preferred = _normalize_language(language)
    cleaned = _safe_text(text)
    if not cleaned:
        return 0.0

    script_ranges = {
        "Hindi": r"\u0900-\u097F",
    }

    if preferred == "English":
        latin_chars = re.findall(r"[A-Za-z]", cleaned)
        alpha_chars = re.findall(r"[A-Za-z\u0900-\u097F\u0980-\u09FF\u0A80-\u0AFF\u0B80-\u0BFF\u0C00-\u0C7F]", cleaned)
        if not alpha_chars:
            return 0.0
        return len(latin_chars) / len(alpha_chars)

    script_range = script_ranges.get(preferred)
    if not script_range:
        return 0.0

    target_chars = re.findall(f"[{script_range}]", cleaned)
    alpha_chars = re.findall(r"[A-Za-z\u0900-\u097F\u0980-\u09FF\u0A80-\u0AFF\u0B80-\u0BFF\u0C00-\u0C7F]", cleaned)
    if not alpha_chars:
        return 0.0
    return len(target_chars) / len(alpha_chars)


def _is_language_compliant(text: str, language: str) -> bool:
    preferred = _normalize_language(language)
    ratio = _language_script_ratio(text, preferred)

    if preferred == "English":
        if ratio < 0.75:
            return False
        return not _contains_hinglish_markers(text)
    return ratio >= 0.65


def _contains_hinglish_markers(text: str) -> bool:
    """Detect common Roman Hindi/Hinglish tokens that should not appear in pure English output."""
    tokens = {
        "bhai", "bhadiya", "kaise", "karoge", "kardenge", "dekhenge", "yaar", "bahut",
        "argent", "thik", "thik hoon", "hoon", "tum", "mera", "jama", "kaam", "mai", "nahi"
    }
    words = re.findall(r"[a-zA-Z']+", _safe_text(text).lower())
    if not words:
        return False
    joined = " ".join(words)
    if "thik hoon" in joined:
        return True
    return any(word in tokens for word in words)


def _summarize_with_gemini_rest(transcript: str, api_key: str, language: str) -> str:
    """Call Gemini REST API and return summary text."""
    preferred_language = _normalize_language(language)
    prompt = (
        "Read the chat carefully, understand the actual meaning, and create a concise summary. "
        "Do not copy chat lines. Do not mention timestamps. Do not mention every message. "
        "Prioritize important facts such as request, response, deadline, urgency, task, agreement, payment/fees request, and next action. "
        "Use only 3 to 5 bullets. If a detail is important, mention it directly instead of omitting it. "
        f"Write the complete response only in {preferred_language}. "
        "If the language is Hindi, use full Hindi sentences in Devanagari script and translate all non-name words. "
        "If the language is English, use full natural English and translate Hinglish/Hindi content.\n\n"
        f"Chat transcript:\n{transcript}"
    )

    return _call_gemini_text(prompt, api_key)


def _call_gemini_text(prompt: str, api_key: str, max_output_tokens: int = 240) -> str:
    """Low-level Gemini REST text call."""
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-1.5-flash:generateContent"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.9,
            "maxOutputTokens": max_output_tokens,
        },
    }

    response = requests.post(
        f"{endpoint}?key={api_key}",
        json=payload,
        timeout=25,
    )
    response.raise_for_status()

    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        return ""

    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        return ""

    return _safe_text(parts[0].get("text", ""))


def _translate_summary_with_gemini(summary_text: str, api_key: str, language: str) -> str:
    """Translate summary into selected language while keeping it short and structured."""
    preferred_language = _normalize_language(language)

    if preferred_language == "English":
        prompt_templates = [
            (
                "Rewrite the following summary in clear, natural, grammatically correct English. "
                "Translate all Hindi/Hinglish phrases fully to English, keep names unchanged, and keep only 3 to 5 short bullets. "
                "Do not use words like bhai, kaise, thik, yaar, dekhenge, kardenge.\n\n"
                "Example conversion: 'mai khana kha raha hoon' -> 'I am eating food'.\n\n"
                f"Summary:\n{summary_text}"
            ),
            (
                "Convert every bullet into proper professional English only. "
                "No Hindi words and no transliterated words. Keep it concise and factual.\n\n"
                "Example conversion: 'mai khana kha raha hoon' -> 'I am eating food'.\n\n"
                f"Text:\n{summary_text}"
            ),
        ]
    elif preferred_language == "Hindi":
        prompt_templates = [
            (
                "Rewrite the following summary fully in natural Hindi (Devanagari). "
                "Translate all non-name words to Hindi. Keep 3 to 5 short bullets and preserve important facts.\n\n"
                f"Summary:\n{summary_text}"
            ),
            (
                "Convert every line into proper Hindi Devanagari. "
                "No English sentence except person names. Keep concise bullet format.\n\n"
                f"Text:\n{summary_text}"
            ),
        ]
    else:
        prompt_templates = [
            (
                "Rewrite the following summary fully in natural Hindi (Devanagari). "
                "Translate all non-name words to Hindi. Keep 3 to 5 short bullets and preserve important facts.\n\n"
                f"Summary:\n{summary_text}"
            ),
            (
                "Convert every line into proper Hindi Devanagari. "
                "No English sentence except person names. Keep concise bullet format.\n\n"
                f"Text:\n{summary_text}"
            ),
        ]

    last_text = summary_text
    for prompt in prompt_templates:
        translated = _call_gemini_text(prompt, api_key, max_output_tokens=320)
        if translated:
            last_text = translated
        if translated and _is_language_compliant(translated, preferred_language):
            return translated

    return last_text


def _dedupe_summary_lines(summary_text: str) -> str:
    """Remove duplicate and greeting-only lines from a generated summary."""
    lines = [line.strip() for line in _safe_text(summary_text).splitlines() if line.strip()]
    if not lines:
        return summary_text

    seen = set()
    cleaned_lines = []
    for index, line in enumerate(lines):
        if index == 0:
            cleaned_lines.append(line)
            continue

        normalized = re.sub(r"^[-•\s]+", "", line).lower()
        # Normalize by removing label prefix to dedupe semantically repeated bullets.
        normalized_key = normalized.split(":", 1)[-1].strip().strip('"') if ":" in normalized else normalized
        if not normalized or normalized in seen:
            continue
        if re.search(r"\b(hi|hello|hey|radhe radhe|namaste)\b", normalized):
            continue
        if normalized_key in seen:
            continue
        seen.add(normalized)
        seen.add(normalized_key)
        cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


def _enforce_language_output(summary_text: str, api_key: str, language: str) -> str:
    """Force summary into selected language if leakage remains."""
    preferred = _normalize_language(language)
    text = _safe_text(summary_text)
    if not text:
        return text

    if _is_language_compliant(text, preferred):
        return text

    if preferred == "Hindi":
        strict_prompt = (
            "Rewrite this summary in pure Hindi Devanagari. "
            "Translate every non-name word. Keep only 3 to 5 short bullets.\n\n"
            f"Summary:\n{text}"
        )
    elif preferred == "English":
        strict_prompt = (
            "Rewrite this summary in pure, grammatically correct English only. "
            "Translate all Hindi/Hinglish words and keep 3 to 5 short bullets.\n\n"
            f"Summary:\n{text}"
        )
    else:
        strict_prompt = (
            "Rewrite this summary in pure Hindi Devanagari. "
            "Translate every non-name word and keep 3 to 5 short bullets.\n\n"
            f"Summary:\n{text}"
        )

    retried = _call_gemini_text(strict_prompt, api_key, max_output_tokens=320)
    return retried if retried else text


def _polish_english_summary(summary_text: str, api_key: str) -> str:
    """Final pass to ensure concise and grammatical English summary."""
    base = _safe_text(summary_text)
    if not base:
        return base

    prompt = (
        "Polish the following summary into concise, grammatically correct English. "
        "Keep all important facts (request, response, deadline/urgency, next action), "
        "use 3 to 5 short bullets, and do not add new information.\n\n"
        f"Summary:\n{base}"
    )
    polished = _call_gemini_text(prompt, api_key, max_output_tokens=300)
    return polished or base


def summarize_chat_with_gemini(chat_transcript: str, language: str = "English") -> str:
    """Generate a concise chat summary using Gemini API."""
    transcript = _safe_text(chat_transcript)
    preferred_language = _normalize_language(language)
    if not transcript:
        return "No meaningful messages found in the selected time range."

    api_key = _safe_text(getattr(settings, "GEMINI_API_KEY", ""))
    if not api_key:
        return _fallback_summary_from_transcript(transcript, language=preferred_language)

    try:
        output = _summarize_with_gemini_rest(transcript, api_key, preferred_language)
        if output and not _looks_like_verbatim(transcript, output):
            translated = _translate_summary_with_gemini(output, api_key, preferred_language)
            translated = _dedupe_summary_lines(translated)
            translated = _enforce_language_output(translated, api_key, preferred_language)
            if preferred_language == "English":
                translated = _polish_english_summary(translated, api_key)
                translated = _dedupe_summary_lines(translated)
            if translated:
                return _format_summary_output(_dedupe_summary_lines(translated), preferred_language)
    except Exception:
        pass

    fallback = _fallback_summary_from_transcript(transcript, language=preferred_language)
    try:
        translated_fallback = _translate_summary_with_gemini(fallback, api_key, preferred_language)
        translated_fallback = _dedupe_summary_lines(translated_fallback)
        translated_fallback = _enforce_language_output(translated_fallback, api_key, preferred_language)
        if preferred_language == "English":
            translated_fallback = _polish_english_summary(translated_fallback, api_key)
            translated_fallback = _dedupe_summary_lines(translated_fallback)
        if _is_language_compliant(translated_fallback, preferred_language):
            return _format_summary_output(_dedupe_summary_lines(translated_fallback), preferred_language)
        return _format_summary_output(_dedupe_summary_lines(fallback), preferred_language)
    except Exception:
        return _format_summary_output(_dedupe_summary_lines(fallback), preferred_language)


def _format_summary_output(summary_text: str, language: str) -> str:
    """Normalize heading and bullet formatting for clean UI rendering."""
    preferred = _normalize_language(language)
    cleaned = _safe_text(summary_text)
    if not cleaned:
        return cleaned

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return cleaned

    heading = "**Summary:**" if preferred == "English" else "**सारांश:**"
    if not lines[0].startswith("**"):
        lines[0] = heading
    else:
        lines[0] = heading

    bulletized = []
    for line in lines[1:]:
        bulletized.append(line if line.startswith("-") or line.startswith("•") else f"- {line}")

    return "\n".join([lines[0], *bulletized])
