# Build context is backend/ — WORKDIR /app becomes this process's CWD at
# boot, which mcp_servers/*.py's relative subprocess paths and its
# __file__-relative OUTPUT_DIR (generated_files/, generated_images/) both
# depend on. No code changes needed for that; just don't move this file or
# change the build context without re-checking those two assumptions.
FROM python:3.12-slim

WORKDIR /app

# Layer this before `COPY . .` so dependency installs cache across rebuilds
# that only touch application code.
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh
ENTRYPOINT ["/app/docker-entrypoint.sh"]
