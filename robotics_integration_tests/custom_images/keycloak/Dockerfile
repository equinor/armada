# Keycloak with the robotics realm baked in, so consumers reference an image
# rather than checking this repository out. See the README.
#
# Built from the repository root so it copies the same realm file the
# integration tests mount, rather than a duplicate that could drift.
FROM quay.io/keycloak/keycloak:26.4@sha256:9409c59bdfb65dbffa20b11e6f18b8abb9281d480c7ca402f51ed3d5977e6007

# A bind mount over this directory replaces the baked-in realm.
COPY robotics_integration_tests/custom_realms/robotics-realm.json /opt/keycloak/data/import/

# Already the base image's user; stated so Trivy sees it (DS-0002).
USER 1000

# Hostname configuration is left to the caller, whose issuer differs.
CMD ["start-dev", "--import-realm"]
