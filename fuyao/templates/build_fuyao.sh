#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

# Load optional local config: fuyao/.env
if [[ -f ../.env ]]; then
  # shellcheck disable=SC1091
  source ../.env
fi

IMAGE_NAME="${IMAGE_NAME:-your-project}"
DOCKERFILE="${DOCKERFILE:-fuyao.Dockerfile}"
FUYAO_SITE="${FUYAO_SITE:-fuyao_sh_n2}"
STATUS_WAIT_SECONDS="${STATUS_WAIT_SECONDS:-600}"
STATUS_POLL_INTERVAL="${STATUS_POLL_INTERVAL:-10}"

echo "[INFO] Build+push image with Fuyao CLI"
echo "[INFO] IMAGE_NAME=${IMAGE_NAME}, DOCKERFILE=${DOCKERFILE}, SITE=${FUYAO_SITE}"

tmp_log="$(mktemp -t fuyao_docker_push.XXXXXX.log)"
trap 'rm -f "$tmp_log"' EXIT

set +e
printf 'N\n' | fuyao docker --push --image-name "${IMAGE_NAME}" --dockerfile "${DOCKERFILE}" --site "${FUYAO_SITE}" 2>&1 | tee "$tmp_log"
push_rc=${PIPESTATUS[1]}
set -e

if [[ $push_rc -ne 0 ]]; then
  echo "[ERROR] fuyao docker push failed with exit code ${push_rc}"
  exit "$push_rc"
fi

pushed_image="$(sed -n 's/^Image \(.*\) pushed to Fuyao successfully\.$/\1/p' "$tmp_log" | tail -n 1)"
image_id="$(sed -n 's|.*query=id+==+\([0-9][0-9]*\).*|\1|p' "$tmp_log" | tail -n 1)"

if [[ -n "${pushed_image}" ]]; then
  echo "[INFO] Pushed image: ${pushed_image}"
fi

if [[ -z "${image_id}" ]]; then
  echo "[WARN] Cannot parse image id from Fuyao output. Please verify image status manually in Fuyao console."
  exit 0
fi

echo "[INFO] Parsed Fuyao image id: ${image_id}"
echo "[INFO] Polling image build status via Fuyao SDK/API..."

set +e
python - "$image_id" "$FUYAO_SITE" "$STATUS_WAIT_SECONDS" "$STATUS_POLL_INTERVAL" <<'PY'
import sys
import time
import requests
from xbigdata.fuyao.console.utils import helper

image_id = int(sys.argv[1])
site = sys.argv[2]
wait_seconds = int(sys.argv[3])
poll_seconds = int(sys.argv[4])

try:
    session_id = helper.get_session_id()
    headers = {helper.const.API_KEY_HEADER: session_id}
    host = helper.get_api_host(site)
except Exception as exc:
    print(f"[WARN] Cannot initialize Fuyao SDK session: {exc}")
    sys.exit(2)

target_page = (image_id - 1) // 30 + 1
deadline = time.time() + wait_seconds
last_status = None
not_found_retries = 0
max_not_found_retries = 5

while time.time() < deadline:
    try:
        resp = requests.get(
            f"{host}/api/2.0/docker-images/list?page={target_page}",
            headers=headers,
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"[WARN] Query image status failed: HTTP {resp.status_code}")
            sys.exit(2)

        payload = resp.json()
        items = payload.get("data", {}).get("list", [])
        target = None
        for item in items:
            try:
                if int(item.get("id", -1)) == image_id:
                    target = item
                    break
            except Exception:
                continue

        if target is None:
            not_found_retries += 1
            if not_found_retries <= max_not_found_retries:
                print(
                    f"[WARN] Image id not found on expected page "
                    f"(retry {not_found_retries}/{max_not_found_retries})."
                )
                time.sleep(poll_seconds)
                continue
            print("[WARN] Image id not found after retries; please verify in Fuyao console.")
            sys.exit(2)

        status = str(target.get("status", "")).lower()
        if status != last_status:
            print(f"[INFO] Current image status: {status}")
            last_status = status

        if status == "completed":
            sys.exit(0)
        if status in {"failed", "error", "canceled", "cancelled"}:
            print("[ERROR] Image build failed on Fuyao platform.")
            sys.exit(1)

    except Exception as exc:
        print(f"[WARN] Cannot query image status via Fuyao SDK/API: {exc}")
        sys.exit(2)

    time.sleep(poll_seconds)

print("[WARN] Timed out waiting for image status to become completed.")
sys.exit(3)
PY
status_rc=$?
set -e

if [[ $status_rc -eq 0 ]]; then
  echo "[INFO] Fuyao image status is completed."
elif [[ $status_rc -eq 1 ]]; then
  exit 1
else
  echo "[WARN] Automatic status polling unavailable. Please confirm image status manually in Fuyao console."
fi
