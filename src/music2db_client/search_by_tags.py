#!/usr/bin/env python3
from __future__ import annotations

import argparse
from urllib.parse import urlencode

import requests
from rich.console import Console
from rich.table import Table
from rich.text import Text


def main() -> int:
    parser = argparse.ArgumentParser(description="Search Music2DB tracks by semantic text and metadata")
    parser.add_argument("tags", nargs="?", default="", help="Semantic search text")
    parser.add_argument("-l", "--limit", type=int, default=20, help="Maximum number of results")
    parser.add_argument("-m", "--max-distance", type=float, default=0.7, help="Maximum distance for semantic search")
    parser.add_argument("--artist", default=None, help="Filter by artist")
    parser.add_argument("--album", default=None, help="Filter by album")
    parser.add_argument("--url", default="http://kimihome.lan:5005", help="Server URL")
    args = parser.parse_args()

    console = Console()
    if not args.tags and not args.artist and not args.album:
        console.print("\n[red]Error: provide tags, --artist, or --album[/]")
        return 1
    if not 0.0 <= args.max_distance <= 2.0:
        console.print("\n[red]Error: max-distance must be between 0.0 and 2.0[/]")
        return 1

    params = {
        "tags": args.tags,
        "limit": args.limit,
        "max_distance": args.max_distance,
    }
    if args.artist:
        params["artist"] = args.artist
    if args.album:
        params["album"] = args.album

    url = f"{args.url.rstrip('/')}/search_tracks/?{urlencode(params)}"
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        results = response.json()
    except requests.exceptions.RequestException as exc:
        console.print(f"\n[red]Error connecting to server:[/] {exc}")
        return 1
    except ValueError as exc:
        console.print(f"\n[red]Server response is not JSON:[/] {exc}")
        return 1

    if not results:
        console.print("\n[yellow]No tracks found[/]")
        return 0

    table = Table(show_header=True, header_style="bold blue", title="Music2DB Search Results", title_style="bold blue")
    table.add_column("№", style="dim", width=4)
    table.add_column("Track Path", width=None)
    table.add_column("Artist")
    table.add_column("Title")
    table.add_column("Album")
    table.add_column("Genre")

    for idx, result in enumerate(results, 1):
        if not isinstance(result, dict):
            continue
        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        table.add_row(
            str(idx),
            Text(str(result.get("file_path", "")), style="bright_white" if idx == 1 else None),
            str(metadata.get("artist", "")),
            str(metadata.get("title", "")),
            str(metadata.get("album", "")),
            str(metadata.get("genre", "")),
        )

    console.print("\n")
    console.print(table)
    console.print("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
