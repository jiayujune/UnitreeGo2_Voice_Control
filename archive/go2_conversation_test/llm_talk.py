import os
import pyttsx3
from groq import Groq

# -----------------------------
# 1. Check API key
# -----------------------------
api_key = os.environ.get("GROQ_API_KEY")

if not api_key:
    print("Error: GROQ_API_KEY is not set.")
    print("Please run:")
    print('export GROQ_API_KEY="your_api_key_here"')
    exit(1)

# -----------------------------
# 2. Set up Groq client
# -----------------------------
client = Groq(api_key=api_key)

# You can change this model later if needed.
MODEL_NAME = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")

# -----------------------------
# 3. Set up text-to-speech
# -----------------------------
engine = pyttsx3.init()

# Optional: make speech a little slower
engine.setProperty("rate", 160)

def speak(text):
    print("Go2:", text)
    engine.say(text)
    engine.runAndWait()

# -----------------------------
# 4. Define Go2 personality
# -----------------------------
system_prompt = """
You are Go2, a friendly robot dog conversation assistant.

Your current job is to have a smooth basic conversation with the user.

Important rules:
1. Keep replies short, usually 1 or 2 sentences.
2. Speak in a friendly and calm tone.
3. Do not claim that you can physically move yet.
4. If the user asks you to move, say that you understand the command, but motion control is not connected yet.
5. If the user asks what you are, say you are Go2, a quadruped robot dog.
6. Do not give long technical explanations unless the user asks.
"""

conversation_history = []

# -----------------------------
# 5. Main conversation loop
# -----------------------------
print("Go2 LLM conversation test started.")
print("Type something to talk to Go2.")
print("Type 'exit' to quit.")
print()

speak("Hello, I am Go2. I am ready to talk with you.")

while True:
    user_text = input("\nYou: ")

    if user_text.lower() in ["exit", "quit", "q"]:
        speak("Goodbye. I will stop talking now.")
        break

    conversation_history.append({
        "role": "user",
        "content": user_text
    })

    # Keep only recent conversation so it does not get too long
    recent_history = conversation_history[-8:]

    messages = [{"role": "system", "content": system_prompt}] + recent_history

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0.4,
            max_tokens=120,
        )

        reply = response.choices[0].message.content.strip()

    except Exception as e:
        reply = "Sorry, I had a problem connecting to my language model."
        print("LLM error:", e)

    conversation_history.append({
        "role": "assistant",
        "content": reply
    })

    speak(reply)

