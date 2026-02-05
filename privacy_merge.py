from __future__ import annotations

import html
import sys
import urllib
import subprocess
import os

import requests
import time
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
from selenium.webdriver.support.wait import WebDriverWait

import base64
import gzip
import json
import re
from io import BytesIO
from pathlib import Path
from DrissionPage import Chromium

# 这里的 URL 和表格 ID 请根据实际情况修改
# 表格 URL 示例: https://superxgr.larksuite.com/base/SebGbrq2yaNXXSsVOcJudpzxsCf?table=tblTywpT1yCgOaV7&view=vewOnkM00z
# API 接口示例: SebGbrq2yaNXXSsVOcJudpzxsCf/records
PRIVACY_GEN_URL = "https://app-privacy-policy-generator.firebaseapp.com/"
table_url = "https://superxgr.larksuite.com/base/SebGbrq2yaNXXSsVOcJudpzxsCf?table=tblTywpT1yCgOaV7&view=vewOnkM00z"
api_keyword = "SebGbrq2yaNXXSsVOcJudpzxsCf/records"
browser = None
browser_port = 9527
cookies_str = ""
app_name: str = ""
company_name: str = ""
email: str = ""

# 用于 finally 安全退出
driver = None

# 生成并发布静态页需要的输出文件
PRIVACY_TEXT_OUT = Path(__file__).resolve().parent / "privacy_text.txt"
TEMPLATE_HTML_PATH = Path(__file__).resolve().parent / "muban.html"


def html_to_formatted_text(html_fragment: str) -> str:
    """将 privacy_simple_content 的 innerHTML 转成较好粘贴的纯文本，保留段落、列表和链接结构。"""
    if not html_fragment:
        return ""
    soup = BeautifulSoup(html_fragment, "html.parser")

    lines = []

    from bs4.element import NavigableString, Tag

    def handle_node(node, indent_level=0):
        indent = "  " * indent_level

        if isinstance(node, NavigableString):
            text = str(node)
            text = text.replace("\u200b", "").strip("\n")
            if text:
                lines.append(indent + text)
            return

        if not isinstance(node, Tag):
            return

        name = (node.name or "").lower()

        if name == "br":
            lines.append("")
            return

        if name in {"p", "div", "section", "strong", "b", "em", "i", "h1", "h2", "h3", "h4", "h5", "h6"}:
            before = len(lines)
            for child in node.children:
                handle_node(child, indent_level)
            after = len(lines)
            if after > before and (not lines or lines[-1] != ""):
                lines.append("")
            return

        if name in {"ul", "ol"}:
            if lines and lines[-1] != "":
                lines.append("")
            idx = 1
            for li in node.find_all("li", recursive=False):
                prefix = "- " if name == "ul" else f"{idx}. "
                buf = []

                def collect(child):
                    if isinstance(child, NavigableString):
                        t = str(child).replace("\u200b", "").strip("\n")
                        if t:
                            buf.append(t)
                    elif isinstance(child, Tag):
                        cname = (child.name or "").lower()
                        if cname == "br":
                            buf.append(" ")
                        elif cname == "a":
                            href = child.get("href") or ""
                            visible = child.get_text(strip=True)
                            if href and visible:
                                buf.append(f"{visible} ({href})")
                            else:
                                buf.append(visible or href)
                        else:
                            for g in child.children:
                                collect(g)

                for c in li.children:
                    collect(c)
                li_text = "".join(buf)
                li_text = re.sub(r"\s+", " ", li_text).strip()
                if li_text:
                    lines.append(indent + prefix + li_text)
                for sub in li.find_all(["ul", "ol"], recursive=False):
                    handle_node(sub, indent_level + 1)
                if lines and lines[-1] != "":
                    lines.append("")
                idx += 1
            return

        if name == "a":
            href = node.get("href") or ""
            visible = node.get_text(strip=True)
            if href and visible:
                lines.append(indent + f"{visible} ({href})")
            else:
                lines.append(indent + (visible or href))
            return

        for child in node.children:
            handle_node(child, indent_level)

    root = soup.find(id="privacy_simple_content") or soup
    for c in root.children:
        handle_node(c, 0)

    out = []
    blank = 0
    for ln in lines:
        if ln.strip() == "":
            blank += 1
            if blank <= 2:
                out.append("")
        else:
            blank = 0
            out.append(ln)

    text = "\n".join(out)
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def copy_to_clipboard_macos(text: str) -> bool:
    """在 macOS 使用 pbcopy 复制文本到系统剪贴板。"""
    if not text:
        return False
    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        print("✅ 已复制到系统剪贴板 (pbcopy)")
        return True
    except Exception as e:
        print(f"⚠️ 复制到剪贴板失败: {e}")
        return False


