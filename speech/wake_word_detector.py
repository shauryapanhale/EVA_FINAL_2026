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
        self.CHUNK = 512  # Smaller chunks for faster response
        self.BUFFER_DURATION = 2.0  # Process 2-second sliding windows
        self.CHUNKS_PER_BUFFER = int(self.RATE * self.BUFFER_DURATION / self.CHUNK)
        
        try:
            logger.info(f"Initializing faster_whisper with model: '{self.model_size}'")
            # Enable VAD for better speech detection
            self.model = WhisperModel(
                self.model_size, 
                device="cpu", 
                compute_type="int8"
            )
            logger.info(f"✓ faster_whisper initialized (model: '{self.model_size}')")

            self.pa = pyaudio.PyAudio()
            self.audio_stream = None
            # Use deque for efficient sliding window
            self.audio_buffer = deque(maxlen=self.CHUNKS_PER_BUFFER)
            self.last_detection_time = 0
            self.detection_cooldown = 2.0  # Prevent rapid re-detections

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
            # Read audio chunk
            data = self.audio_stream.read(self.CHUNK, exception_on_overflow=False)
            audio_chunk = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            
            # Add to sliding window buffer
            self.audio_buffer.append(audio_chunk)

            # Only process when buffer is full
            if len(self.audio_buffer) < self.CHUNKS_PER_BUFFER:
                return False

            # Check cooldown period to prevent duplicate detections
            current_time = time.time()
            if current_time - self.last_detection_time < self.detection_cooldown:
                return False

            # Concatenate buffer for processing
            audio_data = np.concatenate(list(self.audio_buffer))
            
            # Quick energy check to skip silent audio
            rms_energy = self._compute_rms(audio_data)
            if rms_energy < 0.01:  # Silence threshold
                return False

            # Transcribe with VAD enabled
            segments, info = self.model.transcribe(
                audio_data,
                beam_size=1,  # Faster with beam_size=1
                language="en",
                vad_filter=True,  # Enable VAD to filter non-speech
                vad_parameters=dict(
                    threshold=0.5,  # Adjust based on environment
                    min_speech_duration_ms=250,
                    max_speech_duration_s=2.0,
                    min_silence_duration_ms=100
                ),
                condition_on_previous_text=False,  # Faster processing
                temperature=0.0  # Deterministic output
            )

            # Check for wake word in transcription
            for segment in segments:
                transcribed_text = segment.text.lower().strip()
                logger.debug(f"Transcribed: '{transcribed_text}'")
                
                # Flexible wake word matching
                if self.wake_word in transcribed_text or \
                   self._fuzzy_match(transcribed_text, self.wake_word):
                    logger.info(f"🎯 WAKE WORD '{self.wake_word.upper()}' DETECTED!")
                    logger.info(f"   Transcribed: '{segment.text}'")
                    self.last_detection_time = current_time
                    self.audio_buffer.clear()  # Clear buffer after detection
                    return True

            return False

        except Exception as e:
            logger.error(f"Listen error: {e}")
            return False

    def _fuzzy_match(self, text, wake_word):
        """Fuzzy matching for common misrecognitions (e.g., 'even' → 'eva')"""
        # Common misrecognitions for "eva"
        variants = ["even", "eva", "ava", "ever", "ebba"]
        return any(variant in text for variant in variants)

    def detect(self, timeout=None):
        """
        Continuously listens until wake word is detected or timeout occurs
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
