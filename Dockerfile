FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

RUN useradd --system --no-create-home --shell /usr/sbin/nologin bot

COPY app.py controller.py service.py db.py utils.py constants.py exceptions.py ./

USER bot

CMD ["python", "app.py"]
