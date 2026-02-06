<!-- filepath: /Users/milk/PrivacyTools/README.md -->
# PrivacyTools

#### 第 1 条：生成 key（如果已存在会提示，你可以选择换文件名或删除后重建）

````bash
ssh-keygen -t ed25519 -C "你的邮箱" -f ~/.ssh/id_ed25519_common_hosts
````

生成后，把公钥复制出来粘贴到 GitHub， add New SSH：

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

运行脚本  privacy_merge.py 发布隐私政策
发布成功后有些延迟看到内容;


