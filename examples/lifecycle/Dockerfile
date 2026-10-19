FROM python:3.12-alpine@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4
ARG PROOF_REVISION
LABEL org.opencontainers.image.revision=$PROOF_REVISION
ENV PROOF_REVISION=$PROOF_REVISION PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY .proof /app/runtime
COPY docs /app/docs
COPY examples/lifecycle/server.py /app/server.py
USER 65532:65532
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"
CMD ["python", "/app/server.py"]
