"""
Wake Word Detection using faster_whisper with VAD optimization
"""

import logging
import pyaudio
import numpy as np
import time
from faster_whisper import WhisperModel
from collections import deque

logger = logging.getLogger("WakeWordDetector")

class WakeWordDetector:
    """Optimized faster_whisper-based wake word detector"""

    def __init__(self, wake_word="eva", model_size="tiny.en", sensitivity=0.7):
        """Initialize faster_whisper with VAD"""
        self.wake_word = wake_word.lower()
        self.model_size = model_size
        self.is_running = False
        self.sensitivity = sensitivity

        # Audio configuration
        self.RATE = 16000
        self.CHUNK = 1024               # Slightly larger chunks = more stable reads
        self.BUFFER_DURATION = 2.0      # 2-second sliding window
        self.CHUNKS_PER_BUFFER = int(self.RATE * self.BUFFER_DURATION / self.CHUNK)

        try:
            logger.info(f"Initializing faster_whisper with model: '{self.model_size}'")
            self.model = WhisperModel(
                self.model_size,
                device="cpu",
                compute_type="int8"
            )
            logger.info(f"✓ faster_whisper initialized (model: '{self.model_size}')")

            self.pa = pyaudio.PyAudio()
            self.audio_stream = None

            # FIX 1: Use a plain list as a rolling buffer, not a deque with maxlen.
            # We manually trim it so we control when it's "full" vs cleared.
            self.audio_buffer = []
            self.last_detection_time = 0
            self.detection_cooldown = 2.0   # seconds between detections

        except Exception as e:
            logger.critical(f"❌ faster_whisper initialization FAILED: {e}")
            raise RuntimeError(f"faster_whisper MUST work. Error: {e}")

    def start(self):
        """Start audio stream"""
        try:
            logger.info("Opening audio stream...")
            self.audio_stream = self.pa.open(
                rate=self.RATE,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=self.CHUNK,
                stream_callback=None
            )
            self.is_running = True
            logger.info("🎤 Listening for wake word...")
            logger.info(f"✓ Audio stream started (say '{self.wake_word.upper()}' clearly)")

        except Exception as e:
            logger.critical(f"❌ Failed to start audio: {e}")
            raise RuntimeError(f"Audio stream failed: {e}")

    def _compute_rms(self, audio_data):
        """Calculate RMS energy to detect if audio contains speech"""
        return np.sqrt(np.mean(audio_data ** 2))

    def listen(self):
        """Listen for wake word using faster_whisper with sliding window"""
        if not self.audio_stream:
            raise RuntimeError("Audio stream not started")

        try:
            # Read one chunk from the mic
            data = self.audio_stream.read(self.CHUNK, exception_on_overflow=False)
            audio_chunk = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0

            # Add chunk to buffer
            self.audio_buffer.append(audio_chunk)

            # FIX 1: Only process once we have a full buffer worth of audio
            if len(self.audio_buffer) < self.CHUNKS_PER_BUFFER:
                return False

            # FIX 2: Enforce cooldown BEFORE doing any transcription work
            current_time = time.time()
            if current_time - self.last_detection_time < self.detection_cooldown:
                # Slide the window: drop oldest chunk so we stay responsive
                self.audio_buffer.pop(0)
                return False

            # Concatenate all chunks into one array for transcription
            audio_data = np.concatenate(self.audio_buffer)

            # FIX 3: Lower silence threshold — "Eva" on a laptop mic is quiet
            # 0.002 catches normal speech; 0.01 was rejecting real speech
            rms_energy = self._compute_rms(audio_data)
            if rms_energy < 0.002:
                # Definitely silent — slide the window and move on
                self.audio_buffer.pop(0)
                return False

            # Transcribe with relaxed VAD so short words like "Eva" aren't filtered out
            segments, info = self.model.transcribe(
                audio_data,
                beam_size=1,
                language="en",
                vad_filter=True,
                vad_parameters=dict(
                    # FIX 4: Lower threshold + shorter min duration so "Eva" isn't stripped
                    threshold=0.3,              # was 0.5 — lower = less aggressive filtering
                    min_speech_duration_ms=100, # was 250 — "Eva" is ~200-300ms, don't cut it
                    max_speech_duration_s=2.0,
                    min_silence_duration_ms=200
                ),
                condition_on_previous_text=False,
                temperature=0.0
            )

            # Slide the window: always drop oldest chunk after processing
            self.audio_buffer.pop(0)

            # Check for wake word in transcription
            for segment in segments:
                transcribed_text = segment.text.lower().strip()
                logger.debug(f"Transcribed: '{transcribed_text}'")

                if self.wake_word in transcribed_text or \
                   self._fuzzy_match(transcribed_text, self.wake_word):
                    logger.info(f"🎯 WAKE WORD '{self.wake_word.upper()}' DETECTED!")
                    logger.info(f"   Transcribed: '{segment.text}'")
                    self.last_detection_time = current_time
                    # FIX 5: Clear buffer after detection so stale audio isn't reprocessed
                    self.audio_buffer.clear()
                    return True

            return False

        except Exception as e:
            logger.error(f"Listen error: {e}")
            return False

    def _fuzzy_match(self, text, wake_word):
        """
        Fuzzy matching for common misrecognitions of 'eva'.
        FIX 6: Match whole words only using word boundaries, not substrings.
        'even' inside 'I'm not even sure' was triggering false positives.
        """
        # Common misrecognitions for "eva" — checked as whole words
        variants = ["eva", "ava", "eevee", "eve", "evan", "eba"]
        words_in_text = set(text.lower().split())
        return any(variant in words_in_text for variant in variants)

    def detect(self, timeout=None):
        """
        Continuously listens until wake word is detected or timeout occurs.
        """
        logger.info(f"🎤 Starting wake word detection (timeout: {timeout}s)")
        self.start()
        start_time = time.time()

        try:
            while self.is_running:
                if timeout and (time.time() - start_time) > timeout:
                    logger.warning(f"⏱️ Wake word detection timeout ({timeout}s)")
                    self.stop()
                    return False

                if self.listen():
                    logger.info("✓ Wake word detected!")
                    self.stop()
                    return True

                time.sleep(0.01)  # Small delay to prevent CPU overload

        except KeyboardInterrupt:
            logger.info("Wake word detection interrupted by user")
            self.stop()
            return False

        except Exception as e:
            logger.error(f"Detection error: {e}")
            self.stop()
            return False

        return False

    def stop(self):
        """Stop audio stream and cleanup"""
        try:
            self.is_running = False
            if self.audio_stream:
                self.audio_stream.stop_stream()
                self.audio_stream.close()
                self.audio_stream = None

            if self.pa:
                self.pa.terminate()

            logger.info("✓ Audio stream stopped")

        except Exception as e:
            logger.error(f"Error stopping detector: {e}")
