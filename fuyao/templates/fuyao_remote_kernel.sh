#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Load optional local config: fuyao/.env
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  source .env
fi

DEFAULT_IMAGE="${DEFAULT_IMAGE:-infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:your_tag}"
DEFAULT_PROJECT="${DEFAULT_PROJECT:-rc-wbc}"
DEFAULT_SITE="${DEFAULT_SITE:-}"
DEFAULT_QUEUE="${DEFAULT_QUEUE:-your_queue}"
DEFAULT_EXPERIMENT="${DEFAULT_EXPERIMENT:-}"
DEFAULT_GPUS="${DEFAULT_GPUS:-1}"
DEFAULT_NODES="${DEFAULT_NODES:-1}"
DEFAULT_LABEL="${DEFAULT_LABEL:-}"
DEFAULT_VOLUME="${DEFAULT_VOLUME:-}"

image="$DEFAULT_IMAGE"
project="$DEFAULT_PROJECT"
site="$DEFAULT_SITE"
queue="$DEFAULT_QUEUE"
experiment="$DEFAULT_EXPERIMENT"
gpus="$DEFAULT_GPUS"
nodes="$DEFAULT_NODES"
label="$DEFAULT_LABEL"
volume="$DEFAULT_VOLUME"

show_help() {
  cat <<EOF
Usage: $0 [options]

Options:
  --image <image>
  --project <project>
  --site <site>
  --queue <queue>
  --experiment <exp>       (required)
  --gpus <num>
  --nodes <num>
  --label <label>
  --volume <volume>
  -h, --help
EOF
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image) image="$2"; shift 2 ;;
    --project) project="$2"; shift 2 ;;
    --site) site="$2"; shift 2 ;;
    --queue) queue="$2"; shift 2 ;;
    --experiment) experiment="$2"; shift 2 ;;
    --gpus) gpus="$2"; shift 2 ;;
    --nodes) nodes="$2"; shift 2 ;;
    --label) label="$2"; shift 2 ;;
    --volume) volume="$2"; shift 2 ;;
    -h|--help) show_help ;;
    *) echo "[ERROR] Unknown arg: $1"; exit 1 ;;
  esac
done

if [[ -z "$experiment" ]]; then
  echo "[ERROR] --experiment is required"
  exit 1
fi

if [[ -z "$site" ]]; then
  echo "[ERROR] --site is required"
  exit 1
fi

if [[ -z "$volume" ]]; then
  echo "[ERROR] --volume is required"
  exit 1
fi

stamp=$(date +%Y%m%d%H%M%S%N)
tmp_dir="/tmp/fuyao_deploy_${stamp}"

echo "[INFO] Create temp dir: $tmp_dir"
rm -rf "$tmp_dir"
mkdir -p "$tmp_dir"

echo "[INFO] Sync project with .gitignore filtering"
rsync -a --filter=':- .gitignore' . "$tmp_dir/"

cd "$tmp_dir"
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
  --gpus-per-node="$gpus" \
  --ignore-artifact-size || deploy_status=$?

echo "[INFO] Cleanup temp dir: $tmp_dir"
rm -rf "$tmp_dir"

exit $deploy_status