def get_gzip_json_from_api(timeout: int = 60):
    """
    1. 监听接口捕获动态参数。
    2. 手动扫码登录，刷新页面触发接口。
    3. 修改捕获到的 URL，设置 offset=0。
    4. 提取 Cookies，使用 requests 库重新发送请求。
    5. 解析响应，解压 Gzip 数据。
    """
    global browser
    if browser is None:
        browser = Chromium(browser_port)

    tab = browser.latest_tab
    tab.get(table_url)
    print(f"🔍 开始监听接口: {api_keyword}")
    tab.listen.start(api_keyword)

    input("请扫码登录并按 Enter 继续 >>> ")
    tab.refresh()  # 触发接口请求

    print(f"🔎 开始捕获接口请求...")
    # 等待接口触发
    req = tab.listen.wait(timeout=timeout)
    tab.listen.stop()  # 捕获到后停止监听

    if not req:
        print(f"❌ {timeout} 秒内未捕获到接口请求。")
        return None

    # --- 1. 获取原始 URL 并修改 offset ---
    original_url = req.url
    print(f"✅ 捕获到原始接口: {original_url}")

    # 解析 URL 和查询参数
    parsed_url = urllib.parse.urlparse(original_url)
    query_params = urllib.parse.parse_qs(parsed_url.query)

    # 修改 offset 参数为 0（获取所有数据）
    query_params["offset"] = ["0"]

    # 重新构建查询字符串和完整的 URL
    new_query_string = urllib.parse.urlencode(query_params, doseq=True)
    new_url = urllib.parse.urlunparse(parsed_url._replace(query=new_query_string))

    print(f"🔄 正在用修改后的 URL (后台请求): {new_url}")

    # --- 2. 提取已登录的 Cookies ---
    current_cookies = tab.cookies()

    # 将 cookies 转换为字符串形式，作为 HTTP 请求的头部
    cookies_str = "; ".join(
        [f"{cookie['name']}={cookie['value']}" for cookie in current_cookies]
    )

    # 设置 headers，带上 cookies
    headers = {"Cookie": cookies_str}

    # --- 3. 使用 requests 发送请求 ---
    try:
        response = requests.get(new_url, headers=headers, timeout=timeout)
    except requests.exceptions.RequestException as e:
        print(f"❌ 请求失败: {e}")
        return None

    # --- 4. 检查和提取响应体 ---

    if response.status_code != 200:
        print(f"❌ 重新请求失败！HTTP 状态码: {response.status_code}")
        return None

    resp_body_text = response.text

    if not resp_body_text:
        print(f"❌ 重新请求成功 (200)，但响应体为空。")
        return None

    # --- 5. 解析 JSON 和 Gzip 解压 ---

    try:
        resp_json = json.loads(resp_body_text)
    except Exception as e:
        print(f"⚠️ 响应不是合法 JSON：{e}\n原始内容: {resp_body_text[:200]}")
        return None

    # 提取 gzip Base64 数据
    try:
        gzip_base64_str = resp_json["data"]["records"]
    except KeyError:
        print("❌ 未找到 data.records 字段，请检查返回结构。")
        return None

    try:
        gzip_bytes = base64.b64decode(gzip_base64_str)
        with gzip.GzipFile(fileobj=BytesIO(gzip_bytes)) as f:
            decompressed_data = f.read().decode("utf-8")
        records_json = json.loads(decompressed_data)
    except Exception as e:
        print(f"❌ 解压或解析失败: {e}")
        return None

    print("✅ 成功解压 JSON 数据！")
    return records_json, cookies_str


try:
    from selenium.webdriver.support import expected_conditions as EC
except Exception:
    EC = None


def normalize_text(s):
    if not s:
        return ""
    return s.replace('\u200b', '').strip()


