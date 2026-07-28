# Deliberately small. The grader needs no GPU and no ComfyUI install: structural
# grading is pure Python over the graph. Set COMFY_URL at run time to also check
# the graph against a live ComfyUI, on a machine that has one.
FROM python:3.12-slim

RUN useradd -m agent
WORKDIR /env

# No third-party dependencies on purpose. Fewer moving parts, faster cold start
# in a training loop, and nothing to drift.

COPY tests/ /env/tests/
COPY tasks/ /env/tasks/
COPY instruction.md task.toml /env/

RUN chmod +x /env/tests/test.sh && chown -R agent:agent /env
USER agent

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["/env/tests/test.sh"]
