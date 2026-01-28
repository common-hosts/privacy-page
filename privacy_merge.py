import html
import sys
import urllib
import subprocess

import requests
from selenium import webdriver
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


# python
def extract_and_show_privacy_text(driver, wait_seconds=12):
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

    # 尝试复制到系统剪贴板
    copy_to_clipboard_macos(text)

    # 同时写出到文件，方便后续 GitHub Pages 发布
    try:
        PRIVACY_TEXT_OUT.write_text(text, encoding="utf-8")
        print(f"📝 已写入隐私文本到文件: {PRIVACY_TEXT_OUT}")
    except Exception as e:
        print(f"⚠️ 写入隐私文本文件失败: {e}")

    driver.execute_script(
        """
        (function(value){
            let ta = document.getElementById('privacy_plain_textarea');
            if(!ta){
                ta = document.createElement('textarea');
                ta.id = 'privacy_plain_textarea';
                Object.assign(ta.style,{
                    position:'fixed',right:'20px',top:'20px',width:'520px',height:'600px',
                    whiteSpace:'pre-wrap',zIndex:2147483647,fontSize:'12px',padding:'8px',
                    background:'#fff',border:'1px solid rgba(0,0,0,0.2)',boxShadow:'0 2px 8px rgba(0,0,0,0.15)',
                    resize:'both'
                });
                ta.onclick=function(){this.select();};
                document.body.appendChild(ta);
            }
            ta.value=value;
            ta.style.display='block';
            ta.focus();
            ta.select();
            let copied=false;
            try{document.execCommand('copy');copied=true;}catch(e){console.warn('copy failed',e);}
            if(copied){
                let toast=document.getElementById('privacy_copy_toast');
                if(!toast){
                    toast=document.createElement('div');
                    toast.id='privacy_copy_toast';
                    Object.assign(toast.style,{
                        position:'fixed',bottom:'30px',right:'30px',padding:'10px 18px',
                        background:'rgba(0,0,0,0.8)',color:'#fff',borderRadius:'6px',
                        fontSize:'14px',zIndex:2147483647,transition:'opacity 0.3s'
                    });
                    document.body.appendChild(toast);
                }
                toast.textContent='隐私文本已复制';
                toast.style.opacity='1';
                setTimeout(()=>{toast.style.opacity='0';},2000);
            }
            console.log('PRIVACY_PLAIN_TEXT_START\\n'+value+'\\nPRIVACY_PLAIN_TEXT_END');
        })(arguments[0]);
        """,
        text,
    )

    print("------ Privacy Policy 文本开始 ------")
    print(text)
    print("------ Privacy Policy 文本结束 ------")
    print("------ 已复制到系统剪贴板 (pbcopy) ------")

    # 可选：自动发布到 GitHub Pages（依赖 googleSites.py + git push SSH）
    try:
        # googleSites.py 页面的 H1/<title> 已固定为 Privacy Policy，这里的 title 仅用于生成 slug 后半部分
        app_title = (app_name or "privacy-policy").strip() or "privacy-policy"

        subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parent / "googleSites.py"),
                # title 用 app_name（用于 slug 后缀），页面展示标题固定，不会显示这个
                "--title",
                app_title,
                # id 用用户输入编号（用于 slug 前缀 base64）
                "--id",
                str(args.id),
                "--content-file",
                str(PRIVACY_TEXT_OUT),
                "--commit-message",
                f"Publish privacy page: {app_title}",
            ],
            check=False,
        )
    except Exception as e:
        print(f"⚠️ 自动发布到 GitHub Pages 失败（不影响后续流程）: {e}")

    return text


