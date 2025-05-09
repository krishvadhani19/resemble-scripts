import asyncio
import base64
import time

import websockets
import json
import pyaudio
from dotenv import load_dotenv
import os

load_dotenv()

RESEMBLE_API_KEY = os.getenv("RESEMBLE_API_KEY", "Not found")

p = pyaudio.PyAudio()
stream = p.open(format=pyaudio.paInt16,
                channels=1,
                rate=48000,
                output=True)

async def listen(uri):
    async with websockets.connect(uri, extra_headers={"Authorization:": f"Bearer {RESEMBLE_API_KEY}"}, ping_interval=5, ping_timeout=20) as websocket:
        while True:
            await websocket.ping()
            user_input = input("Enter text: ")

            request = {
                "voice_uuid": "55592656",
                "project_uuid": "ca6f4989",
                "data": user_input,
                "sample_rate": 48000,
                "precision": "PCM_16",
                "no_audio_header": True
            }
            json_data = json.dumps(request)
            await websocket.send(json_data) # Send tts request

            first_byte = None
            start_time = time.time()

            while True:
                message = await websocket.recv()
                try:
                    # First try and load as json
                    data = json.loads(message)

                    if data['type'] == 'audio':
                        audio = base64.b64decode(data['audio_content'])
                        if first_byte is None:
                            first_byte = True
                            end_time = time.time()
                            print(f"TTFS: {end_time - start_time}s")
                        stream.write(audio)

                    if data['type'] == 'audio_end':
                        break

                except Exception:
                    print("Expected json but did not receive json.")

asyncio.get_event_loop().run_until_complete(
    listen("wss://websocket.cluster.resemble.ai/stream")
)