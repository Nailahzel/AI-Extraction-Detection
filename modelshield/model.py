"""Small reproducible sentiment model. No runtime downloads or external API calls.

The bundled training corpus is original synthetic demonstration data. Confidence
is the classifier's probability, not a calibrated guarantee of correctness.
Contextual examples cover praise followed by failures and resolved failures;
they improve these cases without providing general sarcasm understanding.
"""

from functools import lru_cache
import hashlib

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer, HashingVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

SUBJECTS = (
    "product",
    "movie",
    "service",
    "hotel",
    "meal",
    "application",
    "delivery",
    "support",
    "experience",
    "camera",
    "course",
    "book",
)
POSITIVE = (
    "excellent",
    "wonderful",
    "fantastic",
    "delightful",
    "great",
    "amazing",
    "reliable",
    "beautiful",
    "helpful",
    "impressive",
    "good",
    "superb",
)
NEGATIVE = (
    "terrible",
    "awful",
    "disappointing",
    "dreadful",
    "bad",
    "horrible",
    "unreliable",
    "broken",
    "useless",
    "frustrating",
    "poor",
    "unpleasant",
)

# Matched outcomes prevent a praise word (or the word "crashes" by itself)
# from deciding the label. The reported regression sentence is not a training
# row: these examples teach reusable failure and recovery phrases.
OUTCOMES = {
    "negative": (
        "it crashes every time I open it",
        "it deletes my saved documents",
        "it freezes and loses my work",
        "it keeps charging me twice",
        "it stops working during important tasks",
        "it corrupts my saved files",
        "it fails to save any changes",
        "it refuses to open my documents",
        "it crashes and deletes my files",
        "it crashes repeatedly and loses hours of work",
        "it still crashes instead of fixing the problem",
        "it claims to save files but deletes them",
    ),
    "positive": (
        "it never crashes when I open it",
        "it keeps all my saved documents safe",
        "it no longer freezes or loses my work",
        "it fixed the duplicate charges and refunded my money",
        "it works smoothly during important tasks",
        "it recovered my corrupted files",
        "it saves every change successfully",
        "it opens all my documents without problems",
        "it saves my files and never crashes",
        "it stopped crashing and now preserves all my work",
        "it fixed the crashes and solved the problem",
        "it prevents data loss and keeps reliable backups",
    ),
}


class SentimentModel:
    name = "Sentinel / TF-IDF sentiment v2"

    def __init__(self):
        texts, labels = [], []
        for subject in SUBJECTS:
            for label, words in (("positive", POSITIVE), ("negative", NEGATIVE)):
                for word in words:
                    texts.extend(
                        (
                            f"The {subject} was {word}.",
                            f"What a {word} {subject}!",
                            f"I found this {subject} really {word}.",
                            f"Absolutely {word} and very {word}.",
                        )
                    )
                    labels.extend([label] * 4)
                    texts.append(f"The {subject} was not {word}.")
                    labels.append("negative" if label == "positive" else "positive")
        extras = {
            "positive": [
                "I love it and would recommend it",
                "It exceeded my expectations",
                "I am happy and satisfied",
                "Works perfectly every time",
                "Worth every penny",
                "Thank you for the quick help",
                "I enjoyed every minute",
                "A pleasure to use",
            ],
            "negative": [
                "I hate it and want a refund",
                "It failed to meet my expectations",
                "I am unhappy and dissatisfied",
                "It never works properly",
                "A complete waste of money",
                "Nobody helped resolve the issue",
                "I regret buying it",
                "A painful experience",
            ],
        }
        for label, examples in extras.items():
            texts.extend(examples * 8)
            labels.extend([label] * len(examples) * 8)
        for label, outcomes in OUTCOMES.items():
            for outcome in outcomes:
                for praise in POSITIVE:
                    texts.extend(
                        (
                            f"Absolutely {praise}! {outcome}. Exactly what I needed!",
                            f"What a {praise} update: {outcome}.",
                            f"The application is {praise}; {outcome}.",
                        )
                    )
                    labels.extend([label] * 3)
        self.pipeline = make_pipeline(
            TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True),
            LogisticRegression(C=12, max_iter=400, random_state=42),
        )
        self.pipeline.fit(texts, labels)
        self.training_samples = len(texts)
        self.fingerprint = hashlib.sha256("\n".join(texts).encode()).hexdigest()[:16]
        # Fixed feature space handles unseen words without fitting on evaluation traffic.
        self.features = HashingVectorizer(
            n_features=2048, alternate_sign=False, ngram_range=(1, 2), norm="l2"
        )

    @lru_cache(maxsize=2048)
    def predict(self, text: str) -> tuple[str, float]:
        probabilities = self.pipeline.predict_proba([text])[0]
        index = int(np.argmax(probabilities))
        return str(self.pipeline.classes_[index]), round(float(probabilities[index]), 4)

    @lru_cache(maxsize=2048)
    def vector(self, text: str):
        return self.features.transform([text])

    def metadata(self):
        return {
            "name": self.name,
            "training_samples": self.training_samples,
            "fingerprint": self.fingerprint,
            "runtime": "Local CPU",
            "corpus": "Original synthetic demonstration corpus",
            "similarity": "Hashed lexical word/bigram cosine (not semantic embeddings)",
        }
