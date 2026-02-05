<!-- filepath: /Users/milk/PrivacyTools/README.md -->
# PrivacyTools

这套脚本用于：
1) 从 Lark 多维表格按“编号（例如 IGT1128）”查数据；
2) 自动在隐私协议生成器网站填充信息并勾选第三方；
3) 从弹窗提取隐私协议文本（可粘贴的纯文本格式），复制到系统剪贴板；
4) 自动发布到 GitHub Pages，并把发布后的 URL 复制到剪贴板。

> 备注：当前主入口脚本是 `privacy_merge.py`。

---

## 使用前提

- macOS
- 已安装 Google Chrome
- 能访问 Lark 表格（工作账号可正常打开链接）
- 具备向 GitHub 组织仓库 `common-hosts/privacy-page` 推送权限（Write）

---

## 1. 安装与首次配置（每台电脑只做一次）

### 1.1 拉取代码

````bash
git clone <仓库地址>
cd PrivacyTools
````

### 1.2 Python 虚拟环境

````bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
````

### 1.3 安装依赖

如果仓库里已有 `requirements.txt`：

````bash
pip install -r requirements.txt
````

如果没有 `requirements.txt`，请联系维护者补齐（建议补一个，方便同事一键安装）。

---

## 2. GitHub Pages 推送权限（必须）

脚本在发布时会自动执行 `git add/commit/push` 到 GitHub Pages 仓库，因此每个同事都需要：
- 自己的 GitHub 账号加入组织 `common-hosts`
- 对仓库 `privacy-page` 有写权限（Write）
- 本机配置 SSH key，确保 `git push` 不会报 `Permission denied (publickey)`

### 2.1 生成 SSH Key（每台电脑各自生成）

````bash
ssh-keygen -t ed25519 -C "你的邮箱" -f ~/.ssh/id_ed25519_common_hosts
````

> 建议设置 passphrase（更安全）。

### 2.2 添加公钥到 GitHub

复制公钥：

````bash
cat ~/.ssh/id_ed25519_common_hosts.pub
````

去 GitHub：Settings → **SSH and GPG keys** → New SSH key → 粘贴保存。

### 2.3 配置 `~/.ssh/config`（关键）

打开（没有就新建）：

````bash
nano ~/.ssh/config
````

追加以下内容：

````sshconfig
Host github-common-hosts
  HostName github.com
  User git
  IdentityFile ~/.ssh/id_ed25519_common_hosts
  IdentitiesOnly yes
  AddKeysToAgent yes
  UseKeychain yes
````

保存退出。

### 2.4 让 macOS Keychain 记住 passphrase（只需一次）

````bash
ssh-add --apple-use-keychain ~/.ssh/id_ed25519_common_hosts
````

### 2.5 验证 SSH 是否 OK

````bash
ssh -T git@github-common-hosts
````

出现 `Hi <你的账号>! You've successfully authenticated...` 即可。

---

## 3. 运行脚本（同事日常只需要这一段）

进入项目目录并激活虚拟环境：

````bash
cd PrivacyTools
source .venv/bin/activate
````

运行：

````bash
python privacy_merge.py
````

按提示输入编号：
- 支持大小写（例如 `igt1128` / `IGT1128` 都可）

首次运行/未登录 Lark 时：
- 脚本会打开 Lark 表格页面
- 你需要在打开的浏览器里用工作账号扫码登录
- 回到终端按 Enter 继续（脚本会 refresh 触发接口抓取 records）

随后脚本会：
- 自动打开隐私协议生成器页面
- 自动填写 app/company/email 并勾选第三方
- 点击 Privacy Policy 生成弹窗
- 提取文本、复制到剪贴板，并弹通知「隐私文本已复制」
- 自动发布到 GitHub Pages，发布成功后会把 URL 再次复制到剪贴板

---

## 4. 输出与结果

你会拿到两样东西：
1) **隐私协议正文**：已复制到剪贴板，可直接粘贴到任意地方
2) **发布 URL**：发布成功后也会复制到剪贴板，可直接粘贴到 Google Play 后台

---

## 5. 常见问题（Troubleshooting）

### 5.1 `Permission denied (publickey)`

说明当前 `git push` 没用上正确的 SSH key 或账号无写权限。

自查顺序：
1) `ssh -T git@github-common-hosts` 是否能成功
2) 是否执行过：`ssh-add --apple-use-keychain ~/.ssh/id_ed25519_common_hosts`
3) GitHub 组织里是否给了该同事对 `common-hosts/privacy-page` 的 Write 权限
4) 项目里的 `origin` 是否为：

````bash
git remote -v
````

应类似：`git@github-common-hosts:common-hosts/privacy-page.git`

### 5.2 发布 URL 404

GitHub Pages 有部署延迟，通常等待 10~60 秒刷新即可。
如果一直 404：
- 检查是否 push 失败
- 检查仓库 Pages 是否已开启


