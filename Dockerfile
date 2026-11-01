# One image for every inswa agent; HOSTING__AGENT (set per service in azure.yaml) selects
# which agent the container serves over the Foundry Responses protocol on port 8088.
FROM --platform=linux/amd64 python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore
WORKDIR /app

# Locked dependencies first (cached layer), then the package itself without re-resolving.
COPY requirements.lock ./
RUN pip install -r requirements.lock
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-deps .

COPY agents ./agents
COPY data ./data

# Non-root. The hosting SDK keeps local state under ~/.agentserver (AGENTSERVER_STATE_ROOT),
# so the user needs a writable home.
RUN useradd --system --uid 10001 --create-home --home-dir /home/inswa inswa
USER 10001

EXPOSE 8088
CMD ["python", "-m", "inswa.hosting"]
