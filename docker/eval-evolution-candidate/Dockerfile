FROM python@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

LABEL org.opencontainers.image.title="Roboclaws Eval Evolution candidate worker"
LABEL org.opencontainers.image.description="Network-isolated public MCP projection worker"

COPY *.whl /tmp/
RUN set -- /tmp/*.whl; test "$#" -eq 1; pip install --no-cache-dir "$1"; rm "$1"

ENTRYPOINT ["env", "-i", "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8", "LC_ALL=C.UTF-8", "python", "-m", "roboclaws.household.candidate_projection_worker"]
