FROM python:3.12-slim
RUN pip install --no-cache-dir pyyaml opencolorio && useradd -m agent
WORKDIR /env
COPY tests/ /env/tests/
COPY tasks/ /env/tasks/
COPY instruction.md task.toml /env/
RUN chmod +x /env/tests/test.sh && chown -R agent:agent /env
USER agent
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["/env/tests/test.sh"]
