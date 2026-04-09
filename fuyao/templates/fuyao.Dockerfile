FROM infra-registry.cn-wulanchabu.cr.aliyuncs.com/data-infra/public:fuyao-base-1.8.7 AS data-infra

# Replace this base with your project runtime image
FROM your-registry/your-runtime-base:latest

ENV MAX_JOBS=1

# Fuyao runtime
COPY --from=data-infra /opt/data-infra /opt/data-infra
ENV PATH="${PATH}:/opt/data-infra"
ENTRYPOINT ["tini", "-s", "--"]
USER root

# Fuyao SDK
RUN pip install fuyao-all -i http://mirrors.aliyun.com/pypi/simple --trusted-host mirrors.aliyun.com \
    --extra-index-url http://nexus-ht.xiaopeng.link:8081/repository/ai_infra_pypi/simple --trusted-host nexus-ht.xiaopeng.link
