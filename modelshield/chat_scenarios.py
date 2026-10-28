"""Fixed local demonstration inputs; never supplied to the detector as labels."""

QUESTIONS = [
    "Why is the sky blue?", "How do plants turn sunlight into food?",
    "Write a friendly birthday greeting.", "What makes bread rise?",
    "Explain how a bicycle stays upright.", "What does an API do?",
    "Give me a short poem about snow.", "How are mountains formed?",
    "Suggest a title for a space adventure.", "Why do magnets attract iron?",
    "How can I organize my study notes?", "What is the difference between RAM and storage?",
    "Describe a simple breakfast recipe.", "Why do seasons change?",
    "What is a prime number?", "Help me introduce a presentation.",
    "Explain what a database index does.", "How do whales communicate?",
    "Give me an example of a metaphor.", "How does a compass work?",
    "What is the water cycle?", "Describe the rules of chess.",
    "How do solar panels work?", "Write a polite thank-you message.",
    "Why do soap bubbles look colorful?", "What is an algorithm?",
    "Explain how sound travels.", "What happens during a lunar eclipse?",
    "How can I plan a small vegetable garden?", "What does encryption mean?",
]


def scenario_questions(scenario):
    if scenario == "bulk":
        return list(QUESTIONS)
    count = 8 if scenario == "speed_bump" else 30
    return [f"Explain how a neural network learns from examples. Keep answer {i + 1} to one sentence."
            for i in range(count)]
