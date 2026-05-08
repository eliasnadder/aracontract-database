"""
╔══════════════════════════════════════════════════════════════════╗
║         AraContract Dataset Builder — main.py                    ║
║         Syrian contracts from syrian-lawyer.club                 ║
║         Damascus University — NLP Project                        ║
╚══════════════════════════════════════════════════════════════════╝

Usage:
    python main.py                             # scrape only the target category
    python main.py --test                      # test mode (first page only)
    python main.py --resume                    # skip already downloaded files
    python main.py --output contracts_dataset  # custom output directory

Output structure:
    contracts_dataset/
    ├── المدنية/
    │   ├── الايجار/
    │   │   ├── صيغة_عقد_إيجار_دار_سكن_مفروشة.md
    │   │   └── ...
    │   ├── الهبة/
    │   └── ...
    ├── manifest.json
    └── scraper.log
"""

import argparse
import json
import logging
import random
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

# ═══════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

BASE_URL = "https://www.syrian-lawyer.club"
DEFAULT_OUTPUT_DIR = Path("contracts_dataset")
LOG_FILE_NAME = "scraper.log"
STATE_FILE_NAME = "scraper_state.json"
MANIFEST_FILE_NAME = "manifest.json"
TARGET_CATEGORY_URL = (
    "https://www.syrian-lawyer.club/category/المكتبة-القانونية/"
    "/صيغ-العقود-و-الدعاوي/صيغ-العقود/المدنية/عقود-مقاولات"
)

# Polite delays (seconds) — keep these generous to respect the server
DELAY_MIN = 5.0    # minimum wait between ANY two requests
DELAY_MAX = 10.0   # maximum wait between requests
CAT_DELAY = 12.0   # extra wait when switching to a new category
PAGE_DELAY = 8.0    # extra wait between pagination pages

# Retry settings
MAX_RETRIES = 3
RETRY_WAIT = 30.0   # wait before retrying a failed request
BLOCK_WAIT = 180.0  # long backoff when blocked (429/403)

# ─── Category resolution ─────────────────────────────────────────────────────
# Folder paths come from the classification file. Slugs are fetched from
# the site when possible, with a fallback to local slug guessing.
# If no classification file is provided, we fall back to a built-in map.

BASE_SLUG = "المكتبة-القانونية/صيغ-العقود-و-الدعاوي/صيغ-العقود/المدنية/عقود-مقاولات"


CATEGORY_FILE_CANDIDATES = [

]

CATEGORY_ALIASES = {

}

# Realistic browser User-Agent strings
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# ═══════════════════════════════════════════════════════════════════
#  LOGGING
# ═══════════════════════════════════════════════════════════════════


def setup_logging(output_dir: Path):
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    log_path = output_dir / LOG_FILE_NAME
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ]
    )


log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
#  HTTP SESSION — BROWSER SIMULATION
# ═══════════════════════════════════════════════════════════════════


def create_session() -> requests.Session:
    """Create a session that looks like a real browser."""
    s = requests.Session()
    user_agent = random.choice(USER_AGENTS)
    s.headers.update({
        "User-Agent":             user_agent,
        "Accept":                  "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language":         "ar-SY,ar;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding":         "gzip, deflate",
        "Connection":              "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest":          "document",
        "Sec-Fetch-Mode":          "navigate",
        "Sec-Fetch-Site":          "same-origin",
        "Sec-Fetch-User":          "?1",
        "Cache-Control":           "max-age=0",
        "sec-ch-ua":               '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile":        "?0",
        "sec-ch-ua-platform":      '"Windows"',
    })
    return s


def warm_up_session(session: requests.Session):
    """Visit homepage first to get cookies — simulates real user navigation."""
    log.info("🌐 Warming up session (visiting homepage)...")
    session.headers["Sec-Fetch-Site"] = "none"
    try:
        r = session.get(BASE_URL + "/", timeout=20)
        log.info(
            f"   Homepage: {r.status_code} | Cookies: {list(session.cookies.keys())}")
        session.headers["Referer"] = BASE_URL + "/"
        session.headers["Sec-Fetch-Site"] = "same-origin"
        time.sleep(random.uniform(3, 6))
    except Exception as e:
        log.warning(f"   Homepage warm-up failed: {e}")


