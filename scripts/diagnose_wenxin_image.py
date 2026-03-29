from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_ENDPOINT = "https://qianfan.baidubce.com/v2/images/generations"
DEFAULT_MODEL = "qwen-image"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Diagnose Wenxin image generation API access.")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prompt", default="画一只小狗")
    parser.add_argument("--size", default="512x512")
    parser.add_argument("--n", type=int, default=1)
    parser.add_argument("--negative-prompt")
    parser.add_argument("--api-key")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    api_key = args.api_key or os.environ.get("QIANFAN_API_KEY") or os.environ.get("WENXIN_API_KEY")
    if not api_key:
        print("Missing API key. Set QIANFAN_API_KEY or pass --api-key.", file=sys.stderr)
        return 2

    payload: dict[str, object] = {
        "model": args.model,
        "prompt": args.prompt,
        "size": args.size,
        "n": args.n,
    }
    if args.negative_prompt:
        payload["negative_prompt"] = args.negative_prompt

    request = Request(
        url=args.endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    print("Request URL:", args.endpoint)
    print("Request Model:", args.model)
    print("Request Payload:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print()

    try:
        with urlopen(request, timeout=120) as response:
            body = response.read().decode("utf-8", errors="replace")
            print("HTTP Status:", response.status)
            print("Response Headers:")
            for key, value in response.headers.items():
                print(f"{key}: {value}")
            print()
            print("Response Body:")
            print(body)
            return 0
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print("HTTP Status:", exc.code)
        print("Response Headers:")
        for key, value in exc.headers.items():
            print(f"{key}: {value}")
        print()
        print("Response Body:")
        print(body)
        return 1
    except URLError as exc:
        print("Network Error:", exc, file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
