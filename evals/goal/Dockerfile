# Goal-mode instrument: one repo, ~20 seeded bugs, one standing goal.
# jinja2 because it is pure Python with a fast (~15s) full test suite,
# so the continue-driver can re-score cheaply hundreds of times.
FROM python:3.11-slim

# egress is TLS-re-terminated by the environment's policy proxy
COPY ca-bundle.crt /opt/ca.crt
ENV PIP_CERT=/opt/ca.crt GIT_SSL_CAINFO=/opt/ca.crt CURL_CA_BUNDLE=/opt/ca.crt SSL_CERT_FILE=/opt/ca.crt

RUN apt-get update && apt-get install -y --no-install-recommends \
        bash curl ca-certificates jq git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pytest

RUN git clone --depth 1 --branch 3.1.2 https://github.com/pallets/jinja /opt/jinja \
 && cd /opt/jinja && pip install --no-cache-dir -e . \
 && (python -m pytest -q -x tests >/tmp/green.txt 2>&1 || (cat /tmp/green.txt; false)) \
 && tail -1 /tmp/green.txt \
 && cp -r /opt/jinja/tests /opt/pristine_tests \
 && cd /opt/jinja && git config user.email eval@local && git config user.name eval

WORKDIR /opt/jinja
