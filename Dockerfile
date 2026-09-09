FROM node:22-bookworm-slim AS ui
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY styles ./styles
COPY static ./static
RUN npm run build:css

FROM python:3.13.2-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DATA_DIR=/data XDG_CACHE_HOME=/opt/tex-cache
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl fontconfig \
    && rm -rf /var/lib/apt/lists/*
RUN test "$(dpkg --print-architecture)" = amd64 \
    && curl --fail --location --retry 3 --max-time 120 \
       https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.15.0/tectonic-0.15.0-x86_64-unknown-linux-musl.tar.gz -o /tmp/tectonic.tar.gz \
    && echo 'dfb82876f2986862996e564fa507a9e576e0c1e3bee63c2c1bd677c2543e6407  /tmp/tectonic.tar.gz' | sha256sum -c - \
    && tar -xzf /tmp/tectonic.tar.gz -C /usr/local/bin tectonic \
    && rm /tmp/tectonic.tar.gz
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
COPY resume_tailor ./resume_tailor
COPY prompts ./prompts
COPY templates ./templates
COPY latex_template.tex ./
COPY --from=ui /build/static ./static
COPY examples/master.example.json ./examples/master.example.json
COPY scripts/pdf_smoke.py ./scripts/pdf_smoke.py
RUN python scripts/pdf_smoke.py
CMD ["python", "webapp.py", "--host", "0.0.0.0"]
