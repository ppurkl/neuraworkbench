from pathlib import Path

from neuraworkbench.src.llm_interface import generate_speech_sync


def test_speech_generation():
    selected_text = """
    Insert the text you want to convert to speech here.
    You can replace this block with a short narration, announcement, or script.
    """

    # Insert the output audio file you want to create.
    speech_file_path = Path(r"\INSERT\YOUR\OUTPUT\speech.mp3")

    # Replace the placeholder text and output path above before running this example.
    if "Insert the text you want to convert to speech here." in selected_text:
        return
    if "INSERT\\YOUR" in str(speech_file_path):
        return

    generate_speech_sync(
        text=selected_text,
        output_path=speech_file_path,
        model="gpt-4o-mini-tts",
        voice="nova",
        instructions="Insert the speaking style you want here.",
    )


if __name__ == "__main__":
    test_speech_generation()
