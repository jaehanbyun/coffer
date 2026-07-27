import client from 'client/coffer';
import { QuotaStore } from './quota';
import { RepositoryStore } from './repositories';

jest.mock('client/coffer', () => ({
  repositories: {
    responseKey: 'repository',
    list: jest.fn(),
    show: jest.fn(),
    create: jest.fn(() => Promise.resolve({})),
  },
  quota: jest.fn(),
}));

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
