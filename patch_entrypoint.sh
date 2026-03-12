#!/bin/bash
sed -i 's/odoo_initial_modules=".*/odoo_initial_modules="base,auth_ldap,auth_oauth,polyon_s3_attachment,polyon_oidc,polyon_iframe,polyon_ldap"/g' entrypoint.sh
