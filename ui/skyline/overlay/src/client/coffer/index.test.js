import { CofferClient } from './index';

jest.mock('stores/root', () => ({
  default: {
    endpoints: {
      coffer: '/api/openstack/regionone/coffer',
    },
  },
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
    request = makeRequest();
    client = new CofferClient();
    Object.defineProperty(client, 'originRequest', {
      value: request,
    });
  });

  it('uses the mapped same-origin v1 endpoint', () => {
    expect(client.baseUrl).toBe('/api/openstack/regionone/coffer/v1');
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
});
