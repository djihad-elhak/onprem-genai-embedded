# Jenkins controller for the platform's CI: Jenkins LTS + the official MCP Server plugin + the F´ unit-test
# toolchain. Internet is needed at build time only (plugins, pip); the running controller works offline.
ARG JENKINS_IMAGE=jenkins/jenkins:2.568.3-jdk21
FROM ${JENKINS_IMAGE}

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    # the F´ repository is bind-mounted read-only and owned by the host user
    && git config --system --add safe.directory '*'
# F´ build tools, pinned to the versions F´ v4.4.1 requires (build tools only, no ground system)
RUN python3 -m venv /opt/fprime-tools \
    && /opt/fprime-tools/bin/pip install --no-cache-dir \
        "fprime-tools==4.4.0" "fprime-fpp==3.4.0" "cmake==3.26.0" "ninja==1.11.1.4"
ENV PATH="/opt/fprime-tools/bin:${PATH}"

USER jenkins
COPY --chown=jenkins:jenkins plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt
COPY --chown=jenkins:jenkins casc.yaml /usr/share/jenkins/ref/casc.yaml
COPY --chown=jenkins:jenkins fprime-unit-tests.Jenkinsfile /usr/share/jenkins/ref/fprime-unit-tests.Jenkinsfile
COPY --chown=jenkins:jenkins init.groovy.d/ /usr/share/jenkins/ref/init.groovy.d/
ENV CASC_JENKINS_CONFIG=/usr/share/jenkins/ref/casc.yaml \
    JAVA_OPTS="-Djenkins.install.runSetupWizard=false"
