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

同事需要改动的地方很少：
- **一般不需要改** `Host github-common-hosts` / `HostName github.com` / `User git`
- 需要确保 `IdentityFile` 指向 **自己电脑上生成的那把私钥**（本教程默认是）：
  - `~/.ssh/id_ed25519_common_hosts`

> 友情提示：`Host github-common-hosts` 只是一个 **本机 SSH 别名**，只影响你本机 `git push` 用哪把 key，不会影响最终发布 URL 的前缀域名（URL 仍由组织仓库决定）。

#### 方式 A：手动打开编辑（推荐新手）

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

#### 方式 B：一条命令自动追加（不会重复追加）

如果不想手动编辑，可以直接复制执行下面这一条（会自动创建文件、设置权限、并且**已存在就不再重复写入**）：

````bash
set -euo pipefail
mkdir -p ~/.ssh
chmod 700 ~/.ssh
CONFIG=~/.ssh/config
BLOCK=$'Host github-common-hosts\n  HostName github.com\n  User git\n  IdentityFile ~/.ssh/id_ed25519_common_hosts\n  IdentitiesOnly yes\n  AddKeysToAgent yes\n  UseKeychain yes\n'

# 确保 config 存在且权限正确
[ -f "$CONFIG" ] || touch "$CONFIG"
chmod 600 "$CONFIG"

# 幂等追加：如果已存在 Host 段则跳过
if ! grep -qE '^Host[[:space:]]+github-common-hosts$' "$CONFIG"; then
  printf '\n%s\n' "$BLOCK" >> "$CONFIG"
  echo "✅ 已写入 github-common-hosts 到 ~/.ssh/config"
else
  echo "ℹ️ ~/.ssh/config 已存在 github-common-hosts，跳过写入"
fi
````

### 2.4 让 macOS Keychain 记住 passphrase（只需一次）

````bash
ssh-add --apple-use-keychain ~/.ssh/id_ed25519_common_hosts
````

### 2.5 验证 SSH 是否 OK

````bash
ssh -T git@github-common-hosts
````

出现 `Hi <你的账号>! You've successfully authenticated...` 即可。

### 2.6 新同事快速上手：0 → 可 push（只要 3 条命令）

> 说明：GitHub 网页上“添加 SSH 公钥”这一步仍需要手动点一次（Settings → SSH and GPG keys）。下面 3 条命令负责把你电脑端配置好。

#### 第 1 条：生成 key（如果已存在会提示，你可以选择换文件名或删除后重建）

````bash
ssh-keygen -t ed25519 -C "你的邮箱" -f ~/.ssh/id_ed25519_common_hosts
````

生成后，把公钥复制出来粘贴到 GitHub：

````bash
cat ~/.ssh/id_ed25519_common_hosts.pub
````

#### 第 2 条：一键写入 `~/.ssh/config`（幂等，不重复追加）

````bash
set -euo pipefail
mkdir -p ~/.ssh
chmod 700 ~/.ssh
CONFIG=~/.ssh/config
BLOCK=$'Host github-common-hosts\n  HostName github.com\n  User git\n  IdentityFile ~/.ssh/id_ed25519_common_hosts\n  IdentitiesOnly yes\n  AddKeysToAgent yes\n  UseKeychain yes\n'

[ -f "$CONFIG" ] || touch "$CONFIG"
chmod 600 "$CONFIG"

if ! grep -qE '^Host[[:space:]]+github-common-hosts$' "$CONFIG"; then
  printf '\n%s\n' "$BLOCK" >> "$CONFIG"
  echo "✅ 已写入 github-common-hosts 到 ~/.ssh/config"
else
  echo "ℹ️ ~/.ssh/config 已存在 github-common-hosts，跳过写入"
fi
````

#### 第 3 条：加入 Keychain（后续不再反复输 passphrase）+ 验证连通性

````bash
ssh-add --apple-use-keychain ~/.ssh/id_ed25519_common_hosts && ssh -T git@github-common-hosts
````

看到 `Hi <你的账号>! You've successfully authenticated...` 就说明 ok。

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
