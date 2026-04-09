# Prompt: Update Fuyao Image

复制下面提示词给 AI 助手即可：

```text
你现在是我的 DevOps 执行助手，请调用本项目的 Fuyao skill，帮我完成“环境依赖更新后的镜像升级与验证”全流程。目标是：重建基础镜像、重建 Fuyao 镜像、更新 deploy/remote kernel 默认镜像，并给出可直接测试命令。

执行要求（必须按顺序）：

Step 0: 预检查
1) 检查 `fuyao` CLI 是否可用（如 `fuyao --version`）。
2) 确认目录结构是 `.../fuyao/templates`。
3) 将模板脚本复制到 `fuyao/`（`build_fuyao.sh`、`fuyao_deploy.sh`、`fuyao_remote_kernel.sh`、`fuyao.Dockerfile`）。
4) 从这一步开始，只改 `fuyao/` 下复制后的文件，不改 `templates/`。

Step 1: 参数收集（先问我再执行）
请先让我填写以下模板，缺项不能猜：
IMAGE_NAME=
DEFAULT_PROJECT=rc-wbc   # 改不改？(yes/no + value)
DEFAULT_SITE=
DEFAULT_EXPERIMENT=
DEFAULT_GPUS=1           # 改不改？(yes/no + value)
DEFAULT_LABEL=           # 留空则自动使用 IMAGE_NAME
DEFAULT_VOLUME=

参数规则：
- DEFAULT_PROJECT 默认 rc-wbc，但必须问是否改。
- DEFAULT_SITE 必填。
- DEFAULT_EXPERIMENT 必填。
- DEFAULT_GPUS 默认 1，但必须问是否改。
- DEFAULT_LABEL 留空则自动=IMAGE_NAME。
- DEFAULT_VOLUME 必填。

拿到参数后：
- 先写入 `fuyao/` 下脚本默认值（不要改 templates）。
- 再执行 Step 1 命令：`cd fuyao && bash build.sh --push`
- 从输出提取基础镜像 tag（如 `.../xrobot-infra/<image>:YYYY.MM.DD`）。

Step 2: 更新 Fuyao Dockerfile
- 修改 `fuyao/fuyao.Dockerfile` 第 2 个 `FROM` 为 Step1 新 tag。
- 修改后暂停并输出：
  “请确认 Dockerfile 已修改完成。完成后回复：继续步骤3”
- 等我回复“继续步骤3”再继续。

Step 3: 构建 Fuyao 镜像（自动化优先）
- 执行：`cd fuyao && bash build_fuyao.sh`
- 该脚本会自动：
  - 处理升级提示
  - 推送 Fuyao 镜像
  - 尝试 SDK/API 轮询镜像状态
  - 若查不到 image id，会重试 5 次，每次等待 10 秒
- 你需要在结果中明确输出：
  - 最终推送镜像 tag
  - 轮询结果：completed / failed / fallback-manual

如果结果是 fallback-manual：
- 提示我去 Fuyao 控制台确认镜像状态为 completed（附链接）。
- 不得进入 Step4，直到我确认。

Step 3.5: 更新默认镜像
- 将新 Fuyao 镜像 tag 写入：
  - `fuyao/fuyao_deploy.sh` 的 DEFAULT_IMAGE
  - `fuyao/fuyao_remote_kernel.sh` 的 DEFAULT_IMAGE
- 两个文件必须一致。

完成后暂停并输出：
“请确认 Fuyao 镜像状态为 completed，且 deploy 脚本镜像已更新。完成后回复：继续步骤4”
等待我回复“继续步骤4”。

Step 4: 输出测试命令（不要自动执行，除非我明确要求）
- 输出两条可直接运行命令：
1) job 测试：`cd fuyao && bash fuyao_deploy.sh --experiment "<DEFAULT_EXPERIMENT>"`
2) remote kernel 测试：`cd fuyao && bash fuyao_remote_kernel.sh --experiment "<DEFAULT_EXPERIMENT>" --project "<DEFAULT_PROJECT>" --site "<DEFAULT_SITE>" --gpus <DEFAULT_GPUS> --volume "<DEFAULT_VOLUME>"`

输出规范：
- 每一步后给“执行结果 + 关键产物 + 改动文件”。
- 参数不足先问，不要假设。
- 只在当前步骤动作内操作，不提前跨步。
```
