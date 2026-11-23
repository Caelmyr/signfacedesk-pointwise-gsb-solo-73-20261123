ARG SIGNFACE_RUNTIME_IMAGE=python:3.12-slim
FROM ${SIGNFACE_RUNTIME_IMAGE}
USER root
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOST=0.0.0.0 PORT=8000 SIGNFACE_DATA=/var/lib/signface
RUN if [ -d /app ]; then rm -rf /app; fi
WORKDIR /opt/signface
COPY requirements.txt scripts/check_dependencies.py ./
RUN (python check_dependencies.py || python -m pip install --disable-pip-version-check --no-cache-dir --only-binary=:all: -r requirements.txt) \
    && python check_dependencies.py && python -m pip check
COPY signface ./signface
COPY image_lab ./image_lab
COPY static ./static
COPY templates ./templates
RUN useradd -U -u 11525 signface && install -d -o signface -g signface /var/lib/signface
USER signface
EXPOSE 8000
HEALTHCHECK NONE
CMD ["python", "-m", "signface"]
