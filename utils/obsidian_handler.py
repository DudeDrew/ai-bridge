# --------------------------
# utils/obsidian_handler.py
# --------------------------
import logging
import os
from typing import Dict, List

import requests

logger = logging.getLogger(__name__)

# Default timeout for Obsidian Local REST API calls (seconds)
_REQUEST_TIMEOUT = 10


def _get_base_url() -> str:
    url = os.getenv("OBSIDIAN_API_URL", "http://localhost:27123")
    return url.rstrip("/")


def _get_headers() -> Dict[str, str]:
    api_key = os.getenv("OBSIDIAN_API_KEY")
    if not api_key:
        raise RuntimeError("OBSIDIAN_API_KEY environment variable is not set")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_obsidian_vault(vault_name: str) -> List[Dict[str, str]]:
    """
    Fetch all Markdown notes from an Obsidian vault via the Local REST API.

    The Obsidian Local REST API plugin must be installed and running.
    See: https://github.com/coddingtonbear/obsidian-local-rest-api

    :param vault_name: The vault name (used as a label; the API serves one vault)
    :returns: List of dicts with 'id' (path), 'title', and 'content' keys
    """
    base_url = _get_base_url()
    headers = _get_headers()

    # List all files in the vault
    try:
        resp = requests.get(f"{base_url}/vault/", headers=headers, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise RuntimeError(
            f"Could not reach Obsidian Local REST API at {base_url}: {e}. "
            "Make sure the plugin is installed and Obsidian is running."
        ) from e

    all_files = resp.json().get("files", [])
    md_files = [f for f in all_files if f.endswith(".md")]

    notes = []
    for file_path in md_files:
        try:
            content_resp = requests.get(
                f"{base_url}/vault/{file_path}",
                headers={**headers, "Accept": "text/markdown"},
                timeout=_REQUEST_TIMEOUT,
            )
            content_resp.raise_for_status()
            content = content_resp.text

            # Derive a friendly title from the file path (strip extension)
            title = file_path.rsplit("/", 1)[-1].removesuffix(".md")

            notes.append({"id": file_path, "title": title, "content": content})
            logger.debug(f"Fetched Obsidian note: {file_path}")

        except requests.RequestException as e:
            logger.error(f"Failed to fetch Obsidian note {file_path}: {e}")
            # Continue with remaining notes rather than aborting the whole sync

    logger.info(f"Fetched {len(notes)} notes from Obsidian vault '{vault_name}'")
    return notes


def process_obsidian_webhook(payload: Dict) -> str:
    """
    Extract text content from an inbound Obsidian webhook payload.

    Obsidian's Local REST API can send payloads in several shapes; this
    function handles the common cases gracefully.

    :param payload: The raw JSON payload dict from the webhook request
    :returns: Plain text string ready for upload
    """
    # Shape 1: explicit 'content' field
    if "content" in payload:
        return payload["content"]

    # Shape 2: file path reference — fetch content live
    if "path" in payload:
        try:
            base_url = _get_base_url()
            headers = _get_headers()
            file_path = payload["path"]
            resp = requests.get(
                f"{base_url}/vault/{file_path}",
                headers={**headers, "Accept": "text/markdown"},
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            logger.error(f"Failed to fetch Obsidian note from webhook path: {e}")
            # Fall through to generic extraction

    # Shape 3: 'text' field
    if "text" in payload:
        return payload["text"]

    # Fallback: serialise the whole payload
    import json
    return json.dumps(payload, indent=2)
