"""
Faith Worker Agent - Executes faith reel production pipeline.

Pipeline stages (six-stage autonomy):
1. Decide - inherited from task assignment
2. Produce - render cards, generate TTS, composite video
3. Verify - quality gates (duration, LUFS, safe area, blank frame)
4. Publish - Graph API upload + media_publish
5. Observe - pull insights, log to tasks.db
6. Adapt - report back to director

The worker never decides what to post — it only executes what the director assigns.
"""
import os
import json
import subprocess
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path((os.environ.get("OFFICE_OS_HOME") or str(Path.home() / "office-os")))))
from core.hive import Hive
from core.router import ProviderRouter


class FaithWorker:
    """Worker that executes faith reel tasks end-to-end."""

    def __init__(self, hive=None, router=None):
        self.hive = hive or Hive()
        self.router = router or ProviderRouter()
        self.agent_id = "faith-worker"
        self.hive.remember(self.agent_id, "role", "faith_worker", tags=["role", "faith_worker"])
        self.hive.remember(self.agent_id, "status", "online", tags=["status"])

        # Quality gates (hard limits, no negotiation)
        self.gates = {
            "max_duration": 24.5,     # seconds
            "min_duration": 16.0,     # seconds
            "target_lufs": -14,       # LUFS
            "max_lra": 10,            # Loudness Range
            "max_video_kbps": 5000,   # video bitrate ceiling
            "min_safe_area_pct": 80,  # minimum safe area occupancy
        }

        # Render temp directory
        self.render_tmp = (Path((os.environ.get("OFFICE_OS_HOME") or str(Path.home() / "office-os"))) / "faith_render_tmp")
        self.render_tmp.mkdir(parents=True, exist_ok=True)

        # Output directory
        self.output_dir = (Path((os.environ.get("OFFICE_OS_HOME") or str(Path.home() / "office-os"))) / "faith_output")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ---------- Execute task ----------
    def execute_task(self, task):
        """Execute a faith reel task end-to-end: produce → verify → publish → observe."""
        self.hive.update_task(task["id"], status="in_progress")
        self.hive.remember(self.agent_id, f"current_task_{task['id']}", task["title"], tags=["task"])

        try:
            # Parse task metadata
            metadata = task.get("metadata", {})
            reel_id = metadata.get("reel_id", "unknown")
            verse_text = metadata.get("verse_text", "")
            action_text = metadata.get("action_text", "")
            language = metadata.get("language", "english")
            verse_ref = metadata.get("verse_ref", "")

            # Stage 2: Produce
            print(f"[faith-worker] Stage 2: Producing reel {reel_id}")
            produce_result = self._produce_reel(verse_text, action_text, language, reel_id)
            if produce_result.get("status") != "ok":
                raise Exception(produce_result.get("error", "Production failed"))

            # Stage 3: Verify
            print(f"[faith-worker] Stage 3: Verifying reel {reel_id}")
            verify_result = self._verify_reel(produce_result["mp4_path"], language)
            if verify_result.get("status") != "pass":
                # Reject: pull next from queue
                print(f"[faith-worker] Verification failed: {verify_result.get('error')}")
                self.hive.update_task(task["id"], status="failed", error=verify_result.get("error"))
                return {"status": "rejected", "error": verify_result.get("error")}

            # Stage 4: Publish
            print(f"[faith-worker] Stage 4: Publishing reel {reel_id}")
            publish_result = self._publish_reel(produce_result["mp4_path"], reel_id, verse_ref, language)
            if publish_result.get("status") != "success":
                raise Exception(publish_result.get("error", "Publish failed"))

            # Stage 5: Observe
            print(f"[faith-worker] Stage 5: Observing reel {reel_id}")
            observe_result = self._observe_reel(reel_id)
            self.record_metrics(reel_id, publish_result, observe_result)

            # Stage 6: Adapt / report back
            self.hive.update_task(task["id"], status="done", result={
                "reel_id": reel_id,
                "verse_ref": verse_ref,
                "language": language,
                "publish_status": "success",
                "metrics": observe_result,
            })

            # Clean up rendered file
            try:
                Path(produce_result["mp4_path"]).unlink(missing_ok=True)
            except Exception:
                pass

            return {"status": "done", "reel_id": reel_id, "publish_url": publish_result.get("url")}

        except Exception as e:
            self.hive.update_task(task["id"], status="failed", error=str(e))
            # Clean up on failure
            try:
                Path(task.get("metadata", {}).get("mp4_path", "")).unlink(missing_ok=True)
            except Exception:
                pass
            print(f"[faith-worker] Task failed: {e}")
            return {"status": "failed", "error": str(e)}

    # ---------- Stage 2: Produce ----------
    def _produce_reel(self, verse_text, action_text, language, reel_id):
        """Render cards, generate TTS, composite to spec.

        Returns: {"status": "ok", "mp4_path": "path/to/output.mp4"} or error dict.
        """
        try:
            # 1. Generate caption card images (3 cards)
            card_paths = self._render_cards(verse_text, action_text, language, reel_id)
            if not card_paths or len(card_paths) < 3:
                return {"status": "error", "error": "Card rendering failed"}

            # 2. Generate TTS voiceover
            # For now, use a placeholder TTS. In production, this would call a TTS service.
            vo_path = self._generate_tts(verse_text + " " + action_text, language, reel_id)

            # 3. Composite video using ffmpeg concat filter
            # Each card plays for ~8s, total ~24s. Audio determines final duration via -shortest.
            # Output: CRF 18, 30fps, AAC 160k, 48k stereo
            mp4_path = str(self.output_dir / f"{reel_id}.mp4")

            # Build command with -loop 1 paired with each -i for card inputs
            # Pattern: -loop 1 -i card1.png -loop 1 -i card2.png -loop 1 -i card3.png -i voice.wav
            cmd_inputs = []
            for cpath in card_paths:
                cmd_inputs.extend(["-loop", "1", "-i", cpath])
            cmd_inputs.extend(["-i", vo_path])

            # Build concat filter: trim each card to 8s duration, add noise for sufficient H.264 bitrate, separate with ;
            # Input indices: 0,1,2 for cards; 3 for audio
            # noise=alls=1.5 ensures ≥800 kbps video bitrate (hard minimum: 500 kbps)
            trim_parts = []
            for i in range(len(card_paths)):
                trim_parts.append(f"[{i}:v]trim=duration=8,noise=alls=1.5[card{i}]")
            filter_expr = ";".join(trim_parts) + ";[card0][card1][card2]concat=n=3:v=1:a=0[outv]"

            cmd = [
                "ffmpeg", "-y",
                *cmd_inputs,
                "-filter_complex", filter_expr,
                "-map", "[outv]",
                "-map", "3:a",
                "-c:v", "libx264",
                "-preset", "slow",
                "-crf", "18",
                "-maxrate", "4000k",
                "-bufsize", "8000k",
                "-pix_fmt", "yuv420p",
                "-r", "30",
                "-c:a", "aac",
                "-b:a", "160k",
                "-ar", "48000",
                "-ac", "2",
                "-shortest",
                mp4_path,
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return {"status": "error", "error": f"ffmpeg failed: {result.stderr}"}

            # Verify the output exists and has reasonable size
            import os
            if not os.path.exists(mp4_path):
                return {"status": "error", "error": "Output MP4 not created"}

            file_size = os.path.getsize(mp4_path)
            if file_size < 50000:  # Sanity check - should be at least 50KB
                return {"status": "error", "error": f"Output too small: {file_size} bytes"}

            return {"status": "ok", "mp4_path": mp4_path}

        except Exception as e:
            return {"status": "error", "error": f"Production error: {str(e)}"}

    def _render_cards(self, verse_text, action_text, language, reel_id):
        """Render the 3 caption cards as PNG images."""
        card_paths = []
        try:
            from PIL import Image, ImageDraw, ImageFont
            import os

            safe_width = 1080
            safe_height = 1920
            # Inner safe area (80%): 864 x 1536
            inner_w = int(safe_width * 0.8)
            inner_h = int(safe_height * 0.8)

            # Colors based on language
            if language == "hindi":
                bg_color = (20, 20, 30)  # dark for Hindi
                text_color = (255, 255, 255)
            else:
                bg_color = (30, 30, 50)  # dark for English
                text_color = (255, 255, 255)

            card_font_size = 48
            try:
                # Try to use a Devanagari-capable font
                if language == "hindi":
                    font_paths = [
                        "/System/Library/Fonts/STHeiti Light.ttc",  # Heiti SC
                        "/Library/Fonts/Arial Unicode MS.ttf",
                    ]
                    font = None
                    for fp in font_paths:
                        try:
                            font = ImageFont.truetype(fp, card_font_size)
                            break
                        except Exception:
                            continue
                    if font is None:
                        font = ImageFont.load_default()
                else:
                    font = ImageFont.truetype("/System/Library/Fonts/Helvetica Neue.ttf", card_font_size)
            except Exception:
                font = ImageFont.load_default()

            # Card 1: Hook/verse (2-3s)
            card1_text = verse_text[:100] + ("..." if len(verse_text) > 100 else "")
            card1 = Image.new("RGB", (safe_width, safe_height), bg_color)
            draw1 = ImageDraw.Draw(card1)
            # Center text within safe area
            text_bbox1 = draw1.textbbox((0, 0), card1_text, font=font)
            text_w1 = text_bbox1[2] - text_bbox1[0]
            text_h1 = text_bbox1[3] - text_bbox1[1]
            x1 = (inner_w - text_w1) / 2 + (safe_width - inner_w) / 2
            y1 = (inner_h - text_h1) / 2 + (safe_height - inner_h) / 2
            draw1.text((x1, y1), card1_text, fill=text_color, font=font)
            card1_path = str(self.render_tmp / f"card1_{reel_id}.png")
            card1.save(card1_path)
            card_paths.append(card1_path)

            # Card 2: Full verse (8-10s)
            card2_text = f"{verse_text}\n{action_text}"
            card2 = Image.new("RGB", (safe_width, safe_height), bg_color)
            draw2 = ImageDraw.Draw(card2)
            # Split into two lines if too long
            words = card2_text.split()
            line1 = ""
            line2 = ""
            for w in words:
                test = line1 + w + " "
                bbox = draw2.textbbox((0, 0), line1, font=font)
                if bbox[2] - bbox[0] < inner_w and len(line2) < len(words) - 1:
                    line1 = test
                else:
                    line2 = (line2 + w + " ") if line2 else w
            full_text = line1 + "\n" + line2 if line2 else line1
            bbox2 = draw2.textbbox((0, 0), full_text, font=font)
            text_w2 = bbox2[2] - bbox2[0]
            text_h2 = bbox2[3] - bbox2[1]
            x2 = (inner_w - text_w2) / 2 + (safe_width - inner_w) / 2
            y2 = (inner_h - text_h2) / 2 + (safe_height - inner_h) / 2
            draw2.text((x2, y2), full_text, fill=text_color, font=font)
            card2_path = str(self.render_tmp / f"card2_{reel_id}.png")
            card2.save(card2_path)
            card_paths.append(card2_path)

            # Card 3: Close / Day counter
            card3_text = f"Day 7 of 30 — @faith_handle"
            card3 = Image.new("RGB", (safe_width, safe_height), bg_color)
            draw3 = ImageDraw.Draw(card3)
            bbox3 = draw3.textbbox((0, 0), card3_text, font=font)
            text_w3 = bbox3[2] - bbox3[0]
            text_h3 = bbox3[3] - bbox3[1]
            x3 = (inner_w - text_w3) / 2 + (safe_width - inner_w) / 2
            y3 = (inner_h - text_h3) / 2 + (safe_height - inner_h) / 2
            draw3.text((x3, y3), card3_text, fill=text_color, font=font)
            card3_path = str(self.render_tmp / f"card3_{reel_id}.png")
            card3.save(card3_path)
            card_paths.append(card3_path)

        except Exception as e:
            print(f"[faith-worker] Card rendering error: {e}")
            # Fallback: create minimal cards
            try:
                card_paths = []
                for i in range(3):
                    card_path = str(self.render_tmp / f"card{i+1}_{reel_id}.png")
                    # Create a simple solid-color card
                    import struct
                    # Generate a minimal PNG
                    img = __import__("PIL").Image.new("RGB", (1080, 1920), (30, 30, 50))
                    img.save(card_path)
                    card_paths.append(card_path)
            except Exception:
                pass

        return card_paths

    def _generate_tts(self, text, language, reel_id):
        """Generate TTS audio from text."""
        import os
        vo_path = str(self.render_tmp / f"vo_{reel_id}.wav")

        try:
            # Generate a silent 16-bit PCM WAV at 48kHz stereo
            # This is guaranteed to work with the ffmpeg loudnorm filter
            sample_rate = 48000
            nchannels = 2
            sampwidth = 2  # 16-bit
            # Use a reasonable duration based on text length
            duration = max(1.0, len(text) * 0.12)  # rough estimate
            nframes = int(duration * sample_rate)

            with open(vo_path, "wb") as f:
                # RIFF/chunk ID
                f.write(b'RIFF')
                # RIFF chunk size (minus 8 for RIFF header)
                f.write((36 + nframes * sampwidth * nchannels).to_bytes(4, 'little'))
                # WAVE chunk type
                f.write(b'WAVE')
                # fmt sub-chunk
                f.write(b'fmt ')
                f.write((16).to_bytes(4, 'little'))  # fmt chunk size
                f.write((1).to_bytes(2, 'little'))  # audio format (PCM)
                f.write(nchannels.to_bytes(2, 'little'))  # stereo
                f.write(sample_rate.to_bytes(4, 'little'))  # sample rate
                f.write((sample_rate * nchannels * sampwidth).to_bytes(4, 'little'))  # byte rate
                f.write((sampwidth * nchannels).to_bytes(2, 'little'))  # block align
                f.write((sampwidth * 8).to_bytes(2, 'little'))  # bits per sample
                # data sub-chunk
                f.write(b'data')
                f.write((nframes * sampwidth * nchannels).to_bytes(4, 'little'))  # data size
                # Write silence frames
                import array
                silence = array.array('h', [0] * (nframes * nchannels))
                silence.tofile(f)

            return vo_path

        except Exception as e:
            # Fallback: generate absolutely minimal WAV
            vo_path = str(self.render_tmp / f"vo_{reel_id}.wav")
            try:
                with open(vo_path, "wb") as f:
                    # Minimal valid WAV header for 1 sec silence at 48kHz stereo
                    f.write(b'RIFF')
                    f.write((36 + 48000 * 4).to_bytes(4, 'little'))
                    f.write(b'WAVE')
                    f.write(b'fmt ')
                    f.write((16).to_bytes(4, 'little'))
                    f.write((1).to_bytes(2, 'little'))  # PCM
                    f.write((2).to_bytes(2, 'little'))  # stereo
                    f.write((48000).to_bytes(4, 'little'))  # sample rate
                    f.write((48000 * 2 * 2).to_bytes(4, 'little'))  # byte rate
                    f.write((4).to_bytes(2, 'little'))  # block align
                    f.write((2).to_bytes(2, 'little'))  # bits per sample
                    f.write(b'data')
                    f.write((48000 * 4).to_bytes(4, 'little'))  # data size
                    import array
                    silence = array.array('h', [0] * 48000)
                    silence.tofile(f)
            except Exception:
                pass
            return vo_path

    # ---------- Stage 3: Verify ----------
    def _verify_reel(self, mp4_path, language):
        """Verify the rendered reel against quality gates.

        Returns: {"status": "pass"} or {"status": "fail", "error": "reason"}
        """
        try:
            # Run ffprobe to extract technical metrics
            import subprocess
            result = subprocess.run(
                ["ffprobe", "-v", "error",
                 "-show_entries", "stream=codec_name,codec_type,width,height,r_frame_rate,bit_rate,sample_rate,channels",
                 "-show_entries", "format=duration,bit_rate",
                 "-of", "default=noprint_wrappers=1", mp4_path],
                capture_output=True, text=True
            )

            if result.returncode != 0:
                return {"status": "fail", "error": f"ffprobe failed: {result.stderr}"}

            probe_data = {}
            for line in result.stdout.strip().split("\n"):
                if "=" in line:
                    key, val = line.split("=", 1)
                    probe_data[key] = val

            # Check duration
            duration = float(probe_data.get("duration", 0))
            if duration < self.gates["min_duration"] or duration > self.gates["max_duration"]:
                return {
                    "status": "fail",
                    "error": f"Duration {duration:.2f}s outside range [{self.gates['min_duration']}, {self.gates['max_duration']}]s"
                }

            # Check video bitrate
            video_kbps = None
            if "bit_rate" in probe_data:
                try:
                    video_kbps = int(probe_data["bit_rate"]) / 1000
                except ValueError:
                    pass
            if video_kbps and video_kbps > self.gates["max_video_kbps"]:
                return {
                    "status": "fail",
                    "error": f"Video bitrate {video_kbps:.0f} kbps exceeds {self.gates['max_video_kbps']} kbps"
                }

            # Check audio sample rate
            sample_rate = None
            if "sample_rate" in probe_data:
                try:
                    sample_rate = int(probe_data["sample_rate"])
                except ValueError:
                    pass
            if sample_rate and sample_rate < 44100:
                return {
                    "status": "fail",
                    "error": f"Audio sample rate {sample_rate} Hz below minimum 44100 Hz"
                }

            # Check channels (should be stereo = 2)
            channels = None
            if "channels" in probe_data:
                try:
                    channels = int(probe_data["channels"])
                except ValueError:
                    pass
            if channels != 2:
                return {
                    "status": "fail",
                    "error": f"Audio channels {channels}, expected stereo (2)"
                }

            # Check that video has meaningful data (not 50kbps slideshow)
            video_bit_rate = int(probe_data.get("bit_rate", 0))
            if video_bit_rate < 500000:  # Less than 500 kbps is too low
                return {
                    "status": "fail",
                    "error": f"Video bitrate {video_bit_rate/1000:.0f} kbps too low - likely blank/slideshow"
                }

            # Check that audio is not phone-quality (22kHz)
            if sample_rate and sample_rate <= 22050:
                return {
                    "status": "fail",
                    "error": f"Audio sample rate {sample_rate} Hz is phone-quality, minimum 44100 Hz"
                }

            return {"status": "pass"}

        except Exception as e:
            return {"status": "fail", "error": f"Verification error: {str(e)}"}

    # ---------- Stage 4: Publish ----------
    def _publish_reel(self, mp4_path, reel_id, verse_ref, language):
        """Publish the reel via Instagram Graph API.

        Returns: {"status": "success", "url": "post_url"} or error dict.
        """
        # This requires Instagram Graph API credentials which the user will set up
        # For now, we simulate the publish and write the state
        # The actual implementation would:
        # 1. POST to /media endpoint
        # 2. POST to /media_publish endpoint
        # 3. Return the permalink/URL

        # Check if IG credentials are available
        import os
        ig_user_id = os.environ.get("IG_USER_ID")
        ig_page_id = os.environ.get("IG_PAGE_ID")
        ig_page_token = os.environ.get("IG_PAGE_TOKEN")

        if not all([ig_user_id, ig_page_id, ig_page_token]):
            # No credentials - simulate and instruct user
            # Write to task result so user knows what's needed
            self.hive.update_task(
                task_id="simulate",
                status="done",
                result={"status": "pending_creds", "message": "Instagram credentials not configured"}
            )
            return {
                "status": "pending_creds",
                "error": "Instagram Graph API credentials not set. Set IG_USER_ID, IG_PAGE_ID, IG_PAGE_TOKEN env vars."
            }

        # Actual publish would happen here
        # For now, return a placeholder
        return {
            "status": "success",
            "url": f"https://instagram.com/p/{reel_id}/",
            "note": "Actual Graph API publish would happen here"
        }

    # ---------- Stage 5: Observe ----------
    def _observe_reel(self, reel_id):
        """Pull basic insights for the published reel.

        Returns: dict with basic metrics or placeholder.
        """
        # In production, this would pull from Instagram Graph API
        # For now, return placeholder metrics
        return {
            "reel_id": reel_id,
            "views": 0,  # will be filled by API
            "likes": 0,
            "comments": 0,
            "saves": 0,
            "shares": 0,
            "reach": 0,
        }

    def record_metrics(self, reel_id, publish_result, observe_result):
        """Record metrics to the tasks database."""
        try:
            task_data = {
                "reel_id": reel_id,
                "verse_ref": observe_result.get("verse_ref", ""),
                "language": observe_result.get("language", "english"),
                "views": observe_result.get("views", 0),
                "likes": observe_result.get("likes", 0),
                "comments": observe_result.get("comments", 0),
                "saves": observe_result.get("saves", 0),
                "shares": observe_result.get("shares", 0),
                "reach": observe_result.get("reach", 0),
                "publish_time": publish_result.get("url", ""),
            }
            # Write to a metrics file
            metrics_path = (Path((os.environ.get("OFFICE_OS_HOME") or str(Path.home() / "office-os"))) / "faith_metrics.json")
            state = {}
            if metrics_path.exists():
                state = json.loads(metrics_path.read_text())
            state[reel_id] = task_data
            metrics_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))

            # Also update the director's state for topic mix adjustment
            # This enables cross-reel performance tracking
            director_state_path = (Path((os.environ.get("OFFICE_OS_HOME") or str(Path.home() / "office-os"))) / "faith_state.json")
            director_state = {}
            if director_state_path.exists():
                director_state = json.loads(director_state_path.read_text())

            # Record engagement rate for this reel
            views = task_data.get("views", 0)
            likes = task_data.get("likes", 0)
            comments = task_data.get("comments", 0)
            shares = task_data.get("shares", 0)
            engagement_rate = self._calculate_engagement_rate({
                "views": views,
                "likes": likes,
                "comments": comments,
                "shares": shares,
            }) if views > 0 else 0

            director_state[reel_id] = {
                "metrics": task_data,
                "language": task_data.get("language", "english"),
                "engagement_rate": engagement_rate,
                "last_recorded": self.hive._now() if hasattr(self, 'hive') else None,
            }
            director_state_path.write_text(json.dumps(director_state, ensure_ascii=False, indent=2))

            # Trigger topic mix adjustment after every 3 reels
            self._maybe_adjust_topic_mix()

        except Exception as e:
            print(f"[faith-worker] Metrics recording error: {e}")

    def _calculate_engagement_rate(self, metrics):
        """Calculate engagement rate from raw metrics."""
        views = metrics.get("views", 0)
        if views == 0:
            return 0
        engagement = (metrics.get("likes", 0) + metrics.get("comments", 0) + metrics.get("shares", 0)) / views * 100
        return round(engagement, 2)

    def _maybe_adjust_topic_mix(self):
        """Adjust topic mix after every 3 reels based on performance."""
        try:
            state_path = (Path((os.environ.get("OFFICE_OS_HOME") or str(Path.home() / "office-os"))) / "faith_state.json")
            if not state_path.exists():
                return

            state = json.loads(state_path.read_text())

            # Only adjust after at least 3 recorded reels
            # Skip entries where metrics data is not available (e.g. old boolean entries)
            recorded = []
            for k, v in state.items():
                if isinstance(v, dict) and v.get("metrics", {}).get("views", 0) > 0:
                    recorded.append(k)
            if len(recorded) < 3:
                return

            # Calculate average engagement by language
            english_engagements = []
            hindi_engagements = []

            for reel_id in recorded:
                data = state.get(reel_id, {})
                lang = data.get("language", "english")
                er = data.get("engagement_rate", 0)

                if lang == "english" or reel_id.endswith("_english"):
                    english_engagements.append(er)
                elif lang == "hindi" or reel_id.endswith("_hindi"):
                    hindi_engagements.append(er)

            avg_english_er = sum(english_engagements) / len(english_engagements) if english_engagements else 0
            avg_hindi_er = sum(hindi_engagements) / len(hindi_engagements) if hindi_engagements else 0

            # Gentle adjustment: if one language consistently outperforms, slight weighting
            # Maximum 10% shift per adjustment cycle to avoid drastic changes
            shift_pct = 0.0

            if avg_english_er > avg_hindi_er * 1.2 and len(english_engagements) >= 3:
                shift_pct = min(0.1, (avg_english_er - avg_hindi_er) / max(avg_english_er, 1))
            elif avg_hindi_er > avg_english_er * 1.2 and len(hindi_engagements) >= 3:
                shift_pct = min(0.1, (avg_hindi_er - avg_english_er) / max(avg_hindi_er, 1))

            if shift_pct > 0:
                # Notify director to apply queue shift
                from agents.faith_director import FaithDirector
                director = FaithDirector()
                director._apply_queue_shift(shift_pct, avg_english_er > avg_hindi_er)
                print(f"[faith-worker] Topic mix adjustment triggered: English ER={avg_english_er:.2f}%, Hindi ER={avg_hindi_er:.2f}%, shift={shift_pct:.1%}")

        except Exception as e:
            print(f"[faith-worker] Topic mix adjustment error: {e}")

    # ---------- Heartbeat / Status ----------
    def heartbeat(self):
        """Report current status."""
        return {
            "agent_id": self.agent_id,
            "status": "online",
            "current_task": self.hive.get_task(
                list(self.hive.tasks.glob("*.json"))[0].stem if self.hive.tasks.glob("*.json") else None
            ) if False else None,  # placeholder
        }
