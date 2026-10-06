from __future__ import annotations

"""LiveKit Agents face harvested from agents-main: same ALTRON /v1 brain.

Default voice is the command-core mic (Web Speech). LiveKit cloud is optional.
"""

from altron.settings import Settings


def status(settings: Settings) -> dict:
    configured = bool(
        (settings.livekit_url or "").strip()
        and (settings.livekit_api_key or "").strip()
        and (settings.livekit_api_secret or "").strip()
    )
    return {
        "configured": configured,
        "url": (settings.livekit_url or "").strip(),
        "face": "browser" if not configured else "livekit+browser",
    }


def run_voice(settings: Settings) -> int:
    core = f"http://{settings.altron_host}:{settings.altron_port}/v1"
    face = f"http://{settings.altron_host}:{settings.altron_port}/"
    info = status(settings)
    print(f"Voice face: open {face} and use Mic / Hear.")
    print(f"ALTRON /v1 brain: {core}")
    if not info["configured"]:
        print("LiveKit cloud: set LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET in .env")
        print("Harvested worker shape:")
        print(f"  openai.LLM(model='altron', base_url='{core}', api_key='altron')")
        return 0
    print(f"LiveKit configured: {info['url']}")
    print("Start a LiveKit agent worker that points LLM at ALTRON /v1 (see agents-main examples).")
    print("Browser mic still works as the local face.")
    return 0