def ensure_check_checkbox(driver, checkbox_id, timeout=10):
    """
    稳健选中 checkbox：滚动、点击 label 或 input，或后备设置 checked 并派发 change。
    """
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            input_el = WebDriverWait(driver, 1).until(
                EC.presence_of_element_located((By.ID, checkbox_id))
            )
        except Exception:
            driver.execute_script("window.scrollBy(0, 400);")
            time.sleep(0.4)
            continue

        try:
            label = driver.find_element(By.CSS_SELECTOR, f"label[for=\"{checkbox_id}\"]")
        except Exception:
            label = None

        target = label if label is not None else input_el
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target)
            driver.execute_script("window.scrollBy(0, -80);")
            time.sleep(0.25)
        except Exception:
            pass

        clicked = False
        if label:
            try:
                driver.execute_script("arguments[0].click();", label)
                clicked = True
            except Exception:
                clicked = False

        if not clicked:
            try:
                driver.execute_script("arguments[0].click();", input_el)
                clicked = True
            except Exception:
                clicked = False

        if not clicked:
            try:
                driver.execute_script(
                    "var el = document.getElementById(arguments[0]); if(el){ el.checked = true; el.dispatchEvent(new Event('change')); }",
                    checkbox_id
                )
            except Exception:
                pass

        try:
            is_checked = driver.execute_script(
                "var el = document.getElementById(arguments[0]); return !!(el && el.checked);", checkbox_id)
            if is_checked:
                print(f"✅ 已成功选中：{checkbox_id}")
                return True
        except Exception:
            pass

        time.sleep(0.4)

    print(f"❌ 无法选中 {checkbox_id}（超时）")
    return False


def click_next_footer(driver, timeout=5):
    """在页脚点击文本为 Next 的按钮"""
    end = time.time() + timeout
    while time.time() < end:
        buttons = driver.find_elements(By.CLASS_NAME, "card-footer-item")
        for btn in buttons:
            try:
                if btn.text.strip().lower() == "next":
                    btn.click()
                    return True
            except Exception:
                continue
        time.sleep(0.3)
    return False


