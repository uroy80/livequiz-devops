# Jenkins controller for the LiveQuiz major project: every tool the pipeline needs is baked in.
FROM docker:29.9.3-cli AS dockercli
FROM docker/buildx-bin:latest AS buildx
FROM aquasec/trivy:0.76.2 AS trivy

FROM jenkins/jenkins:2.580.2-lts-jdk21
USER root
ARG TARGETARCH
ARG TERRAFORM_VERSION=1.17.1
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv python3-pip curl jq unzip openssh-client \
 && rm -rf /var/lib/apt/lists/* \
 && ARCH=$([ "$TARGETARCH" = arm64 ] && echo aarch64 || echo x86_64) \
 && curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${ARCH}.zip" -o /tmp/awscli.zip \
 && unzip -q /tmp/awscli.zip -d /tmp && /tmp/aws/install && rm -rf /tmp/aws /tmp/awscli.zip \
 && curl -fsSL "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${TARGETARCH}.zip" -o /tmp/tf.zip \
 && unzip -q /tmp/tf.zip terraform -d /usr/local/bin && rm /tmp/tf.zip \
 && python3 -m venv /opt/ansible && /opt/ansible/bin/pip install --no-cache-dir ansible-core==2.21.5 \
 && ln -s /opt/ansible/bin/ansible* /usr/local/bin/ \
 && git config --system safe.directory '*'
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=buildx    /buildx               /usr/local/libexec/docker/cli-plugins/docker-buildx
COPY --from=trivy     /usr/local/bin/trivy  /usr/local/bin/trivy
USER jenkins
COPY --chown=jenkins:jenkins plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt
COPY --chown=jenkins:jenkins casc.yaml jobs.groovy /var/jenkins_conf/
ENV CASC_JENKINS_CONFIG=/var/jenkins_conf/casc.yaml \
    JAVA_OPTS="-Djenkins.install.runSetupWizard=false"
