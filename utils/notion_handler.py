# --------------------------
# utils/notion_handler.py
# --------------------------
import logging
import os
from typing import Dict, Any, List

from notion_client import Client

logger = logging.getLogger(__name__)


def _get_client() -> Client:
    """Return an authenticated Notion client."""
    token = os.getenv("NOTION_TOKEN")
    if not token:
        raise RuntimeError("NOTION_TOKEN environment variable is not set")
    return Client(auth=token)


# ── Block → plain text conversion ─────────────────────────────────────────────

def _rich_text_to_str(rich_text: list) -> str:
    """Flatten a Notion rich_text array to a plain string."""
    return "".join(rt.get("plain_text", "") for rt in rich_text)


def _block_to_text(block: Dict) -> str:
    """Convert a single Notion block to a plain text string."""
    block_type = block.get("type", "")
    data = block.get(block_type, {})

    if block_type in (
        "paragraph", "heading_1", "heading_2", "heading_3",
        "bulleted_list_item", "numbered_list_item", "toggle", "quote",
        "callout",
    ):
        return _rich_text_to_str(data.get("rich_text", []))

    if block_type == "code":
        lang = data.get("language", "")
        code = _rich_text_to_str(data.get("rich_text", []))
        return f"```{lang}\n{code}\n```"

    if block_type == "divider":
        return "---"

    if block_type == "to_do":
        checked = "x" if data.get("checked") else " "
        text = _rich_text_to_str(data.get("rich_text", []))
        return f"[{checked}] {text}"

    # Ignore unsupported block types (image, embed, etc.)
    return ""


def _fetch_block_children(client: Client, block_id: str, depth: int = 0) -> str:
    """
    Recursively fetch all child blocks and return them as plain text.
    Depth is capped at 3 to avoid excessively deep recursion.
    """
    if depth > 3:
        return ""

    lines = []
    cursor = None

    while True:
        kwargs = {"block_id": block_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor

        response = client.blocks.children.list(**kwargs)

        for block in response.get("results", []):
            text = _block_to_text(block)
            if text:
                indent = "  " * depth
                lines.append(f"{indent}{text}")

            # Recurse into blocks that have children
            if block.get("has_children"):
                child_text = _fetch_block_children(client, block["id"], depth + 1)
                if child_text:
                    lines.append(child_text)

        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    return "\n".join(lines)


def _page_title(page: Dict) -> str:
    """Extract the title from a Notion page object."""
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            return _rich_text_to_str(prop.get("title", []))
    return page.get("id", "untitled")


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_notion_page(page_id: str) -> str:
    """
    Fetch the full text content of a single Notion page.

    :param page_id: The Notion page UUID
    :returns: Plain text string of the page content
    """
    client = _get_client()
    page = client.pages.retrieve(page_id=page_id)
    title = _page_title(page)
    body = _fetch_block_children(client, page_id)
    return f"# {title}\n\n{body}".strip()


def fetch_notion_database(database_id: str) -> List[Dict[str, str]]:
    """
    Fetch all pages from a Notion database.

    :param database_id: The Notion database UUID
    :returns: List of dicts with 'id', 'title', and 'content' keys
    """
    client = _get_client()
    pages = []
    cursor = None

    while True:
        kwargs = {"database_id": database_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor

        response = client.databases.query(**kwargs)

        for page in response.get("results", []):
            page_id = page["id"]
            title = _page_title(page)

            try:
                body = _fetch_block_children(client, page_id)
                content = f"# {title}\n\n{body}".strip()
            except Exception as e:
                logger.error(f"Failed to fetch content for page {page_id}: {e}")
                content = f"# {title}\n\n[Content unavailable: {e}]"

            pages.append({"id": page_id, "title": title, "content": content})
            logger.debug(f"Fetched Notion page: {title} ({page_id})")

        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    logger.info(f"Fetched {len(pages)} pages from Notion database {database_id}")
    return pages
