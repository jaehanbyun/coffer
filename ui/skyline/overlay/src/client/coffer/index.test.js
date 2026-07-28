import { CofferClient } from './index';
import CofferRequestError from './errors';

const REPOSITORY_ID = '11111111-1111-4111-8111-111111111111';
const DIGEST = `sha256:${'a'.repeat(64)}`;

const artifact = (overrides = {}) => ({
  project_id: 'project-id',
  repository_id: REPOSITORY_ID,
  digest: DIGEST,
  media_type: 'application/vnd.oci.image.manifest.v1+json',
  artifact_type: 'application/vnd.oci.image.config.v1+json',
  kind: 'image',
  size_bytes: 4170,
  pushed_at: '2026-07-28T00:00:00Z',
  updated_at: '2026-07-28T00:01:00Z',
  tags: ['latest'],
  tag_count: 1,
  tags_truncated: false,
  ...overrides,
});

const mockRootStore = {
  endpoints: {
    coffer: '/api/openstack/regionone/coffer',
  },
};

jest.mock('stores/root', () => ({
  default: mockRootStore,
}));

const makeRequest = () => ({
  get: jest.fn(() => Promise.resolve({})),
  post: jest.fn(() => Promise.resolve({})),
  put: jest.fn(),
  delete: jest.fn(),
  patch: jest.fn(),
  head: jest.fn(),
  copy: jest.fn(),
});

describe('CofferClient', () => {
  let request;
  let client;

  beforeEach(() => {
    mockRootStore.endpoints.coffer = '/api/openstack/regionone/coffer';
    request = makeRequest();
    client = new CofferClient();
    Object.defineProperty(client, 'originRequest', {
      value: request,
    });
  });

  it('uses the mapped same-origin v1 endpoint', () => {
    expect(client.baseUrl).toBe('/api/openstack/regionone/coffer/v1');
  });

  it('does not synthesize a v1 endpoint when the catalog entry is absent', () => {
    delete mockRootStore.endpoints.coffer;
    expect(client.baseUrl).toBe('');
  });

  it('lists repositories with a bounded marker request', async () => {
    await client.repositories.list({ limit: 20, marker: 'repository-id' });
    expect(request.get).toHaveBeenCalledWith(
      '/api/openstack/regionone/coffer/v1/repositories',
      { limit: 20, marker: 'repository-id' },
      undefined
    );
  });

  it('shows one repository and sends an unwrapped create body', async () => {
    await client.repositories.show('repository-id');
    await client.repositories.create({
      name: 'team/application',
      immutable_tags: true,
    });
    expect(request.get).toHaveBeenCalledWith(
      '/api/openstack/regionone/coffer/v1/repositories/repository-id',
      undefined,
      undefined
    );
    expect(request.post).toHaveBeenCalledWith(
      '/api/openstack/regionone/coffer/v1/repositories',
      { name: 'team/application', immutable_tags: true },
      undefined,
      undefined
    );
  });

  it('reads quota without exposing a mutation operation', async () => {
    await client.quota();
    expect(request.get).toHaveBeenCalledWith(
      '/api/openstack/regionone/coffer/v1/quota',
      undefined,
      undefined
    );
    expect(client.repositories.delete).toBeUndefined();
    expect(client.repositories.update).toBeUndefined();
  });

  it('validates endpoint discovery and the artifact page contract', async () => {
    request.get
      .mockResolvedValueOnce({
        version: {
          id: 'v1',
          status: 'CURRENT',
          service_type: 'oci-registry',
          endpoints: {
            control: 'https://registry.example.test/v1',
            registry: 'https://registry.example.test/v2/',
            token: 'https://registry.example.test/auth/token',
          },
        },
      })
      .mockResolvedValueOnce({
        artifacts: [artifact()],
        next_marker: DIGEST,
      });

    const endpoint = await client.endpoint();
    const page = await client.artifacts.list(REPOSITORY_ID, {
      limit: 20,
      query: 'latest',
    });

    expect(endpoint.version.endpoints.registry).toBe(
      'https://registry.example.test/v2/'
    );
    expect(page.artifacts[0].tags).toEqual(['latest']);
    expect(request.get).toHaveBeenNthCalledWith(
      1,
      '/api/openstack/regionone/coffer/v1',
      undefined,
      undefined
    );
    expect(request.get).toHaveBeenNthCalledWith(
      2,
      `/api/openstack/regionone/coffer/v1/repositories/${REPOSITORY_ID}/artifacts`,
      { limit: 20, query: 'latest' },
      undefined
    );
  });

  it('shows one validated artifact without a mutation operation', async () => {
    request.get.mockResolvedValueOnce({ artifact: artifact() });

    const result = await client.artifacts.show(REPOSITORY_ID, DIGEST);

    expect(result.artifact.digest).toBe(DIGEST);
    expect(request.get).toHaveBeenCalledWith(
      `/api/openstack/regionone/coffer/v1/repositories/${REPOSITORY_ID}/artifacts/${DIGEST}`,
      undefined,
      undefined
    );
    expect(client.artifacts.create).toBeUndefined();
    expect(client.artifacts.update).toBeUndefined();
    expect(client.artifacts.delete).toBeUndefined();
  });

  it('fails closed when discovery crosses origins', async () => {
    request.get.mockResolvedValueOnce({
      version: {
        id: 'v1',
        status: 'CURRENT',
        service_type: 'oci-registry',
        endpoints: {
          control: 'https://registry.example.test/v1',
          registry: 'https://other.example.test/v2/',
          token: 'https://registry.example.test/auth/token',
        },
      },
    });

    await expect(client.endpoint()).rejects.toBeInstanceOf(CofferRequestError);
  });

  it.each([
    {
      artifacts: [
        artifact({
          repository_id: '22222222-2222-4222-8222-222222222222',
        }),
      ],
      next_marker: null,
    },
    {
      artifacts: [artifact({ digest: 'sha256:invalid' })],
      next_marker: null,
    },
    {
      artifacts: [artifact()],
      next_marker: `sha256:${'b'.repeat(64)}`,
    },
  ])('fails closed on malformed artifact pages', async (payload) => {
    request.get.mockResolvedValueOnce(payload);

    await expect(
      client.artifacts.list(REPOSITORY_ID, { limit: 20 })
    ).rejects.toBeInstanceOf(CofferRequestError);
  });

  it('fails before transport for unsafe artifact paths and queries', async () => {
    expect(() => client.artifacts.list('../repository', { limit: 20 })).toThrow(
      CofferRequestError
    );
    expect(() =>
      client.artifacts.list(REPOSITORY_ID, { query: ' leading' })
    ).toThrow(CofferRequestError);
    expect(() =>
      client.artifacts.show(REPOSITORY_ID, 'sha256:invalid')
    ).toThrow(CofferRequestError);
    expect(request.get).not.toHaveBeenCalled();
  });

  it.each([401, 403, 404, 409, 503])(
    'collapses HTTP %s failures without retaining remote data',
    async (status) => {
      request.get.mockRejectedValueOnce({
        response: {
          status,
          data: {
            description: 'remote detail',
          },
        },
      });
      let caught;
      try {
        await client.quota();
      } catch (error) {
        caught = error;
      }
      expect(caught).toBeInstanceOf(CofferRequestError);
      expect(caught.message).not.toContain('remote detail');
      expect(caught.response).toEqual({ status, data: '' });
    }
  );
});
