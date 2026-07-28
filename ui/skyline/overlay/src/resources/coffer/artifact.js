// Licensed under the Apache License, Version 2.0.

import { validateRepositoryName } from './repository';

const PROJECT_ID = /^[A-Za-z0-9_-]{1,64}$/;

export const registryHost = (registryEndpoint) => {
  let parsed;
  try {
    parsed = new URL(registryEndpoint);
  } catch {
    return '';
  }
  if (
    parsed.protocol !== 'https:' ||
    parsed.pathname !== '/v2/' ||
    parsed.username ||
    parsed.password ||
    parsed.search ||
    parsed.hash
  ) {
    return '';
  }
  return parsed.host;
};

export const repositoryReference = (endpoints, repository) => {
  const host = registryHost(endpoints?.registry);
  const { project_id: projectId, name } = repository || {};
  if (
    !host ||
    typeof projectId !== 'string' ||
    !PROJECT_ID.test(projectId) ||
    !validateRepositoryName(name)
  ) {
    return '';
  }
  return `${host}/p/${projectId}/${name}`;
};

export const artifactReference = (baseReference, artifact) => {
  if (!baseReference || !artifact) {
    return '';
  }
  const [tag] = artifact.tags || [];
  return tag
    ? `${baseReference}:${tag}`
    : `${baseReference}@${artifact.digest}`;
};

export const artifactType = (kind) =>
  ({
    image: t('Container Image'),
    image_index: t('Multi-platform Image'),
    artifact: t('OCI Artifact'),
  }[kind] || t('OCI Artifact'));

export const connectionCommands = (baseReference) => ({
  docker: `export OS_APPLICATION_CREDENTIAL_ID="<finite-application-credential-id>"
openstack registry login --client docker \\
  --application-credential-id "$OS_APPLICATION_CREDENTIAL_ID"
docker pull hello-world
docker tag hello-world "${baseReference}:latest"
docker push "${baseReference}:latest"`,
  podman: `export OS_APPLICATION_CREDENTIAL_ID="<finite-application-credential-id>"
openstack registry login --client podman \\
  --application-credential-id "$OS_APPLICATION_CREDENTIAL_ID"
podman pull docker.io/library/hello-world:latest
podman tag docker.io/library/hello-world:latest "${baseReference}:latest"
podman push "${baseReference}:latest"`,
  helm: `export OS_APPLICATION_CREDENTIAL_ID="<finite-application-credential-id>"
openstack registry login --client docker \\
  --application-credential-id "$OS_APPLICATION_CREDENTIAL_ID"
helm package ./chart
helm push ./chart-0.1.0.tgz "oci://${baseReference}"`,
  oras: `export OS_APPLICATION_CREDENTIAL_ID="<finite-application-credential-id>"
openstack registry login --client oras \\
  --application-credential-id "$OS_APPLICATION_CREDENTIAL_ID"
oras push "${baseReference}:example" \\
  ./artifact.txt:application/octet-stream`,
});
