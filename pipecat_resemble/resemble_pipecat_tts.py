#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import asyncio
import base64
import json
import os
import pyaudio
from typing import AsyncGenerator, Optional

import websockets
from dotenv import load_dotenv
from loguru import logger
from pydantic import BaseModel

from pipecat.frames.frames import Frame, TTSAudioRawFrame, TTSStartedFrame, TTSStoppedFrame, ErrorFrame, EndFrame
from pipecat.services.tts_service import TTSService

# Audio configuration
SAMPLE_RATE = 48000
CHUNK_SIZE = 1024
AUDIO_FORMAT = pyaudio.paInt16

class ResembleTTSService(TTSService):
    class InputParams(BaseModel):
        speed: Optional[float] = None
        pitch: Optional[float] = None
        no_audio_header: bool = True

    def __init__(
        self,
        *,
        api_key: str,
        voice_uuid: str,
        project_uuid: str,
        params: InputParams = InputParams(),
        **kwargs
    ):
        super().__init__(
            sample_rate=SAMPLE_RATE,
            **kwargs
        )
        self._api_key = api_key
        self._voice_uuid = voice_uuid
        self._project_uuid = project_uuid
        self._params = params
        self._websocket = None
        self._request_id = 0
        
        # Initialize PyAudio
        self._pyaudio = pyaudio.PyAudio()
        self._stream = self._pyaudio.open(
            format=AUDIO_FORMAT,
            channels=1,
            rate=SAMPLE_RATE,
            output=True,
            frames_per_buffer=CHUNK_SIZE
        )

    def can_generate_metrics(self) -> bool:
        return True

    async def run_tts(self, text: str) -> AsyncGenerator[Frame, None]:
        logger.debug(f"Generating TTS for: {text}")
        
        try:
            # Connect to WebSocket
            self._websocket = await websockets.connect(
                "wss://websocket.cluster.resemble.ai/stream",
                extra_headers={"Authorization": f"Bearer {self._api_key}"},
                ping_interval=5,
                ping_timeout=20
            )

            await self.start_ttfb_metrics()
            self._request_id += 1

            # Prepare request
            request = {
                "voice_uuid": self._voice_uuid,
                "project_uuid": self._project_uuid,
                "data": text,
                "sample_rate": SAMPLE_RATE,
                "precision": "PCM_16",
                "no_audio_header": self._params.no_audio_header,
                "request_id": self._request_id,
                "binary_response": False
            }

            # Add optional parameters
            if self._params.speed is not None:
                request["speed"] = self._params.speed
            if self._params.pitch is not None:
                request["pitch"] = self._params.pitch

            await self._websocket.send(json.dumps(request))
            await self.start_tts_usage_metrics(text)
            yield TTSStartedFrame()

            while True:
                message = await self._websocket.recv()
                data = json.loads(message)

                if data.get("request_id") != self._request_id:
                    continue

                if data["type"] == "audio":
                    await self.stop_ttfb_metrics()
                    audio = base64.b64decode(data["audio_content"])
                    self._stream.write(audio)  # Play audio immediately
                    yield TTSAudioRawFrame(audio, SAMPLE_RATE, 1)

                elif data["type"] == "audio_end":
                    yield TTSStoppedFrame()
                    break

                elif data["type"] == "error":
                    error_msg = data.get("message", "Unknown error")
                    yield ErrorFrame(error=f"API Error: {error_msg}")
                    break

        except websockets.ConnectionClosed:
            yield ErrorFrame(error="Connection closed unexpectedly")
        except Exception as e:
            logger.error(f"Error during TTS: {e}")
            yield ErrorFrame(error=str(e))
        finally:
            self._request_id = 0

    async def stop(self, frame: Optional[Frame] = None):
        """Clean up resources with proper Pipecat frame handling"""
        if self._websocket:
            await self._websocket.close()
        if hasattr(self, '_stream'):
            self._stream.stop_stream()
            self._stream.close()
        if hasattr(self, '_pyaudio'):
            self._pyaudio.terminate()
        # Call parent with EndFrame if none provided
        await super().stop(frame if frame else EndFrame())


# -----------------------------------------------------------------------------
# Test Code
# -----------------------------------------------------------------------------

async def test_resemble_tts():
    """Test with guaranteed audio playback"""
    load_dotenv()
    api_key = os.getenv("RESEMBLE_API_KEY")
    voice_uuid = "55592656"  # Replace with your voice UUID
    project_uuid = "ca6f4989"  # Replace with your project UUID

    if not api_key:
        raise ValueError("RESEMBLE_API_KEY not found in .env file")

    tts = ResembleTTSService(
        api_key=api_key,
        voice_uuid=voice_uuid,
        project_uuid=project_uuid
    )

    try:
        text = input("Enter text: ")
        
        async for frame in tts.run_tts(text):
            if isinstance(frame, TTSStartedFrame):
                print("🎙️ TTS started")
            elif isinstance(frame, TTSStoppedFrame):
                print("✅ Playback completed")
            elif isinstance(frame, ErrorFrame):
                print(f"❌ Error: {frame.error}")

    except Exception as e:
        print(f"💥 Test failed: {e}")
    finally:
        await tts.stop(EndFrame())  # Explicitly pass EndFrame here
        print("🧹 Cleaned up resources")


if __name__ == "__main__":
    asyncio.run(test_resemble_tts())