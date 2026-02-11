import argparse
import html
import re
import subprocess
import base64
import os
import time
import urllib.request
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


# 这里用一个 SSH Host alias（~/.ssh/config 里配置）来固定使用正确 key
# 例如：Host github-common-hosts -> HostName github.com + IdentityFile ~/.ssh/id_ed25519_common_hosts
PREFERRED_GIT_SSH_HOST = (os.environ.get("PRIVACY_PAGES_SSH_HOST") or "github-common-hosts").strip() or "github-common-hosts"
DEFAULT_PAGES_SSH_KEY = Path(os.environ.get("PRIVACY_PAGES_SSH_KEY", "~/.ssh/id_ed25519_common_hosts")).expanduser()


def _decode_bytes(b: Optional[bytes]) -> str:
    if not b:
        return ""
    try:
        return b.decode("utf-8", errors="replace")
    except Exception:
        # absolute fallback
        return b.decode(errors="replace")


def run(
    cmd: list[str],
    cwd: Optional[Path] = None,
    env: Optional[dict[str, str]] = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """运行命令；失败就打印 stdout/stderr 并抛出。

    Windows 上 git 输出可能包含非本地代码页字符，text=True 可能在后台线程里触发
    UnicodeDecodeError（gbk 解码失败）。这里改为二进制捕获，再手动用 UTF-8 安全解码。
    """
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    p = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        env=merged_env,
    )

    # attach decoded text versions for our own printing/logic
    p.stdout = _decode_bytes(p.stdout)  # type: ignore[attr-defined]
    p.stderr = _decode_bytes(p.stderr)  # type: ignore[attr-defined]

    if check and p.returncode != 0:
        out = (p.stdout or "").strip()
        err = (p.stderr or "").strip()
        if out:
            print(out)
        if err:
            print(err)
        raise subprocess.CalledProcessError(p.returncode, cmd, output=p.stdout, stderr=p.stderr)

    return p


def _resolve_pages_ssh_key() -> Optional[Path]:
    """Resolve which SSH key to use for git push."""
    return DEFAULT_PAGES_SSH_KEY if DEFAULT_PAGES_SSH_KEY.exists() else None


def _key_loaded_in_agent(key_path: Path) -> bool:
    try:
        pub_path = Path(str(key_path) + ".pub")
        if not pub_path.exists():
            return False
        pub = pub_path.read_text(encoding="utf-8").strip()
        if not pub:
            return False

        p = subprocess.run(["ssh-add", "-L"], capture_output=True)
        if p.returncode != 0:
            return False

        out = _decode_bytes(p.stdout)

        # compare pub key body part
        parts = pub.split()
        return len(parts) >= 2 and parts[1] in (out or "")
    except Exception:
        return False


def _ensure_ssh_agent_has_key() -> None:
    """Ensure ssh-agent exists and has the pages SSH key loaded.

    We DO NOT auto-run ssh-add here (it may prompt for passphrase, which would hang
    when running from scripts). Instead we print a one-time setup hint.
    """
    key_path = _resolve_pages_ssh_key()
    if not key_path:
        return

    # If already loaded, do nothing
    if _key_loaded_in_agent(key_path):
        return

    print(
        "\n⚠️ 当前环境的 ssh-agent 里还没有加载 GitHub Pages 的 SSH key，脚本将无法自动 push。\n"
        "请在终端手动执行一次（只需一次）：\n"
        f"  ssh-add --apple-use-keychain {key_path}\n"
        "输入 passphrase 后，会保存到 Keychain，之后运行脚本就不会再提示。\n"
    )