def polite_get(
    session: requests.Session,
    url: str,
    extra_delay: float = 0,
    referer: str | None = None,
) -> requests.Response | None:
    """
    Fetch a URL with:
    - Random delay before request
    - Fixed User-Agent per session
    - Automatic retry on failure
    - Returns None on permanent failure
    """
    wait = random.uniform(DELAY_MIN, DELAY_MAX) + extra_delay
    log.info(f"  ⏳ {wait:.1f}s delay → {url[:90]}")
    time.sleep(wait)

    if referer:
        session.headers["Referer"] = referer
    elif "Referer" not in session.headers:
        session.headers["Referer"] = BASE_URL + "/"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, timeout=25)
            if r.status_code == 200:
                r.encoding = "utf-8"
                return r
            elif r.status_code == 404:
                log.warning(f"  📭 404 Not Found: {url}")
                return None
            elif r.status_code in (429, 403):
                log.warning(
                    f"  ⛔ Blocked ({r.status_code}) — backing off {BLOCK_WAIT:.0f}s and stopping")
                time.sleep(BLOCK_WAIT)
                return None
            elif r.status_code in (500, 502, 503):
                log.warning(
                    f"  ⚠️  Server error ({r.status_code}), waiting {RETRY_WAIT}s...")
                time.sleep(RETRY_WAIT * attempt)
            else:
                log.warning(f"  ⚠️  HTTP {r.status_code}: {url}")
                time.sleep(5)
        except requests.exceptions.ConnectionError as e:
            log.warning(f"  🔌 Connection error (attempt {attempt}): {e}")
            time.sleep(RETRY_WAIT)
        except requests.exceptions.Timeout:
            log.warning(f"  ⌛ Timeout (attempt {attempt}): {url}")
            time.sleep(10)
        except Exception as e:
            log.error(f"  ❌ Unexpected error: {e}")
            return None

    log.error(f"  ❌ All {MAX_RETRIES} attempts failed: {url}")
    return None

# ═══════════════════════════════════════════════════════════════════
#  CATEGORY RESOLUTION
# ═══════════════════════════════════════════════════════════════════


