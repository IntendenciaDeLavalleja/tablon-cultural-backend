import re

def parse_captcha_question(question: str):
    if not question:
        return None

    match = re.search(r'(\d+)\s*\+\s*(\d+)', question)
    if not match:
        return None

    left = int(match.group(1))
    right = int(match.group(2))
    return left, right

def validate_captcha_answer(question: str, answer: str) -> bool:
    parsed = parse_captcha_question(question)
    if not parsed:
        return False

    try:
        expected = parsed[0] + parsed[1]
        return int(str(answer).strip()) == expected
    except ValueError:
        return False