def _rewrite_remote_to_preferred_host(remote_url: str) -> str:
    """Rewrite origin remote url to use our SSH host alias.

    Supports:
      - SSH: git@github.com:owner/repo(.git)
      - SSH alias: git@github-common-hosts:owner/repo(.git)
      - HTTPS: https://github.com/owner/repo(.git)
      - GitHub Desktop style: "GitHub - owner/repo" (seen on some Windows setups)

    Example:
      git@github.com:common-hosts/privacy-page.git  ->  git@github-common-hosts:common-hosts/privacy-page.git
      https://github.com/common-hosts/privacy-page  ->  git@github-common-hosts:common-hosts/privacy-page.git
    """
    u = (remote_url or "").strip()
    if not u:
        return u

    # GitHub Desktop / UI style remote name
    m = re.match(r"^GitHub\s*-\s*([^/\s]+)/([^\s]+)$", u)
    if m:
        owner, repo = m.group(1), m.group(2)
        repo = repo[:-4] if repo.endswith(".git") else repo
        return f"git@{PREFERRED_GIT_SSH_HOST}:{owner}/{repo}.git"

    # HTTPS
    m = re.match(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", u)
    if m:
        owner, repo = m.group(1), m.group(2)
        return f"git@{PREFERRED_GIT_SSH_HOST}:{owner}/{repo}.git"

    # SSH
    m = re.match(r"^git@([^:]+):(.+)$", u)
    if not m:
        return u

    host, rest = m.group(1), m.group(2)
    if host == PREFERRED_GIT_SSH_HOST:
        return u

    if host == "github.com":
        return f"git@{PREFERRED_GIT_SSH_HOST}:{rest}"

    return u


def get_git_remote_url(remote: str = "origin") -> str:
    try:
        p = run(["git", "remote", "get-url", remote], cwd=REPO_ROOT)
        return (p.stdout or "").strip()
    except Exception:
        return ""


def _ensure_origin_uses_preferred_host() -> None:
    remote_url = get_git_remote_url("origin")
    if not remote_url:
        return
    new_url = _rewrite_remote_to_preferred_host(remote_url)
    if new_url != remote_url:
        run(["git", "remote", "set-url", "origin", new_url], cwd=REPO_ROOT)
        print(f"🔧 已将 origin 重写为使用 SSH 别名：{new_url}")


def _print_git_account_hint() -> None:
    """Print what identity this process is going to use to push."""
    try:
        remote_url = get_git_remote_url("origin")
        if remote_url:
            proto = "SSH" if remote_url.startswith("git@") else "HTTPS/OTHER"
            print(f"🔧 Git remote(origin): {remote_url} ({proto})")
            if proto != "SSH":
                print(
                    "⚠️ 检测到 origin 不是 SSH remote。HTTPS remote 会走 IDE/系统凭据，容易出现 403（推送到错误账号）。\n"
                    "   建议把 origin 改成 SSH：git@github-common-hosts:common-hosts/privacy-page.git"
                )
        else:
            print("🔧 Git remote(origin): (empty)")

        key_path = _resolve_pages_ssh_key()
        if key_path:
            print(f"🔐 Pages SSH key: {key_path}")
        else:
            print(f"🔐 Pages SSH key: (not found) expected {DEFAULT_PAGES_SSH_KEY}")
        print(f"🌐 Preferred SSH host alias: {PREFERRED_GIT_SSH_HOST}")
    except Exception:
        pass


def _git_env_for_pages_push() -> dict[str, str]:
    """Force git/ssh to use the right identity non-interactively.

    Key point: we explicitly connect to the SSH *alias host* (e.g. github-common-hosts)
    so ssh will pick the correct IdentityFile, regardless of which GitHub account
    is logged in inside PyCharm.

    Note:
      - BatchMode=yes => never prompt for passphrase. If the key isn't loaded in ssh-agent,
        git push will fail fast with a clear error.
    """
    _ensure_ssh_agent_has_key()
    return {
        # : remote is git@github-common-hosts:...
        # still set -o HostName=... to make sure ssh uses our alias config.
        "GIT_SSH_COMMAND": (
            f"ssh -o HostName=github.com -o BatchMode=yes -o IdentitiesOnly=yes "
            "-o StrictHostKeyChecking=accept-new "
            "-o ControlMaster=auto -o ControlPersist=10m -o ControlPath=~/.ssh/cm-%r@%h:%p"
        ),
        "GIT_PROTOCOL": "version=2",
    }


def get_repo_slug_from_remote(remote_url: str) -> str:
    r"""Extract owner/repo from git remote url.

    Supported:
      - SSH: git@github.com:owner/repo.git
      - HTTPS: https://github.com/owner/repo.git
    """
    u = (remote_url or "").strip()
    if not u:
        raise ValueError(f"Unsupported remote url: {remote_url!r}")

    # SSH
    m = re.match(r"^git@[^:]+:([^/]+)/(.+?)(?:\.git)?$", u)
    if m:
        return f"{m.group(1)}/{m.group(2)}"

    # HTTPS
    m = re.match(r"^https?://[^/]+/([^/]+)/(.+?)(?:\.git)?/?$", u)
    if m:
        return f"{m.group(1)}/{m.group(2)}"

    raise ValueError(f"Unsupported remote url: {remote_url!r}")


def github_pages_base_url(repo_slug: str) -> str:
    owner, repo = repo_slug.split("/", 1)
    return f"https://{owner}.github.io/{repo}/"


def slugify(s: str) -> str:
    """Generate safe path slug for GitHub Pages URL."""
    s = (s or "").strip().lower()
    s = re.sub(r"[\s_]+", "-", s)
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
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def strip_leading_privacy_policy(text: str) -> str:
    """去掉正文最前面的 'Privacy Policy' + 空行，避免页面出现重复标题。"""
    if not text:
        return ""
    t = text.lstrip("\ufeff\n\r\t ")
    if re.match(r"(?is)^privacy\s*policy\s*(\n|\r\n)\s*(\n|\r\n)", t):
        t = re.sub(r"(?is)^privacy\s*policy\s*(\n|\r\n)\s*(\n|\r\n)", "", t, count=1)
    return t


def render_html(page: PageData) -> str:
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


# NOTE:
# We intentionally do NOT write/overwrite repository root `index.html` here.
# Root `index.html` is reserved as a permanent '404 / Not Found' landing page
# to avoid leaking repo details and to prevent per-app publishes from clobbering it.


def read_content_from_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def git_commit_push(commit_message: str) -> None:
    """git add/commit/push; only commit the files we own.

    Team-friendly behavior:
      1) Pull/rebase first to avoid non-fast-forward errors.
      2) Only stage/commit privacy_merge.py + googleSites.py + pages/**
         (do NOT commit root index.html or privacy_text.txt).

    IMPORTANT:
      -   PyCharm 
        : 
        SSH 
        remote `git@github-common-hosts:...`
         `~/.ssh/config`  Host 
    """
    _ensure_origin_uses_preferred_host()
    _print_git_account_hint()
    _ensure_git_identity()

    # 1) Pull first (best effort). If no upstream yet, skip.
    env = _git_env_for_pages_push()
    try:
        # If upstream isn't set, this will fail; we ignore it.
        run(["git", "pull", "--rebase", "--autostash"], cwd=REPO_ROOT, env=env, check=False)
    except Exception:
        pass

    # 2) Only stage what this tool should manage
    paths_to_add = [
        "googleSites.py",
        "privacy_merge.py",
        "pages",
    ]
    run(["git", "add", "--"] + paths_to_add, cwd=REPO_ROOT)

    st = run(["git", "status", "--porcelain"], cwd=REPO_ROOT, check=False)
    if not (st.stdout or "").strip():
        print("  (googleSites.py/privacy_merge.py/pages/) commit")
    else:
        run(["git", "commit", "-m", commit_message], cwd=REPO_ROOT, env=env)

    # 3) Push using origin (already rewritten to preferred host).
    b = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO_ROOT)
    branch = (b.stdout or "main").strip() or "main"
    run(["git", "push", "origin", branch], cwd=REPO_ROOT, env=env)


