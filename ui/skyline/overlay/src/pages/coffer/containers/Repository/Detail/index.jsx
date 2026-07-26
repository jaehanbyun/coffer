// Licensed under the Apache License, Version 2.0.

import { inject, observer } from 'mobx-react';
import Base from 'containers/TabDetail';
import { RepositoryStore } from 'stores/coffer/repositories';
import BaseDetail from './BaseDetail';

export class RepositoryDetail extends Base {
  init() {
    this.store = new RepositoryStore();
  }

  get name() {
    return t('Repository Detail');
  }

  get listUrl() {
    return this.getRoutePath('cofferRepository');
  }

  get detailInfos() {
    return [
      {
        title: t('ID'),
        dataIndex: 'id',
      },
      {
        title: t('Name'),
        dataIndex: 'name',
      },
      {
        title: t('Immutable Tags'),
        dataIndex: 'immutable_tags',
        valueRender: 'yesNo',
      },
      {
        title: t('Created At'),
        dataIndex: 'created_at',
        valueRender: 'toLocalTime',
      },
    ];
  }

  get tabs() {
    return [
      {
        title: t('Detail Info'),
        key: 'detail_info',
        component: BaseDetail,
      },
    ];
  }
}

export default inject('rootStore')(observer(RepositoryDetail));