def _toast_macos(message: str, title: str = "PrivacyTools") -> None:
    """macOS 通知（失败也不影响主流程）。"""
    try:
        if not message:
            return
        subprocess.run(
            ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        pass


def _close_modal_if_possible(driver) -> None:
    """尝试关闭弹窗，不行也不报错。"""
    try:
        btns = driver.find_elements(By.CSS_SELECTOR, ".modal.is-active .delete")
        if btns:
            driver.execute_script("arguments[0].click();", btns[0])
            time.sleep(0.2)
    except Exception:
        pass


# 
# GitHub Pages / SSH helpers
# 


def _decode_bytes(b: bytes | None) -> str:
    """Decode subprocess output safely (avoid Windows GBK crashes)."""
    if not b:
        return ""
    try:
        return b.decode("utf-8", errors="replace")
    except Exception:
        return b.decode(errors="replace")


def _run_capture(cmd: list[str], *, env: dict | None = None, cwd: str | None = None) -> tuple[int, str, str]:
    """Run a command and capture stdout/stderr safely (bytes -> utf-8 replace)."""
    p = subprocess.run(cmd, env=env, cwd=cwd, capture_output=True)
    return p.returncode, _decode_bytes(p.stdout), _decode_bytes(p.stderr)


def ensure_github_ssh_keychain_ready(key_path: str = "~/.ssh/id_ed25519_common_hosts") -> None:
    """Teammate-friendly: don't spam `ssh-add` output and don't block on passphrase.

    We only *check* whether key is loaded. If not loaded, we print a one-time hint.
    Loading should be done manually once:
      ssh-add --apple-use-keychain ~/.ssh/id_ed25519_common_hosts
    """

    def _pub_key_body(pub_text: str) -> str:
        parts = (pub_text or "").strip().split()
        return parts[1] if len(parts) >= 2 else ""

    try:
        kp = Path(key_path).expanduser()
        if not kp.exists():
            return

        pub_path = Path(str(kp) + ".pub")
        if not pub_path.exists():
            return

        want_body = _pub_key_body(pub_path.read_text(encoding="utf-8"))
        if not want_body:
            return

        ret, out, _err = _run_capture(["ssh-add", "-L"])
        if ret == 0 and want_body in (out or ""):
            return

        print(
            "\n⚠️ 检测到 GitHub Pages 的 SSH key 还未加载到 ssh-agent（或未保存到 Keychain）。\n"
            "请在终端手动执行一次（只需一次）：\n"
            f"  ssh-add --apple-use-keychain {kp}\n"
            "输入 passphrase 后，以后脚本运行就不会再提示。\n"
        )
    except Exception:
        pass


def _run_git_push_main_with_env() -> None:
    """Best-effort fallback push using the preferred SSH host alias.

    Note: We do NOT pass '-i key' here to avoid interactive passphrase prompts.
    Use ssh-agent+Keychain for non-interactive use.
    """
    env = os.environ.copy()
    env.setdefault("PRIVACY_PAGES_SSH_HOST", "github-common-hosts")

    env["GIT_SSH_COMMAND"] = (
        "ssh -o BatchMode=yes -o IdentitiesOnly=yes "
        "-o StrictHostKeyChecking=accept-new "
        "-o ControlMaster=auto -o ControlPersist=10m -o ControlPath=~/.ssh/cm-%r@%h:%p"
    )

    repo_root = Path(__file__).resolve().parent

    # push regardless of status (commit may already exist)
    subprocess.run(["git", "push", "origin", "main"], cwd=str(repo_root), env=env, check=False)


def publish_privacy_page_to_github(app_title: str, publish_id: str, content_file: Path) -> str:
    """Call googleSites.py to generate & push pages/<slug>/index.html.

    Return: published page URL (best-effort parsed).
    """
    env = os.environ.copy()
    env.setdefault("PRIVACY_PAGES_SSH_HOST", "github-common-hosts")
    env.setdefault("PRIVACY_PAGES_SSH_KEY", str(Path("~/.ssh/id_ed25519_common_hosts").expanduser()))

    safe_title = (app_title or "privacy-policy").strip() or "privacy-policy"
    safe_id = (publish_id or "").strip()

    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent / "googleSites.py"),
        "--title",
        safe_title,
        "--id",
        safe_id,
        "--content-file",
        str(content_file),
        "--commit-message",
        f"Publish privacy page: {safe_title}",
        "--no-wait",
    ]

    rc, stdout, stderr = _run_capture(cmd, env=env)
    combined = (stdout or "") + ("\n" + (stderr or "") if stderr else "")

    if combined.strip():
        print("------ googleSites.py 输出开始 ------")
        print(combined.strip())
        print("------ googleSites.py 输出结束 ------")

    m = re.search(r"(https?://[^\s]+/pages/[^\s]+/)", combined)
    page_url = m.group(1) if m else ""

    if rc != 0:
        print("⚠️ googleSites.py 返回非 0，尝试兜底 push 一次...")
        try:
            _run_git_push_main_with_env()
        except Exception:
            pass

    return page_url


def extract_and_show_privacy_text(driver, wait_seconds=12, publish_id: str = ""):
    driver.switch_to.default_content()
    try:
        WebDriverWait(driver, wait_seconds).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".modal.is-active #privacy_simple_content"))
        )
    except Exception:
        print("❌ 未检测到弹窗或 privacy_simple_content")
        return None

    # 直接获取元素的 innerHTML 而不是整页 HTML
    try:
        inner_html = driver.execute_script(
            "var el=document.getElementById('privacy_simple_content');return el?el.innerHTML:'';"
        )
    except Exception as e:
        print(f"❌ 获取 innerHTML 失败: {e}")
        return None

    if not inner_html:
        print("❌ privacy_simple_content.innerHTML 为空")
        return None

    text = html_to_formatted_text(inner_html)
    if not text:
        print("❌ 解析结果为空")
        return None

    # 1) 复制隐私文本到剪贴板 + toast
    copy_to_clipboard_macos(text)
    _toast_macos("隐私文本已复制", title="PrivacyTools")

    # 2) 写出到文件给 GitHub Pages 发布用
    try:
        PRIVACY_TEXT_OUT.write_text(text, encoding="utf-8")
        print(f"📝 已写入隐私文本到文件: {PRIVACY_TEXT_OUT}")
    except Exception as e:
        print(f"⚠️ 写入隐私文本文件失败: {e}")

    # 3) 控制台日志输出（可查）
    print("------ Privacy Policy 文本开始 ------")
    print(text)
    print("------ Privacy Policy 文本结束 ------")

    # 4) 复制完成后关闭网页/弹窗（先关 modal，再关 tab）
    _close_modal_if_possible(driver)
    try:
        driver.close()
    except Exception:
        pass

    # 5) 发布到 GitHub Pages：显示“网页发布中...”，成功后复制 URL + toast
    publish_url = ""
    try:
        app_title = (app_name or "privacy-policy").strip() or "privacy-policy"
        print("🚀 网页发布中。。。大概十几秒吧。。。")
        publish_url = publish_privacy_page_to_github(app_title=app_title, publish_id=publish_id, content_file=PRIVACY_TEXT_OUT)

        if publish_url:
            print(f"🌐 已发布网页地址: {publish_url}")
            copy_to_clipboard_macos(publish_url)
            _toast_macos("隐私网页链接已复制", title="PrivacyTools")

            # 6) 发布成功后清理不再需要的文件（根目录 index.html + privacy_text.txt）
            try:
                repo_root = Path(__file__).resolve().parent
                cleanup_paths = [repo_root / "index.html", repo_root / "privacy_text.txt"]
                for p in cleanup_paths:
                    if p.exists():
                        p.unlink()
                        print(f"🧹 已删除无用文件: {p}")
            except Exception as e:
                print(f"⚠️ 清理文件失败（可忽略）: {e}")
        else:
            print("⚠️ 未能从发布输出中提取 URL（但通常仍可能已发布成功，请看 googleSites.py 输出）。")
    except Exception as e:
        print(f"❌ 发布网页失败: {e}")

    return publish_url


