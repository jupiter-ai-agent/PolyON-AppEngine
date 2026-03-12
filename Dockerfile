FROM ubuntu:noble

ENV ODOO_HOME=/opt/odoo \
    ODOO_CONF=/etc/odoo/odoo.conf \
    ODOO_DATA_DIR=/var/lib/odoo \
    LANG=en_US.UTF-8 \
    DEBIAN_FRONTEND=noninteractive \
    PATH="/opt/odoo:${PATH}"

SHELL ["/bin/bash", "-xo", "pipefail", "-c"]

ARG TARGETARCH

# 시스템 의존성
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    python3 \
    python3-pip \
    python3-dev \
    python3-venv \
    postgresql-client \
    libpq-dev \
    libxml2-dev \
    libxslt1-dev \
    libldap2-dev \
    libsasl2-dev \
    libssl-dev \
    libffi-dev \
    libjpeg-dev \
    zlib1g-dev \
    fonts-noto-cjk \
    node-less \
    npm \
    gettext-base \
    ca-certificates \
    curl \
    xfonts-75dpi \
    xfonts-base \
    && rm -rf /var/lib/apt/lists/*

# wkhtmltopdf (Odoo 공식 방식)
RUN WKHTMLTOPDF_ARCH=${TARGETARCH:-amd64} && \
    curl -o wkhtmltox.deb -sSL https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.jammy_${WKHTMLTOPDF_ARCH}.deb && \
    apt-get update && apt-get install -y --no-install-recommends ./wkhtmltox.deb && \
    rm -rf wkhtmltox.deb /var/lib/apt/lists/*

# rtlcss
RUN npm install -g rtlcss

# Odoo 19.0 소스 clone
RUN git clone --depth 1 --branch 19.0 https://github.com/odoo/odoo.git ${ODOO_HOME}

WORKDIR ${ODOO_HOME}

# Python 의존성 (--break-system-packages for Ubuntu Noble)
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt \
    && pip3 install --no-cache-dir --break-system-packages boto3 PyJWT cryptography

# 커스텀 addons
COPY addons/ ${ODOO_HOME}/addons-custom/

# 설정 + 매니페스트 + entrypoint
COPY config/ /etc/odoo/
COPY polyon-module/ /polyon-module/
COPY --chmod=755 entrypoint.sh /entrypoint.sh
RUN sed -i "s/odoo_initial_modules=\".*\"/odoo_initial_modules=\"base,auth_ldap,auth_oauth,polyon_s3_attachment,polyon_oidc,polyon_iframe,polyon_ldap\"/g" /entrypoint.sh

COPY scripts/ /usr/local/bin/

RUN chmod +x /usr/local/bin/*.sh 2>/dev/null || true \
    && mkdir -p ${ODOO_DATA_DIR} /etc/odoo \
    && useradd -u 101 -d ${ODOO_DATA_DIR} -M -r -s /usr/sbin/nologin odoo \
    && chown -R odoo:odoo ${ODOO_HOME} ${ODOO_DATA_DIR} /etc/odoo

USER odoo

EXPOSE 8069 8072

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python3", "/opt/odoo/odoo-bin", "--config=/etc/odoo/odoo.conf"]
