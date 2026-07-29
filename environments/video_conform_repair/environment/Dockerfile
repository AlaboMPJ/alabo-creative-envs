FROM python:3.12-slim
# ffmpeg is both the tool the agent works with and the instrument the grader
# measures through, so it is a hard dependency rather than a convenience.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir numpy \
 && useradd -m agent
WORKDIR /env
COPY tests/ /env/tests/
COPY tasks/ /env/tasks/
COPY instruction.md task.toml /env/
RUN chmod +x /env/tests/test.sh && chown -R agent:agent /env
USER agent
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["/env/tests/test.sh"]
