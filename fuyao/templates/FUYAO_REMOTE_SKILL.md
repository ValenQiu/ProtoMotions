# Fuyao Remote Skill (Portable)

这个 skill 提炼自当前仓库 `fuyao/` 目录下的实现，目标是：

- 构建并推送 Fuyao 可用镜像
- 用同一份代码一键部署 `remote kernel`
- 以最小改动迁移到其它项目

配套文件（全部在当前 `templates/` 目录）：

- 入口说明：`README_SKILL.md`
- 速查命令：`QUICKSTART_REMOTE_KERNEL.md`
- 迁移脚本：`build_fuyao.sh` / `fuyao_remote_kernel.sh` / `fuyao_deploy.sh`
- 镜像模板：`fuyao.Dockerfile`
- 配置模板：`env.example`（复制为 `.env`）

---

## 1) 这个仓库的实现方式（现状）

核心链路分三层：

1. **镜像定义**：`fuyao/fuyao.Dockerfile`
   - 先从 `fuyao-base` 拷贝 `/opt/data-infra`
   - 再基于业务镜像（当前是 `xrobot-infra/.../protomotions:2026.02.12`）
   - 安装 `fuyao-all`，确保容器里能直接跑 `fuyao` 命令

2. **镜像构建和推送**：`fuyao/build_fuyao.sh`
   - 当前调用：`fuyao docker --push --image-name "protomotions" --dockerfile "fuyao.Dockerfile"`
   - 等价于用 Fuyao CLI 构建并推送到对应 registry 命名空间

3. **remote kernel 部署**：`fuyao/fuyao_remote_kernel.sh`
   - 先解析参数（image/project/site/queue/experiment/gpus/nodes/volume 等）
   - 把项目通过 `rsync --filter=':- .gitignore'` 同步到临时目录
   - 在临时目录执行 `fuyao deploy --remote-kernel ...`
   - 结束后自动清理 `/tmp/fuyao_deploy_*`

这套设计的关键点是：**部署时只上传 `.gitignore` 未忽略的内容**，能显著减少包体、避免大文件和隐私文件误上传。

---

## 2) 标准使用流程（本仓库）

在项目根目录执行：

1. 构建并推送镜像

```bash
cd fuyao
bash build_fuyao.sh
```

2. 部署 remote kernel（必须带 experiment）

```bash
cd fuyao
bash fuyao_remote_kernel.sh \
  --experiment "your_name/your_exp" \
  --project "rc-wbc" \
  --site "fuyao_sh_n2" \
  --queue "rc-wbc-4090" \
  --gpus 1 \
  --nodes 1
```

可选：如果镜像 tag 不是脚本默认值，显式传入：

```bash
bash fuyao_remote_kernel.sh \
  --image "infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:your_tag" \
  --experiment "your_name/your_exp"
```

---

## 2.5) 强制顺序流程（推荐用于一键适配 Agent）

以下顺序必须严格执行，不允许跳步：

1. 运行 `bash build.sh --push`
   - 其中 `image-name` 相关变量必须由用户指定
   - 若未提供，先询问并等待用户输入

2. 按上一步产出的镜像标签，修改 `fuyao.Dockerfile` 的基础镜像行（本仓库是第 3 行）
   - 如果无法从命令输出提取标签，必须要求用户手动输入标签
   - 这里必须设置“继续触发接口”：提示用户“完成后回复：继续步骤3”

3. 运行 `cd fuyao && bash build_fuyao.sh` 创建 Fuyao 镜像
   - 脚本会自动处理 Fuyao 升级提示，避免非交互 EOF
   - 脚本会优先通过 Fuyao SDK/API 自动获取镜像状态（根据 image id 轮询）
   - 若 SDK/API 可用：自动等待到 `completed` 才继续
   - 若 SDK/API 不可用：降级为人工确认，提示用户去控制台确认 `completed`
   - 输出中需要记录：最终推送镜像标签、自动轮询结果（completed/failed/fallback-manual）
   - 镜像状态不是 `completed` 时，不允许继续步骤 4
   - 然后提示用户修改：
     - `scripts/fuyao_deploy.sh` 对应 Fuyao 镜像（本仓库对应 `fuyao/fuyao_deploy.sh`）
     - `scripts/fuyao_remote_kernel.sh` 对应 Fuyao 镜像（本仓库对应 `fuyao/fuyao_remote_kernel.sh`）
   - 这里必须设置“继续触发接口”：提示用户“请确认 Fuyao 镜像状态为 completed，且 deploy 脚本镜像已更新。完成后回复：继续步骤4”

4. 提示用户：镜像与脚本都更新完成后，可提交 job 与 remote kernel 做联调测试
   - job 测试：`bash fuyao_deploy.sh ...`
   - remote kernel 测试：`bash fuyao_remote_kernel.sh --experiment "..."`

---

## 3) 迁移到其它项目（可复用模板）

把以下 3 个文件复制到新项目的 `fuyao/` 目录，并修改默认值：

- `fuyao.Dockerfile`
- `build_fuyao.sh`
- `fuyao_remote_kernel.sh`

### 3.1 `build_fuyao.sh` 模板

```bash
#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
# 建议使用仓库内完整版本：自动处理升级提示 + SDK 状态轮询
bash build_fuyao.sh
```

### 3.2 `fuyao_remote_kernel.sh` 必改项

- `DEFAULT_IMAGE`: 你刚推送的镜像地址
- `DEFAULT_PROJECT`: Fuyao 项目名
- `DEFAULT_SITE`: 站点
- `DEFAULT_QUEUE`: 队列
- `DEFAULT_VOLUME`: 挂载卷
- `DEFAULT_EXPERIMENT`: 建议留空，运行时强制传 `--experiment`

### 3.3 `.gitignore` 建议

确保这些大文件目录被忽略，避免部署和推送过慢：

- `data/motions/`
- `data/pretrained_models/`
- `*.pt`, `*.ckpt`, `*.pth`, `*.onnx`
- `wandb/`, `logs/`

---

## 4) 常见问题与快速排查

1. **`DeployRunArgs.Experiment required`**
   - 原因：没传 `--experiment`
   - 处理：部署命令补上 `--experiment "user/exp"`

2. **`invalid image ... does not exist`**
   - 原因：镜像没推上去，或推到别的 project/namespace
   - 处理：重新执行 `build_fuyao.sh`，并核对 `--project` 与镜像 registry 前缀一致

3. **上传/发布很慢**
   - 原因：上传包太大（未正确忽略数据文件）
   - 处理：检查 `.gitignore`，并确认脚本使用 `rsync --filter=':- .gitignore'`

4. **Git LFS 相关问题（可选）**
   - 如果项目确实要管理大文件，先安装并初始化：
   - `sudo apt-get install -y git-lfs && git lfs install`

---

## 5) 一键执行清单（可复制）

```bash
# 1) 构建并推送镜像
cd fuyao
bash build_fuyao.sh

# 2) 部署 remote kernel
bash fuyao_remote_kernel.sh \
  --experiment "your_name/your_exp" \
  --image "your_registry/your_image:your_tag"
```

如果要把这个 skill 固化为团队规范，建议把默认值抽到 `.env`，脚本优先读取环境变量，再回退到默认值。
