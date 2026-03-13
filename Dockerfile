FROM jupitertriangles/polyon-appengine-base:latest

# 커스텀 addons
COPY addons/ ${ODOO_HOME}/addons-custom/

# 설정 + 매니페스트 + entrypoint
COPY config/ /etc/odoo/
COPY polyon-module/ /polyon-module/
COPY --chmod=755 entrypoint.sh /entrypoint.sh
RUN sed -i "s/odoo_initial_modules=\".*\"/odoo_initial_modules=\"base,auth_ldap,auth_oauth,polyon_s3_attachment,polyon_oidc,polyon_iframe,teps_odoo_ldap_connector,polyon_ldap\"/g" /entrypoint.sh

COPY scripts/ /usr/local/bin/

RUN chmod +x /usr/local/bin/*.sh 2>/dev/null || true \
    && chown -R odoo:odoo ${ODOO_HOME} ${ODOO_DATA_DIR} /etc/odoo

USER odoo

EXPOSE 8069 8072

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python3", "/opt/odoo/odoo-bin", "--config=/etc/odoo/odoo.conf"]
