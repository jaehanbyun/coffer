// Licensed under the Apache License, Version 2.0.

import { action } from 'mobx';
import Base from 'stores/base';
import client from 'client/coffer';

export class RepositoryStore extends Base {
  get client() {
    return client.repositories;
  }

  get needGetProject() {
    return false;
  }

  get paramsFuncPage() {
    return ({ current, ...params }) => params;
  }

  parseMarker(data, result) {
    return result.next_marker || '';
  }

  async getCountForPage(newParams, newData, allProjects, result, params) {
    const page = Number(params.current) || 1;
    const limit = Number(params.limit) || 10;
    const completed = (page - 1) * limit + newData.length;
    return {
      total: result.next_marker ? page * limit + 1 : completed,
    };
  }

  @action
  create(data) {
    return this.submitting(
      this.client.create({
        name: data.name,
        immutable_tags: Boolean(data.immutable_tags),
      })
    );
  }
}

const globalRepositoryStore = new RepositoryStore();
export default globalRepositoryStore;
