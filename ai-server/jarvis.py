import os
import subprocess
import tempfile
import time
import wave

import requests
import sounddevice as sd
from faster_whisper import WhisperModel

RATE = 16000
CHANNELS = 1

WAKE_DURATION = 2
COMMAND_DURATION = 6

WHISPER_MODEL = "small.en"
OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_URL = "http://localhost:11434/api/generate"

PIPER_MODEL = "/home/andrew/ai-server/piper-voices/en_GB-alan-medium.onnx"

WAKE_PHRASE = "magic box"
SLEEP_PHRASE = "banish thyself"

USER_TITLE = "Archmage Andrew"


def record_wav(path: str, seconds: int) -> None:
    audio = sd.rec(
        int(seconds * RATE),
        samplerate=RATE,
        channels=CHANNELS,
        dtype="int16",
    )
    sd.wait()

    with wave.open(path, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(audio.tobytes())


def transcribe_audio(model: WhisperModel, wav_path: str) -> str:
    segments, _info = model.transcribe(
        wav_path,
        language="en",
        vad_filter=True,
        beam_size=5,
        initial_prompt=(
            "This is a voice conversation with Jarvis. "
            "Important words may include Andrew, Archmage Andrew, magic box, "
            "banish thyself, Docker, Ollama, Open WebUI, Pi-hole, Portainer, "
            "NucBox, headset, Bluetooth."
        ),
    )
    return " ".join(segment.text for segment in segments).strip()


def ask_ollama(prompt: str, history: list[dict[str, str]]) -> str:
    conversation_text = ""
    for message in history[-8:]:
        role = message["role"].capitalize()
        conversation_text += f"{role}: {message['content']}\n"

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": (
            f"You are Jarvis, a polished, calm, dry-witted, highly capable magical assistant. "
            f"You are speaking to {USER_TITLE}. "
            f"Address the user naturally as Andrew or {USER_TITLE} when appropriate. "
            f"Your tone should be concise, competent, warm, slightly formal, and distinctly British "
            f"without becoming theatrical. Keep spoken responses short unless asked for detail.\n\n"
            f"Recent conversation:\n{conversation_text}\n"
            f"User: {prompt}\n"
            f"Assistant:"
        ),
        "stream": False,
    }

    response = requests.post(OLLAMA_URL, json=payload, timeout=120)
    response.raise_for_status()
    data = response.json()
    return data.get("response", "").strip()


def play_wav_file(wav_path: str) -> bool:
    try:
        subprocess.run(
            ["paplay", wav_path],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        pass

    try:
        subprocess.run(
            ["aplay", wav_path],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def speak(text: str) -> None:
    print(f"Jarvis: {text}")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name

    try:
        subprocess.run(
            [
                "piper",
                "--model",
                PIPER_MODEL,
                "--output_file",
                wav_path,
            ],
            input=text.encode("utf-8"),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        played = play_wav_file(wav_path)
        if not played:
            print("Warning: could not play audio through paplay or aplay.")
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)


def hear_once(model: WhisperModel, seconds: int) -> str:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name

    try:
        record_wav(wav_path, seconds)
        return transcribe_audio(model, wav_path)
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)


def normalize_text(text: str) -> str:
    return text.lower().strip()


def wake_phrase_detected(text: str) -> bool:
    return WAKE_PHRASE in normalize_text(text)


def sleep_phrase_detected(text: str) -> bool:
    return SLEEP_PHRASE in normalize_text(text)


def conversation_mode(model: WhisperModel) -> None:
    history: list[dict[str, str]] = []
    speak(f"I am here, {USER_TITLE}.")

    while True:
        user_text = hear_once(model, COMMAND_DURATION)

        if not user_text:
            continue

        print(f"You: {user_text}")

        if sleep_phrase_detected(user_text):
            speak(f"As you wish, {USER_TITLE}. I take my leave.")
            return

        history.append({"role": "user", "content": user_text})

        try:
            reply = ask_ollama(user_text, history)
        except requests.RequestException as exc:
            print(f"Ollama request failed: {exc}")
            speak("I am having difficulty reaching my thoughts at the moment.")
            continue

        if not reply:
            speak("I do not seem to have a response at the moment.")
            continue

        history.append({"role": "assistant", "content": reply})
        speak(reply)


def main() -> None:
    if not os.path.exists(PIPER_MODEL):
        print(f"Piper model not found: {PIPER_MODEL}")
        print("Put your British Piper voice .onnx file at that path first.")
        return

    print("Loading Faster-Whisper model...")
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")

    print(f"Jarvis is running. Say '{WAKE_PHRASE}' to wake him.")
    print(f"Say '{SLEEP_PHRASE}' to dismiss him.")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            try:
                wake_text = hear_once(model, WAKE_DURATION)

                if wake_text:
                    print(f"Heard (wake check): {wake_text}")

                if wake_phrase_detected(wake_text):
                    conversation_mode(model)

            except Exception as exc:
                print(f"Unexpected error: {exc}")
                time.sleep(1)

    except KeyboardInterrupt:
        print("\nJarvis stopped.")


if __name__ == "__main__":
    main()