def wait_until_url_ready(url: str, timeout_seconds: int = 120, interval_seconds: float = 3.0) -> bool:
    """Poll the published GitHub Pages URL until it returns HTTP 200。

    GitHub Pages often has a small build/deploy delay. This prevents the
    "new page 404, old page works" confusion.
    """
    end = time.time() + timeout_seconds
    last_err = ""
    while time.time() < end:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                if getattr(resp, "status", 200) == 200:
                    return True
        except Exception as e:
            last_err = str(e)
        time.sleep(interval_seconds)

    if last_err:
        print(f"⚠️ 页面在 {timeout_seconds}s 内仍不可访问（可能还在部署中）：{last_err}")
    else:
        print(f"⚠️ 页面在 {timeout_seconds}s 内仍不可访问（可能还在部署中）。")
    return False


# --- Clipboard helpers (macOS) ---
def copy_to_clipboard_macos(text: str) -> bool:
    """Copy text to macOS clipboard using pbcopy."""
    if not text:
        return False
    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        return True
    except Exception:
        return False


def show_macos_toast(message: str, seconds: int = 3) -> None:
    """Best-effort toast via AppleScript (no hard failure if blocked)."""
    msg = (message or "").replace('"', "\\\"")
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{msg}" with title "PrivacyTools"'],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        pass


