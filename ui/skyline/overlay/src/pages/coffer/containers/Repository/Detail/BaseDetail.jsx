// Licensed under the Apache License, Version 2.0.

import { inject, observer } from 'mobx-react';
import Base from 'containers/BaseDetail';

export class RepositoryBaseDetail extends Base {
  get leftCards() {
    return [this.identityCard];
  }

  get identityCard() {
    return {
      title: t('Registry Identity'),
      options: [
        {
          label: t('Repository ID'),
          dataIndex: 'id',
        },
        {
          label: t('Project ID'),
          dataIndex: 'project_id',
        },
        {
          label: t('Repository Name'),
          dataIndex: 'name',
        },
      ],
    };
  }
}

export default inject('rootStore')(observer(RepositoryBaseDetail));
