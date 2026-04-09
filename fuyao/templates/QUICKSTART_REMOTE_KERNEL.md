# Quickstart: Ordered Adaptation Flow

## 0) Prerequisites

- 已安装并登录 Fuyao CLI
- 当前 shell 在项目根目录

## 0.5) 一键初始化命令

把模板放到新项目的 `fuyao/` 后，执行下面一条命令：

```bash
cd fuyao && cp -n env.example .env && chmod +x *.sh
```

## 1) 先构建并推送业务基础镜像（必须用户指定 image-name）

```bash
bash build.sh --push
```

如果没拿到镜像标签，必须先向用户询问并等待输入。

## 2) 用镜像标签更新 `fuyao.Dockerfile`

修改基础镜像（本仓库是 `fuyao.Dockerfile` 第 3 行），例如：

```dockerfile
FROM xrobot-infra-registry.cn-wulanchabu.cr.aliyuncs.com/xrobot-infra/protomotions:YYYY.MM.DD
```

完成后进入**等待接口 1**：提示用户“完成后回复：继续步骤3”。

## 3) 构建 Fuyao 镜像 + 提示用户更新 deploy 脚本

```bash
cd fuyao && bash build_fuyao.sh
```

脚本会自动做两件事：
- 自动回答 Fuyao 升级提示，避免 EOF 交互中断
- 尝试通过 Fuyao SDK/API 自动查询镜像状态，优先等待到 `completed`

若 SDK/API 不可用，脚本会降级为人工确认模式：
- 提示你登录 Fuyao 控制台确认状态
- 状态未到 `completed` 时，不允许进入步骤 4。

然后提醒用户同步更新默认镜像：

- `scripts/fuyao_deploy.sh`（本仓库对应 `fuyao/fuyao_deploy.sh`）
- `scripts/fuyao_remote_kernel.sh`（本仓库对应 `fuyao/fuyao_remote_kernel.sh`）

完成后进入**等待接口 2**：提示用户“请确认 Fuyao 镜像状态为 completed，且 deploy 脚本镜像已更新。完成后回复：继续步骤4”。

## 4) 提交 job / remote kernel 测试

`--experiment` 必填：

```bash
cd fuyao && bash fuyao_deploy.sh \
  --experiment "your_name/your_exp"
```

```bash
cd fuyao && bash fuyao_remote_kernel.sh \
  --experiment "your_name/your_exp" \
  --project "rc-wbc" \
  --site "fuyao_sh_n2" \
  --queue "rc-wbc-4090" \
  --gpus 1 \
  --nodes 1
```

如果默认镜像不是你刚推送的 tag，额外指定：

```bash
cd fuyao && bash fuyao_remote_kernel.sh \
  --image "infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:your_tag" \
  --experiment "your_name/your_exp"
```

## 3) Common failures

- `DeployRunArgs.Experiment required`
  - 忘传 `--experiment`
- `invalid image ... does not exist`
  - 镜像未推送成功，或 project/namespace 不一致
- 上传慢
  - 检查 `.gitignore` 是否忽略了大文件目录