def _ensure_git_identity() -> None:
    """Ensure git has user.name/user.email configured.

    Some teammate machines (or fresh Windows installs) don't have git identity set，
    which makes `git commit` fail. We set a repo-local fallback identity.
    """

    def _cfg(key: str) -> str:
        p = subprocess.run(
            ["git", "config", "--get", key],
            cwd=str(REPO_ROOT),
            capture_output=True,
        )
        return _decode_bytes(p.stdout).strip()

    name = _cfg("user.name")
    email = _cfg("user.email")

    # Set repository-local config (no --global) to avoid touching user's global setup.
    if not name:
        run(["git", "config", "user.name", "privacy-bot"], cwd=REPO_ROOT)
    if not email:
        run(["git", "config", "user.email", "privacy-bot@users.noreply.github.com"], cwd=REPO_ROOT)


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
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Do not wait/poll for GitHub Pages deployment (faster; URL may 404 for a bit).",
    )

    args = parser.parse_args()

    if args.content_file:
        content = read_content_from_file(Path(args.content_file))
    else:
        content = args.content or ""

    # Build slug
    if args.slug:
        page_slug = args.slug
    else:
        id_prefix = encode_id_to_base64_letters(args.id or "")
        if id_prefix:
            page_slug = f"{id_prefix}-{slugify(args.title)}"
        else:
            page_slug = slugify(args.title)

    page = PageData(title=args.title, content=content, content_is_html=args.content_is_html)
    out_path = write_privacy_page(page, page_slug)

    repo_slug = get_repo_slug_from_remote(get_git_remote_url("origin"))
    page_url = github_pages_base_url(repo_slug) + f"pages/{page_slug}/"

    # Do NOT overwrite root index.html (keep permanent 404 landing page)

    print(f"✅ Wrote privacy page: {out_path}")
    print(f"🌐 Page URL: {page_url}")

    if args.no_push:
        print("ℹ️ --no-push used. Skipping git commit/push.")
        return

    try:
        git_commit_push(args.commit_message)

        # give user a quick clipboard copy for convenience
        if copy_to_clipboard_macos(page_url):
            show_macos_toast("发布链接已复制", seconds=3)

        # Default speed: don't wait unless user explicitly wants it
        if not args.no_wait:
            print("⏳ 等待 GitHub Pages 部署生效...")
            if wait_until_url_ready(page_url, timeout_seconds=180, interval_seconds=4.0):
                print("✅ 页面已可访问。")
            else:
                print("ℹ️ 可能需要再等一会儿再刷新浏览器（GitHub Pages 有部署延迟）。")

    except subprocess.CalledProcessError as e:
        err = (e.stderr or "").strip()
        out = (e.output or "").strip()
        if out:
            print(out)
        if err:
            print(err)
        raise SystemExit(f"命令失败: {e.cmd} (exit {e.returncode})")


if __name__ == "__main__":
    main()
