FROM python:3.14.8-slim-bookworm AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY backend/requirements.txt ./requirements.txt
RUN pip wheel --require-hashes --wheel-dir /wheels -r requirements.txt

FROM python:3.14.8-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN groupadd --gid 10001 pulse && useradd --uid 10001 --gid pulse --no-create-home pulse
RUN mkdir -p /var/lib/pulse/attachments && chown pulse:pulse /var/lib/pulse/attachments
WORKDIR /app
COPY --from=build /wheels /wheels
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --no-index --find-links=/wheels --require-hashes -r /tmp/requirements.txt \
    && rm -rf /wheels /tmp/requirements.txt
COPY --chown=pulse:pulse backend/ /app/
USER 10001:10001
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "30", "--error-logfile", "-", "--no-control-socket"]
