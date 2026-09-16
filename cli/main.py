from __future__ import annotations

import argparse
import asyncio
import sys

from rich.console import Console
from rich.markdown import Markdown

from backend.agent.engine import run_agent


async def _run(prompt: str) -> int:
    console = Console()
    text = ""
    cancel = asyncio.Event()
    agen = run_agent(prompt, cancel_event=cancel)
    try:
        async for event in agen:
            if event.event == "tool_start":
                console.print(f"[cyan]→ {event.name}[/] {event.args}")
            elif event.event == "tool_end":
                tone = "green" if event.status == "ok" else "red"
                console.print(f"[{tone}]✓ {event.name} {event.status}[/] {event.preview}")
            elif event.event == "token":
                text += event.text
                console.print(event.text, end="")
            elif event.event == "error":
                console.print(f"\n[red]{event.message}[/]")
            elif event.event == "done":
                if text.strip():
                    console.print()
                    console.print(Markdown(text))
                console.print(f"[dim]done ({event.status})[/]")
    except KeyboardInterrupt:
        cancel.set()
        await agen.aclose()
        console.print("\n[yellow]cancelled[/]")
        return 1
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Crawler Agent CLI")
    parser.add_argument("prompt", nargs="?", help="user message")
    args = parser.parse_args(argv)
    prompt = args.prompt or input("prompt> ").strip()
    if not prompt:
        raise SystemExit("empty prompt")
    raise SystemExit(asyncio.run(_run(prompt)))


if __name__ == "__main__":
    main()
