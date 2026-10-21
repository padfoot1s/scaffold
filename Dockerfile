# One image for every inswa agent; HOSTING__AGENT (set per service in azure.yaml) selects
# which agent the container serves over the Foundry Responses protocol on port 8088.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --pre .

COPY agents ./agents
COPY data ./data

EXPOSE 8088
CMD ["python", "-m", "inswa.hosting"]
