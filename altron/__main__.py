from __future__ import annotations

import argparse
import sys

from altron.graph import AltronCore
from altron.settings import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="altron", description="ALTRON core")
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="ALTRON command core + OpenAI-compatible API")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)

    chat = sub.add_parser("chat", help="One-shot CLI turn")
    chat.add_argument("text", nargs="+")

    app_cmd = sub.add_parser("app", help="Desktop window around the command core")
    app_cmd.add_argument("--host", default=None)
    app_cmd.add_argument("--port", type=int, default=None)

    sub.add_parser("voice", help="Voice face notes (mic is in the command core UI)")

    args = parser.parse_args(argv)
    settings = get_settings()

    if args.cmd == "serve":
        import uvicorn

        host = args.host or settings.altron_host
        port = args.port or settings.altron_port
        uvicorn.run("altron.server:app", host=host, port=port, reload=False)
        return 0

    if args.cmd == "app":
        from altron.desktop import run_app

        patched = settings.model_copy(
            update={
                "altron_host": args.host or settings.altron_host,
                "altron_port": args.port or settings.altron_port,
            }
        )
        return run_app(patched)

    if args.cmd == "voice":
        from altron.voice import run_voice

        return run_voice(settings)

    if args.cmd == "chat":
        core = AltronCore(settings)
        text = " ".join(args.text)
        state = core.run([{"role": "user", "content": text}])
        print(state.get("reply") or "")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
