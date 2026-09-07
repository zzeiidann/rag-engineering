import re

STOPWORDS = set(
    "what is the a an my me how does do of for to in and with it provide calculated".split()
)


def terms(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower())) - STOPWORDS
