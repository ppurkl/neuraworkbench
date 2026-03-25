import os

from neuraworkbench.src.audio_processing import compress_audio, transcribe_audio
from neuraworkbench.src.video_processing import (
    download_instagram_reel,
    download_youtube_video,
    download_youtube_video_mp4,
)


def test_video_processing():
    # Insert an Instagram reel URL if you want to test Instagram downloads.
    test_insta_url = "https://www.instagram.com/p/INSERT_SHORTCODE/"

    # Insert a working folder for your downloaded and processed files.
    test_path = r"C:\INSERT\YOUR\VIDEO\WORKDIR"
    video_test_path = os.path.join(test_path, "downloaded_video.mp4")
    audio_test_path = os.path.join(test_path, "audio.ogg")
    text_test_path = os.path.join(test_path, "text.txt")

    # Insert a YouTube URL if you want to test YouTube downloads.
    test_yt_url = "https://www.youtube.com/watch?v=INSERT_VIDEO_ID"

    # Replace the placeholder paths and URLs above before running this example.
    if "INSERT_SHORTCODE" in test_insta_url or "INSERT_VIDEO_ID" in test_yt_url or "INSERT\\YOUR" in test_path:
        return

    # Step 1: Download the video
    # download_instagram_reel(test_insta_url)
    # download_youtube_video(test_yt_url)
    download_youtube_video_mp4(test_yt_url)

    # Step 2: Extract and compress the audio
    compress_audio(source_audio_path=video_test_path, target_audio_path=audio_test_path)

    # Step 3: Generate the transcription of the audio file
    transcribe_audio(audio_path=audio_test_path, text_path=text_test_path)


if __name__ == "__main__":
    test_video_processing()
