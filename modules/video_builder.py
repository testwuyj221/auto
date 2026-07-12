"""
Assembles the final vertical (1080x1920) Short:
- Crops/scales each beat's stock clip to fill the frame
- Times each clip to match how long its voiceover beat takes
- Lays the single voiceover track under the whole video
- Mixes in a quiet looping background music bed (see MUSIC_DIR below)
- Burns in word-grouped captions synced via edge-tts's own word-boundary timestamps
"""
import os
import random
from moviepy.editor import (
    VideoFileClip, AudioFileClip, CompositeVideoClip, CompositeAudioClip,
    TextClip, concatenate_videoclips, afx,
)

W, H = 2160, 3840  # 4K vertical. NOTE: most Pexels stock clips aren't native 4K
                    # vertical, so lower-res source clips get upscaled to fill this
                    # frame rather than adding real extra detail. Also significantly
                    # increases render time — see build_video()'s preset/timeout notes.

# Drop your own royalty-free .mp3 tracks in here (YouTube Audio Library,
# Pixabay Music, etc. -- anything cleared for monetized use). One is picked
# at random per video so back-to-back uploads don't feel identical. If this
# folder is empty or missing, music is skipped entirely -- never blocks a run.
MUSIC_DIR = "assets/music"
MUSIC_VOLUME = 0.10  # ~ -20dB under the narration -- audible bed, never competes with the voice
MUSIC_FADEOUT_SEC = 1.5


def _pick_background_music(music_dir=MUSIC_DIR):
    if not os.path.isdir(music_dir):
        return None
    tracks = [f for f in os.listdir(music_dir) if f.lower().endswith((".mp3", ".wav", ".m4a"))]
    if not tracks:
        return None
    return os.path.join(music_dir, random.choice(tracks))


def _build_music_track(total_duration, music_dir=MUSIC_DIR):
    """Returns a low-volume AudioClip looped/trimmed to total_duration, or
    None if no music files are available (pipeline still works fine without it)."""
    track_path = _pick_background_music(music_dir)
    if not track_path:
        print("[video_builder] No background music found in assets/music/ -- skipping (this is fine).")
        return None

    try:
        music = AudioFileClip(track_path)
        if music.duration < total_duration:
            music = afx.audio_loop(music, duration=total_duration)
        else:
            music = music.subclip(0, total_duration)
        music = music.fx(afx.volumex, MUSIC_VOLUME)
        if total_duration > MUSIC_FADEOUT_SEC:
            music = music.fx(afx.audio_fadeout, MUSIC_FADEOUT_SEC)
        return music
    except Exception as e:
        # Never let a bad/corrupt music file break the whole video render.
        print(f"[video_builder] Background music failed to load ({track_path}): {e}. Skipping music.")
        return None


def _fit_clip_to_frame(clip, duration):
    """Scale + center-crop a clip to fill a 1080x1920 frame for `duration` seconds."""
    clip = clip.subclip(0, min(duration, clip.duration)) if clip.duration > duration else clip

    # scale so the clip covers the frame, then center-crop the overflow
    scale = max(W / clip.w, H / clip.h)
    clip = clip.resize(scale)
    x_center, y_center = clip.w / 2, clip.h / 2
    clip = clip.crop(x_center=x_center, y_center=y_center, width=W, height=H)

    # loop short clips to fill the needed duration
    if clip.duration < duration:
        n_loops = int(duration // clip.duration) + 1
        clip = concatenate_videoclips([clip] * n_loops).subclip(0, duration)

    return clip.set_duration(duration)


def _caption_clip(chunk):
    txt = TextClip(
        chunk["text"].upper(),
        fontsize=140,  # scaled 2x for the 4K frame (was 70 at 1080x1920)
        color="white",
        stroke_color="black",
        stroke_width=6,
        font="Arial-Bold",
        method="caption",
        size=(W - 240, None),
    )
    txt = txt.set_start(chunk["start"]).set_end(chunk["end"])
    txt = txt.set_position(("center", H * 0.72))
    return txt


def build_video(beats, clip_paths, voiceover_path, caption_chunks, out_path="output/final_short.mp4"):
    """
    beats: list of script beat dicts (used only for approximate per-beat duration split)
    clip_paths: list of local video file paths, same order as beats (None entries are skipped)
    voiceover_path: path to the single narration audio track
    caption_chunks: from captions.group_words_into_caption_chunks()
    """
    narration = AudioFileClip(voiceover_path)
    total_duration = narration.duration

    valid_beats = [(b, p) for b, p in zip(beats, clip_paths) if p]
    if not valid_beats:
        raise RuntimeError("No clips available to build video — check asset_fetcher results.")

    per_beat_duration = total_duration / len(valid_beats)

    segments = []
    for beat, path in valid_beats:
        raw = VideoFileClip(path).without_audio()
        segments.append(_fit_clip_to_frame(raw, per_beat_duration))

    video = concatenate_videoclips(segments, method="compose").set_duration(total_duration)

    music = _build_music_track(total_duration)
    if music is not None:
        final_audio = CompositeAudioClip([narration, music]).set_duration(total_duration)
    else:
        final_audio = narration
    video = video.set_audio(final_audio)

    caption_layers = [_caption_clip(c) for c in caption_chunks]

    final = CompositeVideoClip([video, *caption_layers], size=(W, H)).set_duration(total_duration)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    # "veryfast" instead of "ultrafast": still fast enough for CI, but noticeably
    # cleaner encode at 4K than ultrafast's heavy compression artifacts. bitrate is
    # set explicitly since libx264's default bitrate is tuned for 1080p, not 4K.
    final.write_videofile(out_path, fps=30, codec="libx264", audio_codec="aac",
                          threads=2, preset="veryfast", bitrate="16000k")

    for s in segments:
        s.close()
    narration.close()
    if music is not None:
        music.close()

    return out_path
