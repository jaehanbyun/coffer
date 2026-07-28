import client from 'client/coffer';
import { ArtifactStore } from './artifacts';
import { QuotaStore } from './quota';
import { RepositoryStore } from './repositories';

jest.mock('client/coffer', () => ({
  artifacts: {
    list: jest.fn(),
    show: jest.fn(),
  },
  endpoint: jest.fn(),
  repositories: {
    responseKey: 'repository',
    list: jest.fn(),
    show: jest.fn(),
    create: jest.fn(() => Promise.resolve({})),
  },
  quota: jest.fn(),
}));

describe('ArtifactStore', () => {
  const repositoryId = '11111111-1111-4111-8111-111111111111';
  const digest = `sha256:${'a'.repeat(64)}`;

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('retains only the validated artifact page and continuation marker', async () => {
    const item = { digest, tags: ['latest'] };
    client.artifacts.list.mockResolvedValueOnce({
      artifacts: [item],
      next_marker: digest,
    });
    const store = new ArtifactStore();

    await expect(
      store.fetch(repositoryId, { limit: 20, query: 'latest' })
    ).resolves.toEqual({
      artifacts: [item],
      next_marker: digest,
    });

    expect(client.artifacts.list).toHaveBeenCalledWith(repositoryId, {
      limit: 20,
      query: 'latest',
    });
    expect(store.items).toEqual([item]);
    expect(store.nextMarker).toBe(digest);
    expect(store.errorStatus).toBe(0);
    expect(store.isLoading).toBe(false);
  });

  it('retains only bounded failure state when artifact loading fails', async () => {
    const failure = new Error('remote detail');
    failure.response = { status: 403, data: '' };
    client.artifacts.list.mockRejectedValueOnce(failure);
    const store = new ArtifactStore();

    await expect(store.fetch(repositoryId, { limit: 20 })).rejects.toThrow(
      'remote detail'
    );

    expect(store.items).toEqual([]);
    expect(store.nextMarker).toBeNull();
    expect(store.errorStatus).toBe(403);
    expect(store.isLoading).toBe(false);
  });

  it('retains only the validated public endpoint values', async () => {
    const endpoints = {
      control: 'control',
      registry: 'registry',
      token: 'token',
    };
    client.endpoint.mockResolvedValueOnce({
      version: { endpoints },
    });
    const store = new ArtifactStore();

    await expect(store.fetchEndpoint()).resolves.toEqual(endpoints);

    expect(store.endpoint).toEqual(endpoints);
    expect(store.endpointErrorStatus).toBe(0);
    expect(store.isEndpointLoading).toBe(false);
  });
});

describe('RepositoryStore', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('uses only the server continuation marker', () => {
    const store = new RepositoryStore();
    expect(store.listResponseKey).toBe('repositories');
    expect(
      store.parseMarker([{ id: 'last-row' }], {
        next_marker: 'server-marker',
      })
    ).toBe('server-marker');
    expect(store.parseMarker([{ id: 'last-row' }], { next_marker: null })).toBe(
      ''
    );
  });

  it('reports one synthetic row only when a forward page exists', async () => {
    const store = new RepositoryStore();
    await expect(
      store.getCountForPage(
        {},
        new Array(10),
        false,
        {
          next_marker: 'next',
        },
        {
          current: 2,
          limit: 10,
        }
      )
    ).resolves.toEqual({ total: 21 });
    await expect(
      store.getCountForPage(
        {},
        new Array(3),
        false,
        {
          next_marker: null,
        },
        {
          current: 2,
          limit: 10,
        }
      )
    ).resolves.toEqual({ total: 13 });
  });

  it('sends the public create body without a response envelope', async () => {
    const store = new RepositoryStore();
    await store.create({ name: 'team/application', immutable_tags: 1 });
    expect(client.repositories.create).toHaveBeenCalledWith({
      name: 'team/application',
      immutable_tags: true,
    });
  });
});

describe('QuotaStore', () => {
  it('retains only the quota envelope value', async () => {
    client.quota.mockResolvedValueOnce({
      quota: {
        project_id: 'project-id',
        limit_bytes: 100,
        used_bytes: 25,
        reserved_bytes: 5,
      },
    });
    const store = new QuotaStore();
    await expect(store.fetch()).resolves.toEqual({
      project_id: 'project-id',
      limit_bytes: 100,
      used_bytes: 25,
      reserved_bytes: 5,
    });
    expect(store.isLoading).toBe(false);
  });

  it('clears loading state without logging or rewriting a failure', async () => {
    client.quota.mockRejectedValueOnce(new Error('remote detail'));
    const store = new QuotaStore();
    await expect(store.fetch()).rejects.toThrow('remote detail');
    expect(store.isLoading).toBe(false);
  });
});
