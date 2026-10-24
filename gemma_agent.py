import os
from google import genai
from dotenv import load_dotenv

load_dotenv() 

def analyze_spending(bank_statement_text, prompt_instructions):
    try:
        client = genai.Client() 
    except Exception as e:
        return f"Error initializing client: Ensure GEMINI_API_KEY is set. Details: {e}"
    

    full_content = f"{prompt_instructions}\n\nHere is the data:\n{bank_statement_text}"
    
    try:
        response = client.models.generate_content(model='gemma-4-31b-it', contents=full_content)
        return response.text
    except Exception as e:
        return f"API Error: {e}"
    