import argparse
import html
import re
import subprocess
import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parent
PAGES_DIR = REPO_ROOT / "pages"
INDEX_HTML_PATH = REPO_ROOT / "index.html"
DEFAULT_COMMIT_MESSAGE = "Update privacy page"

# 固定页面模板：H1 永远为 "Privacy Policy"（居中、黑体、H1 大小）
# 注意：页面标签 <title> 也固定为 Privacy Policy（App 名称不放在标题，以免被要求统一标题）。
FALLBACK_TEMPLATE = """<html lang=\"zh-CN\">\n<head>\n  <meta charset=\"utf-8\">\n  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n  <title>Privacy Policy</title>\n  <style>\n    body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,\"Helvetica Neue\",Arial;background:#f7f7fb;margin:0;padding:24px}}\n    .container{{max-width:860px;margin:28px auto;background:#fff;border-radius:10px;padding:28px;box-shadow:0 6px 22px rgba(20,20,30,0.06)}}\n    h1{{margin:0 0 18px;font-size:2rem;font-weight:700;text-align:center}}\n    .content{{line-height:1.7;color:#222;white-space:normal}}\n  </style>\n</head>\n<body>\n  <main class=\"container\">\n    <h1>Privacy Policy</h1>\n    <div class=\"content\">\n{content}\n    </div>\n  </main>\n</body>\n</html>\n"""


@dataclass
class PageData:
    title: str
    # content can be plain text OR html fragment. use content_is_html to decide.
    content: str
    content_is_html: bool = False


