import json
import re
import pdfplumber


def extract_text(pdf_file):
    text = ""

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()

            if page_text:
                text += page_text + "\n"

    return text


def extract_transactions(text):
    pattern = r'(\d{2}/\d{2}/\d{4})\s+(.*?)\s+([+-]?£\d+\.\d{2})'

    matches = re.findall(pattern, text)

    transactions = []

    for date, merchant, amount in matches:
        transactions.append({
            "date": date,
            "merchant": merchant,
            "amount": amount
        })

    return transactions


if __name__ == "__main__":
    pdf_path = "sample.pdf"

    text = extract_text(pdf_path)

    transactions = extract_transactions(text)

    print(transactions)

    json_output = json.dumps(
    {"transactions": transactions},
    indent=4,
    ensure_ascii=False
)

    print(json_output)
