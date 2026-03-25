from neuraworkbench.src.system_utils import execute_shell_command
from neuraworkbench.src.llm_interface import transcribe_audio_sync


def compress_audio(source_audio_path, target_audio_path, bitrate=12):
    bitrate_str = f"{bitrate}k"
    compression_cmd = (f"ffmpeg "
                       f"-i {source_audio_path} "  # input file
                       f"-vn "  # "No video" – ensures any video streams are ignored. Only audio is processed.
                       f"-map_metadata -1 "  # Discards all metadata (artist, album, tags, etc.).
                       f"-ac 1 "  # Downmixes the audio to mono (1 channel).
                       f"-c:a libopus "  # Use the Opus codec for encoding the audio stream.
                       f"-b:a {bitrate_str} "  # Target bitrate
                       f"-application voip "  # Optimize the Opus encoder for voice / speech instead of music.
                       f"{target_audio_path}")  # The output filename (should be in Ogg container format).
    print(compression_cmd)
    compression_out = execute_shell_command(compression_cmd, ".")
    return compression_out


def transcribe_audio(audio_path, text_path):
    text = transcribe_audio_sync(audio_path)

    # Save transcript to file
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(text)
