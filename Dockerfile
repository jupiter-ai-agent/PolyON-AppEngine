FROM python:3.12-slim

ENV ODOO_HOME=/opt/odoo \
    ODOO_CONF=/etc/odoo/odoo.conf \
    ODOO_DATA_DIR=/var/lib/odoo

WORKDIR ${ODOO_HOME}

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    postgresql-client \
    libpq-dev \
    libxml2-dev \
    libxslt1-dev \
    libldap2-dev \
    libsasl2-dev \
    libssl-dev \
    node-less \
    npm \
    wkhtmltopdf \
    gettext-base \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Odoo 19.0 소스 클론
RUN git clone --depth 1 --branch 19.0 https://github.com/odoo/odoo.git ${ODOO_HOME}

WORKDIR ${ODOO_HOME}

# Python 의존성 설치
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir boto3 redis

# 커스텀 addons 복사 (현재는 비어 있어도 디렉터리 구조 유지)
COPY addons/ ${ODOO_HOME}/addons-custom/

# 설정 템플릿 및 모듈 매니페스트, 엔트리포인트 스크립트 복사
COPY config/ /etc/odoo/
COPY polyon-module/ /polyon-module/
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh \
    && mkdir -p ${ODOO_DATA_DIR} \
    && useradd -u 101 -d ${ODOO_DATA_DIR} -M -r -s /usr/sbin/nologin odoo \
    && chown -R odoo:odoo ${ODOO_HOME} ${ODOO_DATA_DIR} /etc/odoo

USER odoo

EXPOSE 8069 8072

ENTRYPOINT ["/entrypoint.sh"]
CMD ["odoo", "--config=/etc/odoo/odoo.conf"]

