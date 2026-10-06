from openai import OpenAI, APIStatusError

from altron.settings import get_settings

CANDIDATES = [
    "meta/llama-3.3-70b-instruct",
    "meta/llama-4-maverick-17b-128e-instruct",
    "qwen/qwen3-next-80b-a3b-instruct",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/llama-3.1-nemotron-70b-instruct",
    "mistralai/mistral-nemotron",
    "deepseek-ai/deepseek-v4-flash",
    "stepfun-ai/step-3.7-flash",
    "meta/llama-3.1-70b-instruct",
]


def main() -> None:
    settings = get_settings()
    key = settings.api_keys[0]
    client = OpenAI(api_key=key, base_url=settings.nvidia_nim_api_base.rstrip("/"), timeout=40, max_retries=0)
    for model in CANDIDATES:
        try:
            res = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Say OK"}],
                max_tokens=8,
            )
            text = (res.choices[0].message.content or "").replace("\n", " ")[:80]
            print(f"LIVE {model} :: {text}")
            return
        except APIStatusError as exc:
            print(f"DEAD {model} :: {exc.status_code}")
        except Exception as exc:  # noqa: BLE001
            print(f"DEAD {model} :: {type(exc).__name__}")
    print("NONE_LIVE")


if __name__ == "__main__":
    main()
