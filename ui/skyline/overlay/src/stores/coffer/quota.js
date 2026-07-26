// Licensed under the Apache License, Version 2.0.

import { action, observable } from 'mobx';
import client from 'client/coffer';

export class QuotaStore {
  @observable
  data = {};

  @observable
  isLoading = false;

  @action
  async fetch() {
    this.isLoading = true;
    try {
      const result = await client.quota();
      this.data = result.quota;
      return this.data;
    } finally {
      this.isLoading = false;
    }
  }
}

const globalQuotaStore = new QuotaStore();
export default globalQuotaStore;