def run_privacy_flow(driver, target_os="Android"):
    """
    执行隐私生成流程（基于 app-privacy-policy-generator）。

    :param driver: selenium WebDriver 实例
    :param target_os: 目标 OS 字符串，例如 "iOS" / "Android"
    """
    global app_name, company_name, email

    # 防止把 WebDriver 或其它对象当成 target_os 传进来
    if not isinstance(target_os, str):
        real_type = type(target_os).__name__
        print(f"❌ target_os 类型错误，期望字符串，实际为: {real_type}")
        # 尝试回退到默认值
        target_os = "Android"

    target_os = (target_os or "").strip()
    if not target_os:
        print("❌ target_os 为空字符串，使用默认 'Android'")
        target_os = "Android"

    driver.get(PRIVACY_GEN_URL)
    try:
        WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "start-btn"))
        ).click()
    except Exception:
        pass

    # 等待 appName 输入出现
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.ID, "appName"))
    )
    driver.find_element(By.ID, "appName").clear()
    driver.find_element(By.ID, "appName").send_keys(app_name or "")
    driver.find_element(By.ID, "appContact").clear()
    driver.find_element(By.ID, "appContact").send_keys(email or "")
    time.sleep(0.2)
    click_next_footer(driver)

    # 继续点击 Next（可能需要多步）
    time.sleep(0.2)
    click_next_footer(driver)
    time.sleep(0.2)

    # 选择 Mobile OS
    radios = driver.find_elements(By.CSS_SELECTOR, 'input[type="radio"]')
    chosen = False
    for r in radios:
        try:
            val = (r.get_attribute("value") or "").strip()
            if val and val.lower() == target_os.lower():
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});", r
                )
                r.click()
                chosen = True
                print(f"✅ 已选择 Mobile OS: {target_os}")
                break
        except Exception:
            continue
    if not chosen:
        # 打印页面里实际可用的 value，方便排查
        available = []
        for r in radios:
            try:
                v = (r.get_attribute("value") or "").strip()
                if v:
                    available.append(v)
            except Exception:
                continue
        print(
            f"❌ 没有找到 OS 选项: {target_os}，页面可用选项: {available or '[]'}"
        )

    time.sleep(0.2)
    click_next_footer(driver)
    time.sleep(0.2)

    # 填写 Company Name
    dev_input = driver.find_elements(By.ID, "devName")
    if dev_input:
        el = dev_input[0]
        el.clear()
        el.send_keys(company_name or "")
        print("✅ 已填写 Company Name")
    time.sleep(0.2)
    click_next_footer(driver)
    time.sleep(0.2)

    # 勾选第三方服务（示例 id 列表，可以根据页面实际 id 调整）
    third_party_ids = [
        "list-switch-Google Analytics for Firebase",
        "list-switch-Firebase Crashlytics",
        "list-switch-Adjust",
    ]
    for cid in third_party_ids:
        ensure_check_checkbox(driver, cid, timeout=6)
        time.sleep(0.2)

    # Next -> Privacy Policy
    time.sleep(0.2)
    click_next_footer(driver)
    time.sleep(0.2)

    # 点击 Privacy Policy 按钮
    footer_links = driver.find_elements(By.CLASS_NAME, "card-footer-item")
    clicked_priv = False
    for link in footer_links:
        try:
            if link.text.strip().lower() == "privacy policy":
                link.click()
                clicked_priv = True
                print("✅ 已点击 Privacy Policy")
                break
        except Exception:
            continue
    if not clicked_priv:
        print("❌ 没有找到 Privacy Policy 按钮")
    extract_and_show_privacy_text(driver)
    # return True


# def create_driver(headless=False, user_data_dir=None, profile_dir=None):
#     opts = webdriver.ChromeOptions()
#     opts.add_argument('--start-maximized')
#     if headless:
#         opts.add_argument('--headless=new')
#     if user_data_dir:
#         opts.add_argument(f'--user-data-dir={user_data_dir}')
#     if profile_dir:
#         opts.add_argument(f'--profile-directory={profile_dir}')
#     return webdriver.Chrome(options=opts)

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

def create_driver(headless=False, user_data_dir=None, profile_dir=None, chrome_binary=None):
    opts = webdriver.ChromeOptions()
    opts.add_argument('--start-maximized')
    if headless:
        opts.add_argument('--headless=new')
    if user_data_dir:
        opts.add_argument(f'--user-data-dir={user_data_dir}')
    if profile_dir:
        opts.add_argument(f'--profile-directory={profile_dir}')
    if chrome_binary:
        opts.binary_location = chrome_binary  # 可选：显式指定 Chrome 可执行文件路径
    service = Service(ChromeDriverManager().install())  # 自动下载并使用匹配的 chromedriver
    return webdriver.Chrome(service=service, options=opts)


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
        run_privacy_flow(driver=driver, target_os="Android")
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