def _replace_template_fields(template_html: str, app: str, creator: str, mail: str) -> str:
    """Replace key fields inside muban.html template.

    Replacements:
      1) In the first sentence: app name + created by name.
      2) Replace email occurrences in the whole template.

    Template keeps other content unchanged.
    """
    html_src = template_html or ""

    app_safe = html.escape(app or "", quote=True)
    creator_safe = html.escape(creator or "", quote=True)
    mail_safe = (mail or "").strip()

    # 1) Replace app name in the fixed phrase
    # Template line: "This privacy policy applies to the BeeKeeper Mania app (hereby referred to as ..."
    html_src = re.sub(
        r"(This privacy policy applies to\s+the\s+)(.+?)(\s+app\s*\(hereby referred to as &quot;Application&quot;\))",
        lambda m: m.group(1) + app_safe + m.group(3),
        html_src,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # 2) Replace creator name in the fixed phrase
    html_src = re.sub(
        r"(for mobile devices that was created by\s+)(.+?)(\s+\(hereby referred to as &quot;Service Provider&quot;\))",
        lambda m: m.group(1) + creator_safe + m.group(3),
        html_src,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # 3) Replace email everywhere (both plain and escaped forms)
    if mail_safe:
        old_emails = set(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", html_src))
        for old in sorted(old_emails, key=len, reverse=True):
            html_src = html_src.replace(old, mail_safe)
            html_src = html_src.replace(html.escape(old, quote=True), html.escape(mail_safe, quote=True))

    return html_src


def _html_to_plain_text_for_clipboard(rendered_html: str) -> str:
    """Convert our template HTML (with <br> and simple tags) into readable plain text."""
    s = rendered_html or ""
    # Keep line breaks
    s = re.sub(r"<\s*br\s*/?\s*>", "\n", s, flags=re.IGNORECASE)
    # Strip all tags
    s = re.sub(r"<[^>]+>", "", s)
    # Unescape HTML entities
    s = html.unescape(s)
    # Normalize multiple blank lines
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def generate_privacy_html_from_template() -> str:
    """Generate final privacy HTML by replacing fields in muban.html."""
    if not TEMPLATE_HTML_PATH.exists():
        raise FileNotFoundError(f"Template not found: {TEMPLATE_HTML_PATH}")

    template_html = TEMPLATE_HTML_PATH.read_text(encoding="utf-8")
    return _replace_template_fields(template_html, app=app_name or "", creator=company_name or "", mail=email or "")


def run_privacy_flow(driver, target_os="Android", publish_id: str = ""):
    """New flow: do NOT open privacy generator website.

    We already have app_name/company_name/email from the Lark pipeline.
    We render muban.html, replace key fields, copy plain text to clipboard,
    and publish the HTML to GitHub Pages.
    """

    # 让 target_os 默认是 Android（且保证类型正确）
    if not isinstance(target_os, str):
        real_type = type(target_os).__name__
        print(f"❌ target_os 类型错误，期望字符串，实际为: {real_type}，将回退为 Android")
        target_os = "Android"

    # 0) 渲染 muban.html 模板
    try:
        rendered_html = generate_privacy_html_from_template()
    except Exception as e:
        print(f"❌ 渲染模板失败: {e}")
        return False

    # 1) 复制纯文本到剪贴板，供用户粘贴
    text_for_clipboard = _html_to_plain_text_for_clipboard(rendered_html)
    if text_for_clipboard:
        copy_to_clipboard_macos(text_for_clipboard)
        _toast_macos("隐私文本已复制", title="PrivacyTools")

    print("------ Privacy Policy 文本 ------")
    print(text_for_clipboard)
    print("------ Privacy Policy 文本 ------")

    # 2) 将 HTML 写入文件，供 GitHub Pages 发布
    try:
        PRIVACY_TEXT_OUT.write_text(rendered_html, encoding="utf-8")
        print(f"📝 已写入隐私文本到文件: {PRIVACY_TEXT_OUT}")
    except Exception as e:
        print(f"⚠️ 写入隐私文本文件失败: {e}")

    # 3) 关闭任何已打开的浏览器（新流程不再需要）
    try:
        driver.quit()
    except Exception:
        pass

    # 4) 发布到 GitHub Pages（逻辑与之前相同）
    publish_url = ""
    try:
        app_title = (app_name or "privacy-policy").strip() or "privacy-policy"
        print("🚀 网页发布中。。。大概十几秒吧。。。")
        publish_url = publish_privacy_page_to_github(app_title=app_title, publish_id=publish_id, content_file=PRIVACY_TEXT_OUT)

        if publish_url:
            print(f"🌐 已发布网页地址: {publish_url}")
            copy_to_clipboard_macos(publish_url)
            _toast_macos("隐私网页链接已复制", title="PrivacyTools")
        else:
            print("⚠️ 未能从发布输出中提取 URL（但通常仍可能已发布成功，请看 googleSites.py 输出）。")
    except Exception as e:
        print(f"❌ 发布网页失败: {e}")

    return True



def find_and_collect_by_target_value(json_obj, target_value=None):
    """
    按订单号筛选并在找到时把 app_name 写入全局变量 app_name，继续返回结果列表。
    """
    # 顶层函数本身不直接读写 app_name，只在内部嵌套函数里操作

    if not target_value:
        print("❌ 需要提供 target_value (订单编号)，例如 'IGT1185'")
        return []

    results = []
    target_str = str(target_value).strip().lower()

    def _search(obj):
        # 这里显式声明使用全局 app_name，避免 UnboundLocalError
        global app_name

        if isinstance(obj, dict):
            fld_order = obj.get("fldxQWjXD7")
            if isinstance(fld_order, dict):
                val = fld_order.get("value")
                if isinstance(val, list):
                    for entry in val:
                        if isinstance(entry, dict):
                            text = (entry.get("text") or "").strip()
                            if text.lower() == target_str:
                                # 提取 app_name（来自 fldaShB3Gb 的第一个 value 的 text）
                                found_app_name = None
                                flda = obj.get("fldaShB3Gb")
                                if isinstance(flda, dict):
                                    fval = flda.get("value")
                                    if isinstance(fval, list) and fval:
                                        first = fval[0]
                                        if isinstance(first, dict):
                                            found_app_name = (first.get("text") or "").strip() or None

                                # 尝试在 fldnLglcRi 中写入 app_name 并返回其第一个 value
                                fldn = obj.get("fldnLglcRi")
                                if isinstance(fldn, dict):
                                    v = fldn.get("value")
                                    if isinstance(v, list) and v:
                                        first_item = v[0]
                                        if isinstance(first_item, dict):
                                            if found_app_name:
                                                first_item["app_name"] = found_app_name
                                            results.append(first_item)
                                        else:
                                            new_item = {"value": first_item}
                                            if found_app_name:
                                                new_item["app_name"] = found_app_name
                                            results.append(new_item)
                                    else:
                                        new_item = {}
                                        if found_app_name:
                                            new_item["app_name"] = found_app_name
                                        results.append(new_item)
                                else:
                                    if found_app_name:
                                        results.append({"app_name": found_app_name})
                                    else:
                                        results.append(obj)

                                # 无论之前是否有值，直接把找到的 app_name 赋给全局变量
                                if found_app_name:
                                    app_name = found_app_name
                                    print(f"🔧 已设置全局 app_name = `{app_name}`")

                                break

            # 继续递归查找子节点
            for v in obj.values():
                _search(v)

        elif isinstance(obj, list):
            for item in obj:
                _search(item)

    _search(json_obj)
    return results


def extract_vps_array_from_doc22(doc_data, cookies_str):
    global company_name, email
    print("🔎 提取页面中首个有效的 @gmail.com 邮箱...")
    results = []
    seen_urls = set()

    headers = {
        "Cookie": cookies_str or "",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/123.0 Safari/537.36",
    }

    email_re = re.compile(r'(?<![A-Za-z0-9._%+\-])([A-Za-z0-9._%+\-]+@gmail\.com)\b', re.I)

    def _clean_gmail_emails(raw_text):
        found = email_re.findall(raw_text or "")
        unique = []
        seen = set()
        for e in found:
            ne = e.strip().lower()
            if ne and ne not in seen:
                seen.add(ne)
                unique.append(ne)
        final = []
        sset = set(unique)
        for e in unique:
            if len(e) > 1 and e[1:] in sset and len(e[0]) == 1:
                continue
            final.append(e)
        return final

    for item in doc_data:
        url = item.get("link")
        text = item.get("text", "")
        if not url and not text:
            continue
        if url in seen_urls:
            continue

        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                print(f"❌ 请求失败: {url}, 状态码: {response.status_code}")
                continue

            page_content = html.unescape(response.text or "")
            emails = _clean_gmail_emails(page_content)
            primary = emails[0] if emails else ""

            # 首次发现时，设置全局 company_name 和 email（如果尚未设置）
            if not company_name:
                t = (text or "").strip()
                m = re.search(r'-(.+)$', t)
                if m:
                    company_name = m.group(1).strip()
                else:
                    parts = t.split(None, 1)
                    company_name = parts[1].strip() if len(parts) > 1 else (t or "")

            if primary and not email:
                email = primary.strip().lower()

            results.append(
                {
                    "text": text,
                    "url": url,
                    "email": primary,
                }
            )
            seen_urls.add(url)

        except Exception as e:
            print(f"❌ 解析失败: {url}, 错误: {e}")

        # 如果全局信息都已填充，可以选择提前退出以加快速度
        if company_name and email:
            break

    # 按 text 中的数字排序（保持原有行为）
    def _extract_number(t):
        m = re.search(r"(\d+)", (t or ""))
        return int(m.group(1)) if m else 0

    results.sort(key=lambda x: _extract_number(x.get("text")))

    for item in results:
        print(f"{item.get('text')}")
        if item.get('email'):
            print(f"  邮箱: {item.get('email')}")
        else:
            print("  邮箱: 未发现 @gmail.com 地址")
        print("-" * 50)

    print(f"✅ 总数量: {len(results)}")
    return results


def save_to_json(data, filename="none.json"):
    Path(filename).write_text(json.dumps(data, ensure_ascii=False, indent=2))
    # print(f"✅ 已保存 {len(data)} 条结果到 {filename}")


import argparse


if __name__ == "__main__":
    # 在运行 push 之前只做一次检查：如果 key 没加载，会提示同事执行一次 ssh-add
    ensure_github_ssh_keychain_ready()

    parser = argparse.ArgumentParser()
    parser.add_argument('id', nargs='?', help='表格中查找的编号，例如 IGT1128')
    args = parser.parse_args()

    # 交互获取 id（若未通过命令行提供）
    if not args.id:
        try:
            args.id = input("请输入编号（例如 IGT1128）：").strip()
        except (EOFError, KeyboardInterrupt):
            args.id = None

    if not args.id:
        print("❌ 未提供编号，脚本将退出。\n示例用法：python privacys.py IGT1128 --scan")
        sys.exit(2)

    try:
        records, cookies_str = get_gzip_json_from_api()
        if not records:
            print("❌ 未能获取 records，脚本退出")
            sys.exit(1)

        available_records = find_and_collect_by_target_value(records, target_value=args.id)
        vps_result = extract_vps_array_from_doc22(available_records, cookies_str)

        driver = create_driver()
        run_privacy_flow(driver=driver, target_os="Android", publish_id=args.id)
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
