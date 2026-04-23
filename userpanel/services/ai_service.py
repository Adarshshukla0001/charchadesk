import google.generativeai as genai
from django.conf import settings

genai.configure(api_key=settings.GEMINI_API_KEY)

model = genai.GenerativeModel("gemini-pro")


def generate_summary(chat_text):
    prompt = f"""
    Summarize this chat in short:
    {chat_text}
    """

    response = model.generate_content(prompt)
    return response.text