def normalize_arabic(text: str) -> str:
    """Normalize Arabic text for tolerant matching."""
    text = unicodedata.normalize("NFKC", text).strip()
    text = re.sub(r"[\u064B-\u065F]", "", text)  # remove harakat
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    text = re.sub(r"[\-_]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def slugify_arabic(text: str) -> str:
    """Convert a category name to a URL-friendly slug."""
    text = re.sub(r"[\\/*?:\"<>|؟،]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def build_alias_index() -> dict[str, list[str]]:
    alias_index: dict[str, list[str]] = {}
    for base_name, aliases in CATEGORY_ALIASES.items():
        all_names = [base_name] + list(aliases)
        for name in all_names:
            key = normalize_arabic(name)
            alias_index.setdefault(key, [])
            for candidate in all_names:
                if candidate not in alias_index[key]:
                    alias_index[key].append(candidate)
    return alias_index


ALIAS_INDEX = build_alias_index()


def find_categories_file(explicit_path: str | None) -> Path | None:
    if explicit_path:
        path = Path(explicit_path)
        return path if path.exists() else None

    search_roots = [Path.cwd(), Path(__file__).resolve().parent]
    for root in search_roots:
        for name in CATEGORY_FILE_CANDIDATES:
            candidate = root / name
            if candidate.exists():
                return candidate
    return None


def extract_paths_from_json(data) -> list[str]:
    paths: list[str] = []

    if isinstance(data, list):
        for item in data:
            if isinstance(item, str) and "/" in item:
                paths.append(item)
            elif isinstance(item, dict):
                for key in ("path", "category", "category_path", "name"):
                    value = item.get(key)
                    if isinstance(value, str) and "/" in value:
                        paths.append(value)
    elif isinstance(data, dict):
        for key in ("paths", "categories", "items"):
            value = data.get(key)
            if isinstance(value, list):
                paths.extend(extract_paths_from_json(value))
        if not paths:
            for key, value in data.items():
                if isinstance(key, str):
                    if isinstance(value, dict):
                        for child in extract_paths_from_json(value):
                            prefix = f"{key}/{child}" if child else key
                            paths.append(prefix)
                    elif isinstance(value, list) and value:
                        for child in extract_paths_from_json(value):
                            prefix = f"{key}/{child}" if child else key
                            paths.append(prefix)
                    else:
                        paths.append(key)

    return paths


def load_category_paths(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8")
    paths: list[str] = []

    if path.suffix.lower() == ".json":
        try:
            data = json.loads(raw)
            paths = extract_paths_from_json(data)
        except json.JSONDecodeError:
            paths = []
    elif path.suffix.lower() == ".jsonl":
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            for key in ("path", "category", "category_path", "name"):
                value = data.get(key)
                if isinstance(value, str) and "/" in value:
                    paths.append(value)

    if not paths:
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("```"):
                continue
            line = re.sub(r"^(?:[-*•]+\s+)", "", line)
            if "/" in line:
                paths.append(line)

    cleaned = []
    seen = set()
    for path_item in paths:
        path_item = path_item.replace("\\", "/").strip().strip("/")
        if not path_item:
            continue
        if path_item not in seen:
            seen.add(path_item)
            cleaned.append(path_item)
    return cleaned


def extract_slug_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    path = parsed.path
    marker = "/category/"
    if marker not in path:
        return None
    slug = path.split(marker, 1)[1].strip("/")
    return unquote(slug) if slug else None


def fetch_category_index(session: requests.Session) -> dict[str, str]:
    index: dict[str, str] = {}
    category_root = build_category_url(BASE_SLUG)
    r = polite_get(session, category_root, referer=BASE_URL + "/")
    if r is None:
        return index

    soup = BeautifulSoup(r.text, "lxml")
    for link in soup.select("a[href*='/category/']"):
        href = link.get("href", "")
        if not href:
            continue
        slug = extract_slug_from_url(href)
        if not slug or not slug.startswith(BASE_SLUG):
            continue
        name = link.get_text(strip=True)
        if not name:
            continue
        key = normalize_arabic(name)
        if key not in index:
            index[key] = slug
    return index


def resolve_category_slug(category_name: str, category_index: dict[str, str]) -> str:
    candidates = [category_name]
    key = normalize_arabic(category_name)
    for alias in ALIAS_INDEX.get(key, []):
        if alias not in candidates:
            candidates.append(alias)

    for candidate in candidates:
        slug = category_index.get(normalize_arabic(candidate))
        if slug:
            return slug

    fallback = slugify_arabic(candidates[0])
    return f"{BASE_SLUG}/{fallback}"


def build_category_map(paths: list[str], category_index: dict[str, str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for path_item in paths:
        leaf = path_item.split("/")[-1]
        slug = resolve_category_slug(leaf, category_index)
        mapping[path_item] = slug
    return mapping


def pick_test_category(paths: list[str]) -> str:
    target = normalize_arabic("عقود-مقاولات")
    for path_item in paths:
        leaf = path_item.split("/")[-1]
        if normalize_arabic(leaf) == target:
            return path_item
    return "المدنية/عقود-مقاولات"

# ═══════════════════════════════════════════════════════════════════
#  HTML PARSING
# ═══════════════════════════════════════════════════════════════════


def build_category_url(slug: str, page: int = 1) -> str:
    """Build the full URL for a category page (with pagination)."""
    # quote each path segment but NOT the slashes
    encoded_parts = []
    for part in slug.split("/"):
        encoded_parts.append(quote(part, safe=""))
    encoded_slug = "/".join(encoded_parts)

    base = f"{BASE_URL}/category/{encoded_slug}/"
    if page > 1:
        return f"{base}page/{page}/"
    return base


def extract_article_links(soup: BeautifulSoup) -> list[dict]:
    """
    Extract article title + URL from a category listing page.
    Tries multiple CSS selectors to handle theme variations.
    """
    links = []
    seen = set()

    selectors = [
        "h2.entry-title a",
        "h1.entry-title a",
        "article h2 a",
        "article h1 a",
        ".post-title a",
        ".entry-title a",
    ]

    for selector in selectors:
        for tag in soup.select(selector):
            href = tag.get("href", "").strip()
            title = tag.get_text(strip=True)
            if not href or not title:
                continue
            href = urljoin(BASE_URL + "/", href)
            if href.startswith(BASE_URL) and href not in seen:
                seen.add(href)
                links.append({"url": href, "title": title})

    return links


def get_next_page_url(soup: BeautifulSoup) -> str | None:
    """Find pagination 'next page' link."""
    next_btn = soup.select_one(
        "a.next.page-numbers, "
        "a[rel='next'], "
        ".nav-next a, "
        ".pagination .next"
    )
    if not next_btn:
        return None
    return urljoin(BASE_URL + "/", next_btn["href"])


UNWANTED_SELECTORS = (
    "nav",
    "aside",
    ".sharedaddy",
    ".jp-relatedposts",
    ".related-posts",
    ".post-tags",
    ".post-categories",
    ".post-navigation",
    ".nav-links",
    ".nav-previous",
    ".nav-next",
    ".entry-footer",
    ".wp-block-separator",
    ".wp-block-social-links",
    ".wp-block-buttons",
    ".comments-area",
    ".elementor-widget-social-icons",
    ".elementor-widget-button",
    "script",
    "style",
    "noscript",
    ".ezoic-ad",
    ".adsbygoogle",
    "[class*='ad-']",
    "[id*='ad-']",
)

NOISE_LINE_PATTERNS = [
    r"^المزيد من المشاركات$",
    r"^المزيد من المقالات$",
    r"^المزيد$",
    r"^السابق$",
    r"^التالي$",
    r"^Previous$",
    r"^Next$",
    r"^Related Posts$",
    r"^Share$",
]


def render_inline(node: Tag | NavigableString) -> str:
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""

    name = node.name.lower()
    if name == "br":
        return "\n"
    if name in ("strong", "b"):
        return f"**{render_inline_children(node)}**"
    if name in ("em", "i"):
        return f"*{render_inline_children(node)}*"
    if name == "code":
        text = render_inline_children(node)
        fence = "``" if "`" in text else "`"
        return f"{fence}{text}{fence}"
    if name == "a":
        text = render_inline_children(node).strip()
        href = node.get("href", "").strip()
        if href:
            return f"[{text}]({href})" if text else href
        return text

    return render_inline_children(node)


def render_inline_children(tag: Tag) -> str:
    parts = [render_inline(child) for child in tag.children]
    return "".join(parts)


def render_list(list_tag: Tag, ordered: bool, indent: int = 0) -> str:
    lines: list[str] = []
    index = 1
    for li in list_tag.find_all("li", recursive=False):
        prefix = "  " * indent + (f"{index}. " if ordered else "- ")
        inline_parts = []
        for child in li.children:
            if isinstance(child, Tag) and child.name in ("ul", "ol"):
                continue
            inline_parts.append(render_inline(child))
        line = prefix + "".join(inline_parts).strip()
        if line.strip():
            lines.append(line)

        for child in li.find_all(["ul", "ol"], recursive=False):
            lines.append(render_list(child, ordered=(
                child.name == "ol"), indent=indent + 1))

        index += 1

    return "\n".join(lines) + "\n\n" if lines else ""


def render_table(table_tag: Tag) -> str:
    rows = []
    for tr in table_tag.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        row = [render_inline_children(cell).strip() for cell in cells]
        if row:
            rows.append(row)

    if not rows:
        return ""

    max_cols = max(len(row) for row in rows)
    rows = [row + [""] * (max_cols - len(row)) for row in rows]

    header = rows[0]
    sep = ["---"] * max_cols
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines) + "\n\n"


def render_blockquote(tag: Tag) -> str:
    text = tag.get_text("\n", strip=True)
    if not text:
        return ""
    lines = ["> " + line for line in text.splitlines()]
    return "\n".join(lines) + "\n\n"


def render_block(node: Tag | NavigableString) -> str:
    if isinstance(node, NavigableString):
        text = str(node).strip()
        return text + "\n\n" if text else ""
    if not isinstance(node, Tag):
        return ""

    name = node.name.lower()
    if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = int(name[1])
        text = render_inline_children(node).strip()
        return f"{'#' * level} {text}\n\n" if text else ""
    if name == "p":
        text = render_inline_children(node).strip()
        return f"{text}\n\n" if text else ""
    if name == "ul":
        return render_list(node, ordered=False)
    if name == "ol":
        return render_list(node, ordered=True)
    if name == "table":
        return render_table(node)
    if name == "blockquote":
        return render_blockquote(node)
    if name == "pre":
        text = node.get_text("\n", strip=True)
        return f"```\n{text}\n```\n\n" if text else ""
    if name in ("div", "section", "article"):
        return render_container(node)

    text = render_inline_children(node).strip()
    return f"{text}\n\n" if text else ""


def render_container(tag: Tag) -> str:
    blocks = []
    for child in tag.children:
        block = render_block(child)
        if block:
            blocks.append(block)
    return "".join(blocks)


def clean_markdown(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_noise_lines(text: str) -> str:
    cleaned = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            if any(re.match(pattern, stripped, re.IGNORECASE) for pattern in NOISE_LINE_PATTERNS):
                continue
        cleaned.append(line)
    text = "\n".join(cleaned)
    return clean_markdown(text)


def ensure_title_heading(title: str, body: str) -> str:
    if not title or not body:
        return body
    first_line = ""
    for line in body.splitlines():
        if line.strip():
            first_line = line
            break
    if normalize_arabic(first_line.lstrip("#").strip()) == normalize_arabic(title):
        return body
    return f"# {title}\n\n{body}"


def extract_contract_markdown(soup: BeautifulSoup, url: str) -> dict:
    """
    Extract title and full contract text as Markdown from an article page.
    Handles both classic WordPress themes and Elementor page builder.
    """
    # ── Title ──────────────────────────────────────────────────────
    title_tag = soup.select_one(
        "h1.entry-title, h1.post-title, "
        ".elementor-widget-theme-post-title h1, "
        "h1"
    )
    title = title_tag.get_text(strip=True) if title_tag else "بدون_عنوان"

    # ── Content ────────────────────────────────────────────────────
    content_selectors = [
        "div.entry-content",
        "div.post-content",
        "div.article-content",
        "div.elementor-widget-theme-post-content",
        "div.elementor-text-editor",
        ".elementor-widget-container .elementor-widget-text-editor",
        "div.wp-block-post-content",
    ]

    content_tag = None
    for sel in content_selectors:
        content_tag = soup.select_one(sel)
        if content_tag:
            break

    if not content_tag:
        content_tag = soup.select_one("article")

    if content_tag:
        for unwanted in content_tag.select(", ".join(UNWANTED_SELECTORS)):
            unwanted.decompose()
        markdown = render_container(content_tag)
    else:
        log.warning(f"    No content container found for: {url}")
        markdown = ""

    markdown = strip_noise_lines(markdown)
    markdown = ensure_title_heading(title, markdown)

    return {
        "title": title,
        "markdown": markdown,
        "url": url,
        "char_count": len(markdown),
    }

# ═══════════════════════════════════════════════════════════════════
#  FILE I/O
# ═══════════════════════════════════════════════════════════════════


def safe_filename(title: str) -> str:
    """Convert Arabic title into a safe filesystem filename."""
    title = title.strip()
    # Remove forbidden filesystem characters
    title = re.sub(r'[\\/*?:"<>|؟،]', '', title)
    # Collapse whitespace to underscore
    title = re.sub(r'\s+', '_', title)
    # Remove leading/trailing underscores
    title = title.strip('_')
    # Cap length (leave room for extension)
    return title[:100] if title else "عقد_بدون_عنوان"


def save_contract(data: dict, folder: Path) -> Path:
    """
    Save contract as UTF-8 Markdown file.
    Returns the path of the saved file.
    """
    folder.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(data["title"]) + ".md"
    filepath = folder / filename

    # If file already exists, don't overwrite (resume support)
    if filepath.exists() and filepath.stat().st_size > 200:
        return filepath  # already downloaded

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(data["markdown"])

    return filepath


def already_downloaded(title: str, folder: Path) -> bool:
    """Check if this contract was already saved (for --resume mode)."""
    filename = safe_filename(title) + ".md"
    filepath = folder / filename
    return filepath.exists() and filepath.stat().st_size > 200


def load_resume_state(output_dir: Path) -> dict:
    state_path = output_dir / STATE_FILE_NAME
    if not state_path.exists():
        return {"done_urls": set()}

    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"done_urls": set()}

    urls = data.get("done_urls", [])
    return {"done_urls": set(urls)}


def save_resume_state(output_dir: Path, state: dict) -> None:
    state_path = output_dir / STATE_FILE_NAME
    data = {"done_urls": sorted(state.get("done_urls", []))}
    state_path.write_text(json.dumps(
        data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_manifest(output_dir: Path) -> tuple[list[dict], set[str]]:
    manifest_path = output_dir / MANIFEST_FILE_NAME
    if not manifest_path.exists():
        return [], set()

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [], set()

    items = data.get("items", [])
    url_set = {item.get("url") for item in items if item.get("url")}
    return items, url_set


def add_manifest_item(items: list[dict], url_set: set[str], item: dict) -> None:
    url = item.get("url")
    if not url or url in url_set:
        return
    items.append(item)
    url_set.add(url)


def save_manifest(stats: dict, output_dir: Path, items: list[dict], category_paths: list[str]) -> Path:
    counts = {path: 0 for path in category_paths}
    for item in items:
        category = item.get("category")
        if category not in counts:
            counts[category] = 0
        counts[category] += 1

    manifest = {
        "total_contracts": len(items),
        "failed_fetches": stats["failed"],
        "empty_content": stats["empty"],
        "skipped_existing": stats.get("skipped", 0),
        "categories": counts,
        "items": items,
    }

    manifest_path = output_dir / MANIFEST_FILE_NAME
    manifest_path.write_text(json.dumps(
        manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"\n📋 Manifest saved: {manifest_path}")
    return manifest_path

# ═══════════════════════════════════════════════════════════════════
#  MAIN SCRAPING ENGINE
# ═══════════════════════════════════════════════════════════════════


def scrape_category(
    session: requests.Session,
    folder_path: str,
    url_slug: str,
    stats: dict,
    output_dir: Path,
    resume_state: dict,
    manifest_items: list[dict],
    manifest_urls: set[str],
    resume: bool = False,
    test_mode: bool = False,
):
    """
    Scrape all contracts in one category.
    Handles multi-page pagination automatically.
    """
    folder = output_dir / folder_path
    folder.mkdir(parents=True, exist_ok=True)

    log.info(f"\n{'═'*65}")
    log.info(f"📂  Category : {folder_path}")
    log.info(f"    Folder  : {folder}")

    page_num = 1
    visited_urls: set[str] = set()

    while True:
        cat_url = build_category_url(url_slug, page_num)
        log.info(f"\n  📄 Page {page_num}: {cat_url}")

        r = polite_get(
            session,
            cat_url,
            extra_delay=PAGE_DELAY if page_num > 1 else 0,
            referer=BASE_URL + "/",
        )
        if r is None:
            log.warning(
                f"  ⚠️  Could not fetch category page {page_num} — stopping this category")
            break

        soup = BeautifulSoup(r.text, "lxml")

        # Check for actual 404 content (some WP setups return 200 for missing pages)
        page_title = soup.title.string if soup.title else ""
        if "404" in page_title or "Page not found" in page_title:
            log.info(f"  📭 Page {page_num} is 404 — end of category")
            break

        article_links = extract_article_links(soup)
        if not article_links:
            log.info(f"  📭 No articles on page {page_num} — end of category")
            break

        log.info(
            f"  🔗 Found {len(article_links)} article(s) on page {page_num}")

        for idx, link in enumerate(article_links):
            art_url = link["url"]
            art_title = link["title"]

            # Skip duplicates
            if art_url in visited_urls:
                continue
            visited_urls.add(art_url)

            # Skip already downloaded (resume mode)
            if resume and art_url in resume_state.get("done_urls", set()):
                log.info(f"  ⏭️  Skip (already downloaded): {art_title[:50]}")
                stats["skipped"] += 1
                continue

            if resume and already_downloaded(art_title, folder):
                log.info(f"  ⏭️  Skip (already downloaded): {art_title[:50]}")
                resume_state.setdefault("done_urls", set()).add(art_url)
                save_resume_state(output_dir, resume_state)
                stats["skipped"] += 1
                continue

            log.info(
                f"  [{idx+1}/{len(article_links)}] Fetching: {art_title[:55]}")

            # Fetch article page
            r2 = polite_get(session, art_url, referer=cat_url)
            if r2 is None:
                log.error(f"  ❌ Failed to fetch: {art_url}")
                stats["failed"] += 1
                continue

            soup2 = BeautifulSoup(r2.text, "lxml")
            data = extract_contract_markdown(soup2, art_url)

            # Validate content
            if not data["markdown"] or data["char_count"] < 150:
                log.warning(
                    f"  ⚠️  Content too short ({data['char_count']} chars): {art_title[:50]}")
                stats["empty"] += 1
                continue

            # Save
            saved_path = save_contract(data, folder)
            log.info(
                f"  ✅ Saved [{data['char_count']} chars]: {saved_path.name}")
            stats["saved"] += 1

            resume_state.setdefault("done_urls", set()).add(art_url)
            save_resume_state(output_dir, resume_state)

            add_manifest_item(
                manifest_items,
                manifest_urls,
                {
                    "title": data["title"],
                    "url": data["url"],
                    "category": folder_path,
                    "path": saved_path.relative_to(output_dir).as_posix(),
                    "char_count": data["char_count"],
                },
            )

        # ── Pagination ───────────────────────────────────────────────
        next_url = get_next_page_url(soup)
        if next_url and not test_mode:
            log.info(f"  ➡️  Next page found")
            page_num += 1
        else:
            if test_mode:
                log.info(f"  🧪 Test mode — stopping after first page")
            else:
                log.info(f"  ✔️  All pages done for this category")
            break


# ═══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="AraContract Dataset Builder")
    parser.add_argument("--test",   action="store_true",
                        help="Test mode: scrape only عقود-مقاولات, first page only")
    parser.add_argument("--resume", action="store_true",
                        help="Skip already downloaded contracts")
    parser.add_argument(
        "--output", default=str(DEFAULT_OUTPUT_DIR), help="Output directory")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(output_dir)

    log.info("╔══════════════════════════════════════════════╗")
    log.info("║   AraContract Dataset Builder — Starting     ║")
    log.info("╚══════════════════════════════════════════════╝")
    log.info(f"  Output  : {output_dir.resolve()}")
    log.info(
        f"  Mode    : {'TEST' if args.test else 'FULL'} {'+ RESUME' if args.resume else ''}")
    log.info(f"  Delays  : {DELAY_MIN}–{DELAY_MAX}s per request")

    # Create session and warm it up
    session = create_session()
    warm_up_session(session)

    target_slug = extract_slug_from_url(TARGET_CATEGORY_URL)
    if not target_slug:
        log.error("  ❌ Invalid TARGET_CATEGORY_URL — missing /category/ slug")
        return

    cats = {"المدنية/عقود-مقاولات": target_slug}
    log.info("  Categories: 1 (fixed target)\n")

    stats = {"saved": 0, "failed": 0, "empty": 0, "skipped": 0}
    resume_state = load_resume_state(output_dir)
    manifest_items, manifest_urls = load_manifest(output_dir)

    for folder_path, url_slug in cats.items():
        scrape_category(
            session=session,
            folder_path=folder_path,
            url_slug=url_slug,
            stats=stats,
            output_dir=output_dir,
            resume_state=resume_state,
            manifest_items=manifest_items,
            manifest_urls=manifest_urls,
            resume=args.resume,
            test_mode=args.test,
        )
        # Courtesy pause between categories
        if len(cats) > 1:
            pause = random.uniform(CAT_DELAY, CAT_DELAY * 1.5)
            log.info(f"\n  💤 Resting {pause:.1f}s before next category...\n")
            time.sleep(pause)

    # ── Final summary ──────────────────────────────────────────────
    log.info("\n" + "═" * 65)
    log.info("✅  SCRAPING COMPLETE")
    log.info(f"   ✔  Saved     : {stats['saved']} contracts")
    log.info(f"   ❌  Failed    : {stats['failed']} requests")
    log.info(f"   ⚠️   Empty     : {stats['empty']} articles")
    log.info(f"   ⏭️   Skipped   : {stats['skipped']} (already existed)")
    log.info("═" * 65)

    save_manifest(stats, output_dir, manifest_items, list(cats.keys()))

    log.info(f"\n🗂️  Dataset location: {output_dir.resolve()}")
    log.info(f"📝  Full log: {(output_dir / LOG_FILE_NAME).resolve()}")


if __name__ == "__main__":
    main()
