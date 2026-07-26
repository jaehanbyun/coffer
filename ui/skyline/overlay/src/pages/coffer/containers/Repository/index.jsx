// Licensed under the Apache License, Version 2.0.

import React from 'react';
import { inject, observer } from 'mobx-react';
import BaseList from 'containers/List';
import { cofferBase } from 'client/client/constants';
import globalRepositoryStore from 'stores/coffer/repositories';
import actionConfigs from './actions';
import QuotaSummary from './QuotaSummary';

export class RepositoryList extends BaseList {
  init() {
    this.store = globalRepositoryStore;
  }

  get name() {
    return t('Repositories');
  }

  get checkEndpoint() {
    return true;
  }

  get endpoint() {
    return cofferBase();
  }

  get isFilterByBackend() {
    return true;
  }

  get hideSearch() {
    return true;
  }

  get hideCustom() {
    return true;
  }

  get hideDownload() {
    return true;
  }

  get tableTopHeight() {
    return super.tableTopHeight + 104;
  }

  get actionConfigs() {
    return actionConfigs;
  }

  getColumns() {
    return [
      {
        title: t('Name'),
        dataIndex: 'name',
        routeName: this.getRouteName('cofferRepositoryDetail'),
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

  renderHeader() {
    return (
      <div style={{ margin: '0 0 16px' }}>
        <QuotaSummary />
      </div>
    );
  }
}

export default inject('rootStore')(observer(RepositoryList));
