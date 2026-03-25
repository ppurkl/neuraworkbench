import os
import yt_dlp
import instaloader

from neuraworkbench.src.audio_processing import compress_audio, transcribe_audio


def download_youtube_video(url):
    with yt_dlp.YoutubeDL({'extract_audio': True, 'format': 'bestaudio', 'outtmpl': '%(title)s.mp3'}) as video:
        info_dict = video.extract_info(url, download=True)
        video_title = info_dict['title']
        print(video_title)
        video.download(url)
        print("Successfully Downloaded")


def pick_german_audio(formats):
    """
    Return the best (highest abr) German audio-only format-id if present.
    We check multiple possible metadata fields and common language codes.
    """
    candidates = []
    for f in formats:
        if f.get("vcodec") == "none":  # audio-only
            # yt-dlp may expose language as 'language' and/or 'lang'
            lang = (f.get("language") or f.get("lang") or "").lower()
            if lang in {"de", "deu", "ger", "de-DE".lower()}:
                # Prefer higher bitrate (abr), fall back to tbr/asr if missing
                score = (
                    (f.get("abr") or 0),
                    (f.get("tbr") or 0),
                    (f.get("asr") or 0),
                )
                candidates.append((score, f))
    if not candidates:
        return None
    # pick highest-abr candidate
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]["format_id"]


def download_youtube_video_mp4(url):
    # yt-dlp options
    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4",  # mp4 video + audio
        "merge_output_format": "mp4",  # ensure final file is MP4
        "outtmpl": "%(title)s.%(ext)s",  # output filename = video title.mp4
    }
    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[lang=de]/mp4",  # pick German audio
        "merge_output_format": "mp4",
        "outtmpl": "%(title)s.%(ext)s",
        "postprocessors": [{
            "key": "FFmpegVideoConvertor",
            "preferedformat": "mp4",  # force mp4 output
        }],
    }

    # Run yt-dlp
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # 1) Probe formats (no download)
    # probe_opts = {"skip_download": True, "quiet": True}
    # with yt_dlp.YoutubeDL(probe_opts) as ydl:
    #     info = ydl.extract_info(url, download=False)
    #     german_aid = pick_german_audio(info.get("formats", []))
    #
    # if not german_aid:
    #     raise SystemExit(
    #         "No German audio track was found on this video. "
    #         "It likely only has a single (non-German) audio stream."
    #     )
    #
    # # 2) Download best MP4 video + the chosen German audio format-id
    # ydl_opts = {
    #     # best MP4 video (fallback to any mp4 if needed)
    #     "format": f"bv*[ext=mp4]+{german_aid}/bv*+{german_aid}",
    #     "merge_output_format": "mp4",
    #     "outtmpl": "%(title)s.%(ext)s",
    #     # Make sure we don’t accidentally keep extra audio tracks
    #     "audio_multistreams": False,
    # }
    #
    # with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    #     ydl.download([url])
    print("Done.")


def download_instagram_reel(url):
    L = instaloader.Instaloader(
        download_comments=False,
        download_geotags=False,
        download_pictures=False,
        download_video_thumbnails=False,
        save_metadata=False
    )

    shortcode = url.split('/')[-2]

    try:
        post = instaloader.Post.from_shortcode(L.context, shortcode)
        L.download_post(post, target=shortcode)

    except Exception as e:
        print(f'Something went wrong: {e}')


def transcribe_video(video_path, text_path):
    # Step 1: Extract and compress the audio
    # compress_audio(source_audio_path=video_test_path, target_audio_path=audio_test_path)

    # Step 2: Generate the transcription of the audio file
    # transcribe_audio(audio_path=audio_test_path, text_path=text_test_path)
    pass

