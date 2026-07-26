import { CofferClient } from './index';
import CofferRequestError from './errors';

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
