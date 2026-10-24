import pdfplumber


def extract_text(pdf_file):
    text = ""

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()

            if page_text:
                text += page_text + "\n"

    return text


if __name__ == "__main__":
    pdf_path = "sample.pdf"

    text = extract_text(pdf_path)

    print(text)