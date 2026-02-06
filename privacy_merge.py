import html
import sys
import urllib
import subprocess
import os

import requests
import time
from bs4 import BeautifulSoup

import base64
import gzip
import json
import re
from io import BytesIO
from pathlib import Path
from DrissionPage import Chromium

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

# muban.html 模板路径（内容固定，只替换少量字段）
MUBAN_TEMPLATE_PATH = Path(__file__).resolve().parent / "muban.html"


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


# （已停用）以下 Selenium 相关逻辑为旧版隐私网站自动化流程，当前模板方案不再需要。
# 为避免运行期误触发打开/关闭浏览器，这里移除相关函数入口。
# - ensure_check_checkbox
# - click_next_footer
# - _close_modal_if_possible
# - extract_and_show_privacy_text
# - create_driver


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


def build_privacy_html_from_template(app_name_value: str, company_name_value: str, email_value: str) -> str:
    """基于 muban.html 替换关键字段生成最终 HTML。

    只做 2 处替换：
      1) "This privacy policy applies to the <APP> app ... created by <COMPANY> ..."
      2) "please contact the Service Provider via email at <EMAIL>."

    模板其他保持不变。
    """
    tpl = MUBAN_TEMPLATE_PATH.read_text(encoding="utf-8")

    app_safe = (app_name_value or "").strip()
    company_safe = (company_name_value or "").strip()
    email_safe = (email_value or "").strip()

    if not app_safe or not company_safe or not email_safe:
        print(f"⚠️ 模板替换字段可能为空: app_name={app_safe!r}, company_name={company_safe!r}, email={email_safe!r}")

    # 1) 替换 app_name / company_name（只替换这一句里的部分）
    #    用非贪婪匹配，尽量不破坏模板其它内容。
    def _repl_main(m: re.Match) -> str:
        return (
            "This privacy policy applies to the "
            + app_safe
            + " app"
            + m.group(1)
            + "created by "
            + company_safe
            + m.group(2)
        )

    main_pat = re.compile(
        r"This privacy policy applies to the\s+.*?\s+app(\s*\(hereby referred to as\s+&quot;Application&quot;\)\s+for mobile devices that was\s+)(?:created by\s+).*?(\s+\(hereby referred to as\s+&quot;Service Provider&quot;\)\s+as a Free service)",
        re.I | re.S,
    )
    new_tpl, n1 = main_pat.subn(_repl_main, tpl, count=1)
    if n1 == 0:
        # 兜底：如果模板句子略有不同，尝试宽松一点的匹配
        loose_pat = re.compile(r"This privacy policy applies to the\s+.*?\s+app\s*\(.*?\)\s+for mobile devices that was created by\s+.*?\s*\(.*?\)\s+as a Free service", re.I | re.S)
        loose_match = loose_pat.search(new_tpl)
        if loose_match:
            s = loose_match.group(0)
            s2 = re.sub(r"This privacy policy applies to the\s+.*?\s+app", f"This privacy policy applies to the {app_safe} app", s, flags=re.I | re.S)
            s2 = re.sub(r"created by\s+.*?\s*\(", f"created by {company_safe} (", s2, flags=re.I | re.S)
            new_tpl = new_tpl.replace(s, s2)
            n1 = 1

    # 2) 替换底部 Contact Us 里的邮箱（可能出现多次，我们替换全部）
    #    按用户说的那句来替换（不改变其它地方）
    contact_pat = re.compile(
        r"please contact the Service Provider via email at\s+[^<\s]+@gmail\.com\.",
        re.I,
    )
    new_tpl2, n2 = contact_pat.subn(
        f"please contact the Service Provider via email at {email_safe}.",
        new_tpl,
    )

    # 模板里也可能有括号形式的邮箱（例如 Children 段），一并替换同一个邮箱
    new_tpl3 = re.sub(r"\([^\s()]+@gmail\.com\)", f"({email_safe})", new_tpl2, flags=re.I)

    if n1 == 0:
        print("⚠️ 未命中模板主句替换（app_name/company_name），请确认 muban.html 中该句是否有改动。")
    if n2 == 0:
        print("⚠️ 未命中模板 Contact Us 邮箱替换（email），请确认 muban.html 中该句是否有改动。")

    return new_tpl3


def privacy_html_to_plain_text(html_doc: str) -> str:
    """把模板 HTML 转成更适合粘贴的纯文本，保留换行/列表/链接。"""
    soup = BeautifulSoup(html_doc or "", "html.parser")
    content = soup.select_one("#privacy_simple_content")
    # 我们的 muban.html 不一定有这个 id，这里兼容：优先取 .content
    if content is None:
        content = soup.select_one(".content")
    if content is None:
        content = soup

    # 使用已有的 html_to_formatted_text：它接受 innerHTML
    return html_to_formatted_text(str(content))


def generate_privacy_text_from_muban() -> str:
    """直接用 muban.html 生成隐私文本（无需打开隐私生成网站）。"""
    html_doc = build_privacy_html_from_template(app_name, company_name, email)
    text = privacy_html_to_plain_text(html_doc)
    if not text:
        raise RuntimeError("未能从 muban.html 生成可用的隐私文本")

    # 写文件供发布脚本使用
    PRIVACY_TEXT_OUT.write_text(text, encoding="utf-8")
    return text


# python
def run_privacy_flow(publish_id: str = ""):
    """生成隐私文本文件并发布到 GitHub Pages。

    注意：此流程不再打开 Selenium 浏览器。
    浏览器仅用于 get_gzip_json_from_api() 的 Lark 登录/抓取。
    """

    # 1) 用模板生成隐私文本（写入 privacy_text.txt）
    _ = generate_privacy_text_from_muban()

    # 2) 发布到 GitHub Pages
    print("🚀 网页发布中。。。")
    page_url = publish_privacy_page_to_github(
        app_title=(app_name or "privacy-policy"),
        publish_id=publish_id,
        content_file=PRIVACY_TEXT_OUT,
    )

    if page_url:
        print(f"🌐 已发布网页地址: {page_url}")

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

        # 不再创建 selenium driver（避免运行期间浏览器弹起又关闭）
        run_privacy_flow(publish_id=args.id)
    finally:
        # get_gzip_json_from_api 使用的是 DrissionPage Chromium，不是 selenium driver；这里不做 driver.quit()
        pass
