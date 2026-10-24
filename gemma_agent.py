import time
import traceback
from google import genai
from dotenv import load_dotenv

load_dotenv()


def analyze_spending(full_prompt):
    try:
        client = genai.Client()
    except Exception:
        return traceback.format_exc()

    for attempt in range(3):
        try:
            response = client.models.generate_content(model="gemma-4-31b-it",contents=full_prompt)

            if hasattr(response, "text") and response.text:
                return response.text

            return '{"summary":{"total_spent":0,"total_income":0,"period":"Unknown","currency":"GBP"},"categories":[],"subscriptions":[],"transactions":[]}'

        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")

            if attempt < 2:
                time.sleep(2)
                continue

            return traceback.format_exc()