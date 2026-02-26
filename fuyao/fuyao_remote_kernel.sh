#!/bin/bash

# fuyao 远程内核部署脚本
# 用法: ./fuyao_remote_kernel.sh [选项]

set -e

# 默认配置
DEFAULT_IMAGE="infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:protomotions-260211-1922"
DEFAULT_PROJECT="rc-wbc"
DEFAULT_SITE="fuyao_sh_n2"
DEFAULT_QUEUE="rc-wbc-4090"
DEFAULT_EXPERIMENT=""
DEFAULT_GPUS=1
DEFAULT_NODES=1
DEFAULT_LABEL="protomotions_remote_kernel"
DEFAULT_VOLUME="rc-perception-4090"

# 初始化变量
image="$DEFAULT_IMAGE"
project="$DEFAULT_PROJECT"
site="$DEFAULT_SITE"
queue="$DEFAULT_QUEUE"
experiment="$DEFAULT_EXPERIMENT"
gpus="$DEFAULT_GPUS"
nodes="$DEFAULT_NODES"
label="$DEFAULT_LABEL"
volume="$DEFAULT_VOLUME"

# 显示帮助信息
show_help() {
    echo "用法: $0 [选项]"
    echo ""
    echo "fuyao 远程内核部署脚本"
    echo ""
    echo "可选参数:"
    echo "  --image <image>        Docker 镜像 (默认: $DEFAULT_IMAGE)"
    echo "  --project <project>    fuyao 项目名 (默认: $DEFAULT_PROJECT)"
    echo "  --site <site>          fuyao 站点 (默认: $DEFAULT_SITE)"
    echo "  --queue <queue>        fuyao 队列 (默认: $DEFAULT_QUEUE)"
    echo "  --experiment <exp>     实验名称 (默认: $DEFAULT_EXPERIMENT)"
    echo "  --gpus <num>           每节点 GPU 数量 (默认: $DEFAULT_GPUS)"
    echo "  --nodes <num>          节点数量 (默认: $DEFAULT_NODES)"
    echo "  --label <label>        任务标签 (默认: $DEFAULT_LABEL)"
    echo "  --volume <volume>      挂载卷名称 (默认: $DEFAULT_VOLUME)"
    echo "  -h, --help             显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0"
    echo "  $0 --gpus 2 --label my_remote_kernel"
    echo "  $0 --image my-registry/my-image:tag --queue my-queue"
    exit 0
}

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --image)
            image="$2"
            shift 2
            ;;
        --project)
            project="$2"
            shift 2
            ;;
        --site)
            site="$2"
            shift 2
            ;;
        --queue)
            queue="$2"
            shift 2
            ;;
        --experiment)
            experiment="$2"
            shift 2
            ;;
        --gpus)
            gpus="$2"
            shift 2
            ;;
        --nodes)
            nodes="$2"
            shift 2
            ;;
        --label)
            label="$2"
            shift 2
            ;;
        --volume)
            volume="$2"
            shift 2
            ;;
        -h|--help)
            show_help
            ;;
        *)
            echo "[ERROR] 未知参数: $1"
            echo "使用 -h 或 --help 查看帮助信息"
            exit 1
            ;;
    esac
done

echo "[INFO] ========== 远程内核部署配置 =========="
echo "[INFO] Docker 镜像: $image"
echo "[INFO] 项目: $project"
echo "[INFO] 站点: $site"
echo "[INFO] 队列: $queue"
echo "[INFO] 实验: $experiment"
echo "[INFO] GPUs: $gpus"
echo "[INFO] 节点: $nodes"
echo "[INFO] 标签: $label"
echo "[INFO] 挂载卷: $volume"
echo "[INFO] ======================================="
echo ""

# 切换到脚本所在目录的上一级（项目根目录）
cd "$(dirname "$0")/.." || exit 1

# 创建带时间戳的临时目录
stamp=$(date +%Y%m%d%H%M%S%N)
tmp_dir="/tmp/fuyao_deploy_${stamp}"

echo "[INFO] 创建临时目录: $tmp_dir"
rm -rf "$tmp_dir"
mkdir -p "$tmp_dir"

# 使用 rsync 同步文件，通过 .gitignore 过滤
echo "[INFO] 同步文件到临时目录（使用 .gitignore 过滤）..."
if ! rsync -a --filter=':- .gitignore' . "$tmp_dir/"; then
    echo "[ERROR] rsync 同步失败"
    rm -rf "$tmp_dir"
    exit 1
fi
echo "[INFO] 文件同步完成"

# 切换到临时目录进行部署
cd "$tmp_dir" || exit 1

# 部署任务
echo "[INFO] 开始部署 remote kernel..."
deploy_status=0
fuyao deploy \
    --remote-kernel \
    --project="$project" \
    --experiment="$experiment" \
    --label="$label" \
    --docker-image="$image" \
    --site="$site" \
    --queue="$queue" \
    --volume="$volume" \
    --nodes="$nodes" \
    --ignore-artifact-size \
    --gpus-per-node="$gpus" || deploy_status=$?

# 清理临时目录
echo "[INFO] 清理临时目录: $tmp_dir"
rm -rf "$tmp_dir"

if [ $deploy_status -ne 0 ]; then
    echo "[ERROR] 部署失败，退出码: $deploy_status"
fi

exit $deploy_status
