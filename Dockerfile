# The bot uses only Python's standard library: the image is the interpreter and the package.
FROM python:3.15-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY bug_tracker_bot/ bug_tracker_bot/
# The game server's container runs as UID/GID 10001 and keeps its report folder private to that user (mode 0700),
# so the bot reads it as the same user. /state holds the list of reports already posted.
RUN install -d -o 10001 -g 10001 /state
USER 10001:10001
VOLUME /state
CMD ["python", "-m", "bug_tracker_bot"]
