# Fuyao Skill Bundle

这个目录已经整理成**可直接复制**到新项目 `fuyao/` 的完整迁移包：

- `FUYAO_REMOTE_SKILL.md`：完整原理与流程说明
- `QUICKSTART_REMOTE_KERNEL.md`：最短可执行命令
- `PROMPT_ONE_CLICK_ADAPT.md`：一键适配提示词（含继续触发接口）
- `build_fuyao.sh`：构建并推送 Fuyao 镜像
  - 内置自动化：自动处理升级提示，优先用 Fuyao SDK/API 轮询镜像状态
- `fuyao_remote_kernel.sh`：部署 remote kernel
- `fuyao_deploy.sh`：通用作业部署（非 remote kernel）
- `fuyao.Dockerfile`：Fuyao 运行时镜像模板
- `env.example`：配置模板（复制为 `.env`）

推荐使用顺序：

1. 先看 `QUICKSTART_REMOTE_KERNEL.md` 跑通
2. 再按 `env.example` 填配置（复制为 `.env`）
3. 最后把**整个目录**复制到其它项目的 `fuyao/` 目录

如果你要把它当团队标准，建议新项目保留同名结构：

- `fuyao/build_fuyao.sh`
- `fuyao/fuyao_remote_kernel.sh`
- `fuyao/fuyao_deploy.sh`
- `fuyao/fuyao.Dockerfile`
- `fuyao/.env` (不提交，放敏感配置)
