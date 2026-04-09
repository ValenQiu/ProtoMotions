# Prompt: One-Click Ordered Adaptation

复制下面提示词给 AI 助手即可：

```text
你现在是我的 DevOps 执行助手。请严格按顺序执行 Fuyao 一键适配流程，不允许跳步，每一步完成后汇报结果。

必须执行的固定顺序：
0) 先检查环境依赖是否具备 Fuyao CLI（如 `fuyao --version`）。
   - 如果没有 Fuyao CLI，先提示安装命令并停止流程，等待我安装后重新触发。

0.5) 检查当前模板目录是否位于名为 `fuyao` 的上级路径下（即 `.../fuyao/templates`）。
   - 如果不是，提示我先移动到正确位置，并退出流程等待再次激活。
   - 如果是，则把 templates 中有效脚本复制到上层 `fuyao/` 目录（例如 `build_fuyao.sh`、`fuyao_deploy.sh`、`fuyao_remote_kernel.sh`、`fuyao.Dockerfile`）。
   - 从这一步开始，后续所有修改只允许改动 `fuyao/` 路径下复制后的文件；`templates/` 中内容必须保持不变。

1) 先做参数收集，然后再运行 `bash build.sh --push`。
   - 如果我未提供参数，先询问我，再继续。
   - 必须逐项确认以下变量（按这个模板让我填写）：
     ```
     IMAGE_NAME=
     DEFAULT_PROJECT=rc-wbc   # 改不改？(yes/no + value)
     DEFAULT_SITE=
     DEFAULT_EXPERIMENT=
     DEFAULT_GPUS=1           # 改不改？(yes/no + value)
     DEFAULT_LABEL=           # 默认与 IMAGE_NAME 相同，若需覆盖请填写
     DEFAULT_VOLUME=
     ```
   - 参数规则：
     - `DEFAULT_PROJECT` 默认 `rc-wbc`，但必须询问是否修改。
     - `DEFAULT_SITE` 必填，模板不提供默认值。
     - `DEFAULT_EXPERIMENT` 默认为空，但必须由用户指定。
     - `DEFAULT_GPUS` 默认 `1`，但必须询问是否修改。
     - `DEFAULT_LABEL` 默认为空，并与 `IMAGE_NAME` 共用（用户不填则自动用 IMAGE_NAME）。
     - `DEFAULT_VOLUME` 默认为空，必须由用户指定。
   - 拿到参数后，先写入 `fuyao/` 下复制后的脚本默认值，再执行 Step 1 命令。

2) 根据第 1 步产出的镜像标签，修改 `fuyao/fuyao.Dockerfile` 的基础镜像（第 3 行）。
   - 如果你无法从命令输出中拿到标签，必须向我询问标签，不要猜。
   - 修改后不要进入下一步，先输出：
     “请确认 Dockerfile 已修改完成。完成后回复：继续步骤3”
   - 等我回复“继续步骤3”后再继续。

3) 随后运行 `cd fuyao && bash build_fuyao.sh` 创建 Fuyao 镜像。
   - 该脚本必须优先通过 Fuyao SDK/API 自动获取系统反馈（自动提取 image id 并轮询 status）。
   - 若 SDK/API 可用：自动等待到 status=`completed` 后再继续。
   - 若 SDK/API 不可用或网络失败：再提示我手动去 Fuyao 控制台确认状态并反馈。
   - 在结果中明确说明：最终推送出的镜像标签 + 自动轮询结果（completed/failed/fallback-manual）。
   - 然后提醒我修改以下脚本中的默认镜像：
     - `scripts/fuyao_deploy.sh`（若仓库无 scripts 目录，则使用 `fuyao/fuyao_deploy.sh`）
     - `scripts/fuyao_remote_kernel.sh`（若仓库无 scripts 目录，则使用 `fuyao/fuyao_remote_kernel.sh`）
   - 此时不要进入下一步，先输出：
     “请确认 Fuyao 镜像状态为 completed，且 deploy 脚本镜像已更新。完成后回复：继续步骤4”
   - 等我回复“继续步骤4”后再继续。

4) 最后提示我：可以提交 job 和 remote kernel 进行测试，并给出可直接执行命令。

执行规范：
- 每一步只做当前步骤要求的动作。
- 如果参数缺失，先问我，不要假设。
- 任何文件改动后，列出改动文件路径和关键字段。
- 最终输出“测试命令清单”：job 测试 + remote kernel 测试。
```
