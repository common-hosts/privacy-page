// ==UserScript==
// @name         飞书多维表格 VPS 自动提取
// @version      1.3.3
// @description  在飞书多维表格页筛选 QST 工作室 VPS 记录，拼接 vpsPassword 供酷鸟云分享页脚本自动填密码
// @author       kili
// @match        https://superxgr.larksuite.com/base/SebGbrq2yaNXXSsVOcJudpzxsCf*
// @grant        GM_addStyle
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_openInTab
// @grant        unsafeWindow
// @connect      *
// @run-at       document-start
// ==/UserScript==

(function () {
  "use strict";

  const uw = typeof unsafeWindow !== "undefined" ? unsafeWindow : window;

  const TABLE_HOST = "superxgr.larksuite.com";
  const API_KEYWORD = "SebGbrq2yaNXXSsVOcJudpzxsCf/records";
  const STORAGE_VPS_QUEUE = "vps_auto_enter_queue";

  const GAME_DEV_DATA = {
    "kili.g": "optnpNmerL",
    "milk.l": "optOikPJ0o",
    "mihu.o": "optYiUhmQF",
    "udnolk.x": "opttF4cmah",
    "vito.l": "optErloYaW",
  };
  const STUDIO_QST = "optZqg8fvW";
  const STATUS_PUBLISHED = "optbYwscO4";
  const STATUS_REVIEW = "optoR3b5JJ";

  function formatCreatorName(key) {
    const [name, domain] = key.split(".");
    const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
    return `${cap(name)}.${cap(domain)}`;
  }

  function buildCreatorOptionsHtml() {
    return Object.keys(GAME_DEV_DATA)
      .map(
        (key) =>
          `<option value="${formatCreatorName(key)}">${formatCreatorName(key)}</option>`
      )
      .join("");
  }

  // 在【页面上下文】注入 hook，才能捕获飞书自己的 fetch/XHR
  if (location.hostname === TABLE_HOST) {
    const hook = document.createElement("script");
    hook.textContent = `(() => {
      const K = ${JSON.stringify(API_KEYWORD)};
      const save = (url, method, gzipB64) => {
        if (!url || !String(url).includes(K)) return;
        const u = String(url);
        window.__larkCapturedRecordsUrl = u;
        window.__larkCapturedRecordsMeta = { url: u, method: method || "GET" };
        if (gzipB64) {
          window.__larkCapturedRecordsGzip = gzipB64;
          const size = gzipB64.length;
          if (!window.__larkBestGzipSize || size > window.__larkBestGzipSize) {
            window.__larkBestGzipSize = size;
            window.__larkBestRecordsGzip = gzipB64;
            window.__larkBestRecordsUrl = u;
          }
        }
      };
      const origFetch = window.fetch;
      window.fetch = function (...args) {
        const url = typeof args[0] === "string" ? args[0] : args[0]?.url;
        const p = origFetch.apply(this, args);
        if (url && String(url).includes(K)) {
          p.then(async (resp) => {
            try {
              const json = await resp.clone().json();
              save(url, args[1]?.method, json?.data?.records);
            } catch (_) {}
          }).catch(() => {});
        }
        return p;
      };
      const origOpen = XMLHttpRequest.prototype.open;
      XMLHttpRequest.prototype.open = function (method, url, ...rest) {
        if (url && String(url).includes(K)) {
          this.addEventListener("load", function () {
            try {
              const json = JSON.parse(this.responseText);
              save(url, method, json?.data?.records);
            } catch (_) {}
          });
        }
        return origOpen.call(this, method, url, ...rest);
      };
    })();`;
    (document.documentElement || document.head).appendChild(hook);
    hook.remove();
  }

  if (location.hostname !== TABLE_HOST) return;

  window.addEventListener("load", injectPanel);

  function injectPanel() {
    GM_addStyle(`
      #vps-auto-panel {
        position: fixed; right: 16px; bottom: 16px; z-index: 999999;
        width: 320px; background: #fff; border: 1px solid #ddd;
        border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,.15);
        font: 13px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        color: #1f2329;
      }
      #vps-auto-panel header {
        padding: 10px 12px; font-weight: 600; border-bottom: 1px solid #eee;
        display: flex; justify-content: space-between; align-items: center;
      }
      #vps-auto-panel .body { padding: 10px 12px; }
      #vps-auto-panel label { display: block; margin-bottom: 4px; color: #646a73; }
      #vps-auto-panel select, #vps-auto-panel button {
        width: 100%; box-sizing: border-box; margin-bottom: 8px;
        padding: 6px 8px; border-radius: 4px; border: 1px solid #d0d3d6;
      }
      #vps-auto-panel button {
        cursor: pointer; background: #3370ff; color: #fff; border-color: #3370ff;
      }
      #vps-auto-panel button:disabled { opacity: .6; cursor: not-allowed; }
      #vps-auto-panel button.secondary { background: #fff; color: #3370ff; }
      #vps-auto-panel #vps-log {
        max-height: 200px; overflow: auto; background: #f5f6f7;
        padding: 8px; border-radius: 4px; font-size: 12px; white-space: pre-wrap;
      }
      #vps-auto-panel #vps-links {
        max-height: 120px; overflow: auto; margin-top: 6px;
        font-size: 11px; word-break: break-all;
      }
      #vps-auto-panel #vps-links a {
        display: block; color: #3370ff; margin-bottom: 4px;
      }
    `);

    const panel = document.createElement("div");
    panel.id = "vps-auto-panel";
    panel.innerHTML = `
      <header>
        <span>VPS 自动提取 v1.3.3</span>
        <button type="button" id="vps-panel-close" style="width:auto;margin:0;padding:2px 8px;background:#fff;color:#646a73;border:1px solid #ddd;">×</button>
      </header>
      <div class="body">
        <label>创始人</label>
        <select id="vps-creator">
          ${buildCreatorOptionsHtml()}
        </select>
        <button type="button" id="vps-run">获取记录并提取 VPS</button>
        <button type="button" id="vps-open-all" class="secondary" disabled>打开全部 VPS（${GM_getValue("vps_last_count", 0)}）</button>
        <div id="vps-log">已登录飞书即可，无需脚本内扫码。\n等待表格数据加载后点击按钮。</div>
        <div id="vps-links"></div>
      </div>
    `;
    document.body.appendChild(panel);

    document.getElementById("vps-panel-close").onclick = () => panel.remove();
    document.getElementById("vps-run").onclick = runWorkflow;
    document.getElementById("vps-open-all").onclick = openAllVps;
  }

  function log(msg) {
    const el = document.getElementById("vps-log");
    if (el) el.textContent += `\n${msg}`;
    console.log("[VPS]", msg);
  }

  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  /** 必须用页面上下文的 fetch，沙箱 fetch 不带飞书 Cookie */
  async function pageFetch(url, options = {}) {
    const timeout = options.timeout ?? 120000;
    const controller = new uw.AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const { timeout: _t, ...rest } = options;
      return await uw.fetch(url, {
        credentials: "include",
        ...rest,
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }
  }

  function buildFullRecordsUrl(originalUrl) {
    const u = new URL(originalUrl, location.origin);
    u.searchParams.set("offset", "0");
    return u.toString();
  }

  /** 酷鸟云 VPS：拼接 vpsPassword，供「Kuniao云VPS分享页自动打开」脚本识别 */
  function buildVpsOpenUrl(baseLink, password) {
    if (!baseLink) return "";
    try {
      const u = new URL(baseLink);
      if (password) u.searchParams.set("vpsPassword", password);
      return u.toString();
    } catch {
      if (!password) return baseLink;
      const sep = baseLink.includes("?") ? "&" : "?";
      return `${baseLink}${sep}vpsPassword=${encodeURIComponent(password)}`;
    }
  }

  async function decompressGzipBase64(b64) {
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    if (typeof uw.DecompressionStream === "undefined") {
      throw new Error("浏览器不支持 DecompressionStream，请用 Chrome 113+");
    }
    // pipeThrough 比手动 write/close 更稳定，避免卡死
    const ds = new uw.DecompressionStream("gzip");
    const blob = new uw.Blob([bytes]);
    const decompressed = new uw.Response(blob.stream().pipeThrough(ds));
    return decompressed.text();
  }

  async function fetchRecordsJson(url, onProgress) {
    onProgress("📡 正在请求 API（全量数据可能较慢）…");
    const resp = await pageFetch(url, { timeout: 180000 });
    onProgress(`📡 API 响应 HTTP ${resp.status}`);

    if (!resp.ok) {
      const snippet = (await resp.text()).slice(0, 200);
      throw new Error(`HTTP ${resp.status}: ${snippet}`);
    }

    onProgress("📦 正在解析 JSON…");
    const respJson = await resp.json();
    const gzipB64 = respJson?.data?.records;
    if (!gzipB64) {
      throw new Error("响应缺少 data.records，可能未登录或接口结构变了");
    }

    const sizeKb = Math.round((gzipB64.length * 3) / 4 / 1024);
    onProgress(`🗜️ 正在解压 gzip（约 ${sizeKb} KB）…`);
    const text = await decompressGzipBase64(gzipB64);
    onProgress(`✅ 解压完成（${Math.round(text.length / 1024)} KB 明文）`);
    return JSON.parse(text);
  }

  function getRecordMap(jsonObj) {
    if (!jsonObj || typeof jsonObj !== "object") return null;
    if (jsonObj.recordMap && typeof jsonObj.recordMap === "object") {
      return jsonObj.recordMap;
    }
    if (jsonObj.data?.recordMap) return jsonObj.data.recordMap;
    return null;
  }

  function countRecordMap(jsonObj) {
    const rm = getRecordMap(jsonObj);
    return rm ? Object.keys(rm).length : 0;
  }

  async function loadRecordsFromGzip(gzipB64, onProgress) {
    onProgress("📦 正在解压页面 records…");
    const text = await decompressGzipBase64(gzipB64);
    const records = JSON.parse(text);
    onProgress(
      `📊 recordMap ${countRecordMap(records)} 条 / table ${records.tableRecordNum ?? "?"} 条`
    );
    return records;
  }

  async function loadRecords(onProgress) {
    const cachedGzip = uw.__larkBestRecordsGzip || uw.__larkCapturedRecordsGzip;
    const capturedUrl = uw.__larkBestRecordsUrl || uw.__larkCapturedRecordsUrl;

    if (cachedGzip) {
      let records = await loadRecordsFromGzip(cachedGzip, onProgress);
      const cachedSize = countRecordMap(records);
      const tableTotal = records.tableRecordNum || 0;

      // 页面缓存偏少时再尝试 offset=0 全量拉取
      if (capturedUrl && tableTotal > 0 && cachedSize < tableTotal * 0.5) {
        onProgress("📡 页面数据不完整，尝试 offset=0 拉全量…");
        try {
          const fullRecords = await fetchRecordsJson(
            buildFullRecordsUrl(capturedUrl),
            onProgress
          );
          if (countRecordMap(fullRecords) > cachedSize) {
            records = fullRecords;
          } else {
            onProgress("⚠️ 全量拉取未更全，继续使用页面数据");
          }
        } catch (e) {
          onProgress(`⚠️ 全量拉取失败: ${e.message}，继续使用页面数据`);
        }
      }
      return records;
    }

    if (!capturedUrl) return null;
    onProgress("⚠️ 未缓存 gzip，改走 API 拉取…");
    return fetchRecordsJson(buildFullRecordsUrl(capturedUrl), onProgress);
  }

  function matchCreator(fld7ebTKE0, creatorName, currentUser) {
    if (!fld7ebTKE0) return false;
    const val = fld7ebTKE0.value;
    if (val && String(val).toLowerCase() === String(currentUser).toLowerCase()) {
      return true;
    }
    const users = fld7ebTKE0.value?.users || fld7ebTKE0.users;
    if (Array.isArray(users)) {
      return users.some(
        (u) => (u.name || "").toLowerCase() === creatorName.toLowerCase()
      );
    }
    return false;
  }

  function debugFilterStats(jsonObj, creatorName) {
    const currentUser = GAME_DEV_DATA[creatorName.toLowerCase()];
    const stats = {
      recordMap: countRecordMap(jsonObj),
      statusOk: 0,
      creatorOk: 0,
      studioOk: 0,
      docOk: 0,
    };

    function walk(obj) {
      if (!obj || typeof obj !== "object") return;
      if (Array.isArray(obj)) {
        obj.forEach(walk);
        return;
      }
      const fldX = obj.fldX6h4A4P;
      if (
        fldX &&
        (fldX.value === STATUS_PUBLISHED || fldX.value === STATUS_REVIEW)
      ) {
        stats.statusOk++;
        if (matchCreator(obj.fld7ebTKE0, creatorName, currentUser)) {
          stats.creatorOk++;
          const studio = obj.flde65I8Bc;
          if (studio && studio.value === STUDIO_QST) {
            stats.studioOk++;
            const val = obj.fldnLglcRi?.value;
            if (Array.isArray(val) && val.length) stats.docOk++;
          }
        }
      }
      Object.values(obj).forEach(walk);
    }

    const rm = getRecordMap(jsonObj);
    if (rm) walk(rm);
    return stats;
  }

  function findAndCollectByTargetValue(jsonObj, creatorName) {
    const results = [];
    const currentUser = GAME_DEV_DATA[creatorName.toLowerCase()];
    if (!currentUser) return results;

    function searchRecord(obj) {
      if (!obj || typeof obj !== "object") return;
      if (Array.isArray(obj)) {
        obj.forEach(searchRecord);
        return;
      }

      const fldX = obj.fldX6h4A4P;
      const statusOk =
        fldX &&
        (fldX.value === STATUS_PUBLISHED || fldX.value === STATUS_REVIEW);

      if (statusOk) {
        const creatorMatched = matchCreator(
          obj.fld7ebTKE0,
          creatorName,
          currentUser
        );

        const studioField = obj.flde65I8Bc;
        const studioMatched = studioField && studioField.value === STUDIO_QST;

        if (creatorMatched && studioMatched) {
          const val = obj.fldnLglcRi?.value;
          if (Array.isArray(val) && val.length) results.push(val[0]);
        }
      }

      Object.values(obj).forEach(searchRecord);
    }

    const recordMap = getRecordMap(jsonObj);
    if (recordMap) searchRecord(recordMap);
    return results;
  }

  async function extractVpsFromDocs(docData, onProgress) {
    const results = [];
    const seen = new Set();

    for (let i = 0; i < docData.length; i++) {
      const item = docData[i];
      const url = item.link;
      const text = item.text;
      if (!url || !text) continue;

      const numMatch = text.match(/(\d+)/);
      if (!numMatch) continue;
      const number = parseInt(numMatch[1], 10);

      onProgress(`📄 [${i + 1}/${docData.length}] 解析 ${text}…`);

      try {
        const resp = await pageFetch(url, { timeout: 30000 });
        if (!resp.ok) {
          log(`❌ 文档失败 ${text}: HTTP ${resp.status}`);
          continue;
        }

        const page = unescapeHtml(await resp.text());

        let vpsLink = "";
        const aMatch = page.match(/https?:\/\/[^\s"'<>]*ipAddress=[^\s"'<>]*/);
        if (aMatch) {
          vpsLink = aMatch[0].trim();
        } else {
          const spanMatch = page.match(
            /<div class="code-line-wrapper"[^>]*data-line-num="1"[^>]*>.*?<span[^>]*>(.*?)<\/span>/s
          );
          if (spanMatch) vpsLink = spanMatch[1].trim();
        }
        let password = "";
        const pwdMatch = page.match(
          /<div class="code-line-wrapper"[^>]*data-line-num="2"[^>]*>.*?<span[^>]*>(.*?)<\/span>/s
        );
        if (pwdMatch) {
          const pw = pwdMatch[1].match(/访问密码[:：\s]*([^\s，,。；]+)/);
          if (pw) password = pw[1].trim();
        }

        const openUrl = buildVpsOpenUrl(vpsLink, password);
        const key = openUrl;
        if (seen.has(key)) {
          log(`⚠️ 重复跳过: ${text}`);
          continue;
        }
        seen.add(key);

        results.push({ text, url, vps_link: openUrl, password, number });
        log(`${number}: ${text}`);
        log(`  ${openUrl}`);
      } catch (e) {
        log(`❌ ${text}: ${e.message}`);
      }
    }

    results.sort((a, b) => a.number - b.number);
    return results;
  }

  function unescapeHtml(html) {
    const ta = document.createElement("textarea");
    ta.innerHTML = html;
    return ta.value;
  }

  async function runWorkflow() {
    const btn = document.getElementById("vps-run");
    const openBtn = document.getElementById("vps-open-all");
    const creator = document.getElementById("vps-creator").value;
    const logEl = document.getElementById("vps-log");
    logEl.textContent = "开始…";

    btn.disabled = true;
    const progress = (msg) => log(msg);

    try {
      const captured = uw.__larkBestRecordsUrl || uw.__larkCapturedRecordsUrl;
      const hasGzip = !!(uw.__larkBestRecordsGzip || uw.__larkCapturedRecordsGzip);

      if (!captured && !hasGzip) {
        log("未捕获到接口，3 秒后刷新页面…");
        await sleep(3000);
        location.reload();
        return;
      }

      log("✅ 已捕获接口");
      if (captured) console.log("[VPS] capturedUrl:", captured);

      const records = await loadRecords(progress);
      if (!records) throw new Error("无法获取 records 数据");

      const filtered = findAndCollectByTargetValue(records, creator);
      log(`🔎 筛选到 ${filtered.length} 条 (creator=${creator}, QST)`);

      if (!filtered.length) {
        const s = debugFilterStats(records, creator);
        log(
          `🔬 诊断: recordMap=${s.recordMap}, 状态=${s.statusOk}, 创始人=${s.creatorOk}, QST=${s.studioOk}, 有文档=${s.docOk}`
        );
        log("无匹配记录。请确认表格已加载完，或换创始人后重试");
        return;
      }

      const vpsList = await extractVpsFromDocs(filtered, progress);
      log(`✅ 共 ${vpsList.length} 个 VPS`);

      GM_setValue(STORAGE_VPS_QUEUE, vpsList);
      GM_setValue("vps_last_count", vpsList.length);
      openBtn.disabled = vpsList.length === 0;
      openBtn.textContent = `打开全部 VPS（${vpsList.length}）`;
      renderVpsLinks(vpsList);
    } catch (e) {
      const msg = e.name === "AbortError" ? "请求超时（>3分钟），数据量太大或网络慢" : e.message;
      log(`❌ ${msg}`);
      console.error("[VPS]", e);
    } finally {
      btn.disabled = false;
    }
  }

  function renderVpsLinks(list) {
    const box = document.getElementById("vps-links");
    if (!box) return;
    if (!list.length) {
      box.innerHTML = "";
      return;
    }
    box.innerHTML = list
      .map(
        (item) =>
          `<a href="${item.vps_link}" target="_blank" rel="noopener">${item.number}: ${item.text}</a>`
      )
      .join("");
  }

  /** 必须在用户点击的同步调用栈内打开，不能用 setTimeout，否则会被拦 */
  function openUrlInNewTab(url) {
    if (typeof GM_openInTab === "function") {
      GM_openInTab(url, { active: false, insert: true, setParent: true });
      return true;
    }
    return !!window.open(url, "_blank", "noopener");
  }

  function openAllVps() {
    const list = GM_getValue(STORAGE_VPS_QUEUE, []);
    if (!list.length) {
      log("无 VPS 数据，请先执行提取");
      return;
    }

    renderVpsLinks(list);

    let opened = 0;
    let blocked = 0;
    for (const item of list) {
      if (openUrlInNewTab(item.vps_link)) {
        opened++;
        log(`打开 ${item.number}: ${item.text}`);
      } else {
        blocked++;
      }
    }

    if (blocked) {
      log(`⚠️ ${blocked} 个被浏览器拦截，请允许本页弹窗后重试，或点下方链接逐个打开`);
    } else {
      log(`✅ 已打开 ${opened} 个 VPS 标签页`);
    }
  }
})();
