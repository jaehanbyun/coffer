import {
  artifactReference,
  artifactType,
  connectionCommands,
  registryHost,
  repositoryReference,
} from './artifact';

describe('Coffer artifact presentation', () => {
  const endpoints = {
    registry: 'https://registry.example.test:18788/v2/',
  };
  const repository = {
    id: '11111111-1111-4111-8111-111111111111',
    project_id: 'project-id',
    name: 'team/application',
  };

  beforeEach(() => {
    t.mockImplementation((value) => value);
  });

  it('builds a safe OCI namespace from discovery and project scope', () => {
    expect(registryHost(endpoints.registry)).toBe(
      'registry.example.test:18788'
    );
    expect(repositoryReference(endpoints, repository)).toBe(
      'registry.example.test:18788/p/project-id/team/application'
    );
    expect(
      repositoryReference(endpoints, {
        ...repository,
        project_id: '$(unsafe)',
      })
    ).toBe('');
    expect(registryHost('https://user@registry.example.test:18788/v2/')).toBe(
      ''
    );
  });

  it('prefers a tag and falls back to an immutable digest reference', () => {
    const base = repositoryReference(endpoints, repository);
    const digest = `sha256:${'a'.repeat(64)}`;
    expect(artifactReference(base, { digest, tags: ['latest'] })).toBe(
      `${base}:latest`
    );
    expect(artifactReference(base, { digest, tags: [] })).toBe(
      `${base}@${digest}`
    );
  });

  it('generates four credential-safe client guides', () => {
    const base = repositoryReference(endpoints, repository);
    const commands = connectionCommands(base);

    expect(Object.keys(commands).sort()).toEqual([
      'docker',
      'helm',
      'oras',
      'podman',
    ]);
    expect(commands.docker).toContain(
      'openstack registry login --client docker'
    );
    expect(commands.helm).toContain('openstack registry login --client helm');
    expect(commands.helm).toContain('helm create "application"');
    expect(commands.helm).toContain(
      '"oci://registry.example.test:18788/p/project-id/team"'
    );
    expect(commands.oras).toContain(`${base}:example`);
    expect(JSON.stringify(commands)).not.toContain('OS_PASSWORD');
    expect(JSON.stringify(commands)).not.toContain(
      'OS_APPLICATION_CREDENTIAL_SECRET'
    );
  });

  it('renders stable human-facing artifact types', () => {
    expect(artifactType('image')).toBe('Container Image');
    expect(artifactType('image_index')).toBe('Multi-platform Image');
    expect(artifactType('artifact')).toBe('OCI Artifact');
  });
});
