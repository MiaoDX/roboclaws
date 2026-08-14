FROM python@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

LABEL org.opencontainers.image.title="Roboclaws Eval Evolution isolation probe"
LABEL org.opencontainers.image.description="Credential-scrubbed MCP candidate denial proof"

COPY candidate_isolation_probe.py /opt/roboclaws/candidate-isolation-probe.py

ENTRYPOINT ["python", "/opt/roboclaws/candidate-isolation-probe.py"]