def run(cmd: list[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=check, text=True, capture_output=True)


def get_git_remote_url(remote: str = "origin") -> str:
    try:
        p = run(["git", "remote", "get-url", remote], cwd=REPO_ROOT)
        return (p.stdout or "").strip()
    except Exception:
        return ""


def get_repo_slug_from_remote(remote_url: str) -> str:
    """Extract owner/repo from git remote (ssh or https)."""
    m = re.search(r"github\.com[:/](?P<slug>[^/]+/[^/]+?)(?:\.git)?$", remote_url.strip())
    if not m:
        raise ValueError(f"Unsupported remote url: {remote_url!r}")
    return m.group("slug")


def github_pages_base_url(repo_slug: str) -> str:
    owner, repo = repo_slug.split("/", 1)
    return f"https://{owner}.github.io/{repo}/"


def slugify(s: str) -> str:
    """Generate safe path slug for GitHub Pages URL."""
    s = (s or "").strip().lower()
    # spaces/underscores -> hyphen
    s = re.sub(r"[\s_]+", "-", s)
    # keep alnum and hyphen only
    s = re.sub(r"[^a-z0-9\-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "privacy-policy"


def escape_and_preserve_newlines_as_html(text: str) -> str:
    """Plain text -> safe HTML, keeping line breaks and indentation for nicer display."""
    safe = html.escape(text or "")
    safe = safe.replace("  ", "&nbsp;&nbsp;")
    safe = safe.replace("\r\n", "\n").replace("\r", "\n")
    safe = safe.replace("\n", "<br>\n")
    return safe


def encode_id_to_base64_letters(raw_id: str) -> str:
    """把编号编码成 base64url 形式（只包含字母/数字/连字符/下划线），更短且可用于 URL 路径。"""
    raw = (raw_id or "").strip()
    if not raw:
        return ""
    b = raw.encode("utf-8")
    # urlsafe_b64encode 会用 - _ 替代 + /
    s = base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")
    return s


def strip_leading_privacy_policy(text: str) -> str:
    """去掉正文最前面的 'Privacy Policy' + 空行（来自生成器的首行），避免页面出现重复标题。"""
    if not text:
        return ""
    t = text.lstrip("\ufeff\n\r\t ")
    # 匹配：Privacy Policy\n\n...
    if re.match(r"(?is)^privacy\s*policy\s*(\n|\r\n)\s*(\n|\r\n)", t):
        t = re.sub(r"(?is)^privacy\s*policy\s*(\n|\r\n)\s*(\n|\r\n)", "", t, count=1)
    return t


def render_html(page: PageData) -> str:
    # 先做正文清理（去掉重复的 Privacy Policy 开头）
    content_source = page.content
    if not page.content_is_html:
        content_source = strip_leading_privacy_policy(content_source)

    content_html = content_source if page.content_is_html else escape_and_preserve_newlines_as_html(content_source)
    return FALLBACK_TEMPLATE.format(content=content_html)


def write_privacy_page(page: PageData, page_slug: str) -> Path:
    """Write to pages/<slug>/index.html and return the written path."""
    page_dir = PAGES_DIR / page_slug
    page_dir.mkdir(parents=True, exist_ok=True)
    out_path = page_dir / "index.html"
    out_path.write_text(render_html(page), encoding="utf-8")
    return out_path


def write_root_landing(latest_url: str) -> None:
    """Keep root index.html as a simple redirect to latest page (optional but useful)."""
    landing = f"""<html><head><meta charset=\"utf-8\"><meta http-equiv=\"refresh\" content=\"0; url={html.escape(latest_url)}\"></head>
<body>Redirecting to <a href=\"{html.escape(latest_url)}\">{html.escape(latest_url)}</a>...</body></html>\n"""
    INDEX_HTML_PATH.write_text(landing, encoding="utf-8")


def git_commit_push(commit_message: str = DEFAULT_COMMIT_MESSAGE) -> None:
    run(["git", "add", "pages", "index.html"], cwd=REPO_ROOT)

    status = run(["git", "status", "--porcelain"], cwd=REPO_ROOT).stdout.strip()
    if not status:
        print("ℹ️ No git changes to commit.")
        return

    run(["git", "commit", "-m", commit_message], cwd=REPO_ROOT)

    branch = run(["git", "branch", "--show-current"], cwd=REPO_ROOT).stdout.strip() or "main"
    run(["git", "push", "origin", branch], cwd=REPO_ROOT)


def read_content_from_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Publish per-app privacy page to GitHub Pages (no overwrite).")
    parser.add_argument("--title", required=True, help="App name (for logging only; page H1/title are fixed)")
    parser.add_argument("--content", help="Page content (plain text).")
    parser.add_argument("--content-file", help="Read content from a text file instead of --content")
    parser.add_argument("--content-is-html", action="store_true", help="Treat content as HTML (no escaping).")
    parser.add_argument("--slug", help="Optional custom slug; default: encoded_id + '-' + slugify(title)")
    parser.add_argument("--id", help="Optional raw ID (e.g. IGT1128). If provided, will be encoded into slug prefix.")
    parser.add_argument("--commit-message", default=DEFAULT_COMMIT_MESSAGE, help="Git commit message")
    parser.add_argument("--no-push", action="store_true", help="Only write files, do not commit/push")
    parser.add_argument("--no-landing", action="store_true", help="Do not update root index.html redirect")

    args = parser.parse_args()

    if bool(args.content) == bool(args.content_file):
        raise SystemExit("Please provide exactly one of --content or --content-file")

    content = args.content or read_content_from_file(Path(args.content_file).expanduser())
    page = PageData(title=args.title, content=content, content_is_html=bool(args.content_is_html))

    # 生成 slug：优先使用 --slug，否则用 (base64(id) + '-' + slugify(title))
    if args.slug:
        page_slug = slugify(args.slug)
    else:
        prefix = encode_id_to_base64_letters(args.id or "")
        suffix = slugify(args.title)
        page_slug = f"{prefix}-{suffix}" if prefix else suffix

    out_path = write_privacy_page(page, page_slug)

    remote_url = get_git_remote_url("origin")
    base_url = ""
    if remote_url:
        repo_slug = get_repo_slug_from_remote(remote_url)
        base_url = github_pages_base_url(repo_slug)

    page_url = f"{base_url}pages/{page_slug}/" if base_url else f"pages/{page_slug}/"

    if not args.no_landing and base_url:
        write_root_landing(page_url)

    print(f"✅ Wrote privacy page: {out_path}")
    print(f"🌐 Page URL: {page_url}")

    if args.no_push:
        print("ℹ️ --no-push used. Skipping git commit/push.")
        return

    git_commit_push(args.commit_message)
    print("✅ Committed and pushed.")
    print(f"\nOpen: {page_url}")


if __name__ == "__main__":
    main()
