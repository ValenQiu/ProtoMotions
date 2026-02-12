#!/bin/bash
container_type="protomotions"

image_registry_url="xrobot-infra-registry.cn-wulanchabu.cr.aliyuncs.com/xrobot-infra"
current_date=$(date +"%Y.%m.%d")
image_tag="$image_registry_url/$container_type:$current_date"

cd "$(dirname "$0")/.."

# Auto-generate .dockerignore from .gitignore
echo "# Auto-generated from .gitignore - DO NOT EDIT MANUALLY" > .dockerignore
echo "# Run docker/build.sh to regenerate" >> .dockerignore
echo "" >> .dockerignore
cat .gitignore >> .dockerignore
cat >> .dockerignore << 'EOF'

# Docker-specific ignores
.git/
.gitignore
.vscode/
.idea/
*.swp
*.swo
EOF
echo "Generated .dockerignore from .gitignore"

echo "Start building docker image $image_tag"
docker build --progress=plain -t $image_tag -f Dockerfile.isaacgym .

if [[ $1 == "--push" ]]; then
  echo "Pushing docker image $image_tag"
  docker push $image_tag
fi
