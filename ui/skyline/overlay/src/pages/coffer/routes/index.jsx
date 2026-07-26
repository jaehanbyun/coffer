// Licensed under the Apache License, Version 2.0.

import BaseLayout from 'layouts/Basic';
import E404 from 'pages/base/containers/404';
import RepositoryList from '../containers/Repository';
import RepositoryDetail from '../containers/Repository/Detail';

const PATH = '/registry';

export default [
  {
    path: PATH,
    component: BaseLayout,
    routes: [
      {
        path: `${PATH}/repository`,
        component: RepositoryList,
        exact: true,
      },
      {
        path: `${PATH}/repository/detail/:id`,
        component: RepositoryDetail,
        exact: true,
      },
      { path: '*', component: E404 },
    ],
  },
];
