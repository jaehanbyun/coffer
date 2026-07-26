import renderMenu from 'layouts/menu';
import routes from './routes';

jest.mock('layouts/Basic', () => () => null);
jest.mock('pages/base/containers/404', () => () => null);
jest.mock('./containers/Repository', () => () => null);
jest.mock('./containers/Repository/Detail', () => () => null);

describe('Coffer Skyline integration', () => {
  it('registers the repository list and UUID detail routes', () => {
    const root = routes[0];
    expect(root.path).toBe('/registry');
    expect(root.routes).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          path: '/registry/repository',
          exact: true,
        }),
        expect.objectContaining({
          path: '/registry/repository/detail/:id',
          exact: true,
        }),
      ])
    );
  });

  it('gates the Registry menu on the mapped Coffer endpoint', () => {
    const menu = renderMenu((value) => value);
    const registry = menu.find((item) => item.key === 'cofferRegistry');
    expect(registry).toEqual(
      expect.objectContaining({
        path: '/registry',
        endpoints: 'coffer',
      })
    );
    expect(registry.children[0]).toEqual(
      expect.objectContaining({
        path: '/registry/repository',
        key: 'cofferRepository',
      })
    );
    expect(registry.children[0].children[0].routePath).toBe(
      '/registry/repository/detail/:id'
    );
  });
});
