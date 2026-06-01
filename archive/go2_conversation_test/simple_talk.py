import pyttsx3

engine = pyttsx3.init()

print("Go2 conversation test started.")
print("Type something to talk to Go2.")
print("Type 'exit' to quit.")

while True:
    user_text = input("\nYou: ")

    if user_text.lower() in ["exit", "quit", "q"]:
        reply = "Goodbye. I will stop talking now."
        print("Go2:", reply)
        engine.say(reply)
        engine.runAndWait()
        break

    if "hello" in user_text.lower() or "hi" in user_text.lower():
        reply = "Hello, I am Go2. I am ready to talk with you."
    elif "hear" in user_text.lower():
        reply = "Yes, I can hear you through this system."
    elif "ready" in user_text.lower():
        reply = "Yes, I am ready."
    elif "who are you" in user_text.lower():
        reply = "I am Go2, a quadruped robot dog."
    else:
        reply = "I heard you. I am still learning how to respond better."

    print("Go2:", reply)

    engine.say(reply)
    engine.runAndWait()
