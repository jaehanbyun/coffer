// Licensed under the Apache License, Version 2.0.

import Base from '../client/base';
import { cofferBase } from '../client/constants';

export class CofferClient extends Base {
  constructor() {
    super();
    this.repositories = {
      responseKey: 'repository',
      list: (params) => this.request.get('repositories', params),
      show: (id) => this.request.get(`repositories/${id}`),
      create: (data) => this.request.post('repositories', data),
    };
  }

  get baseUrl() {
    return cofferBase();
  }

  get resources() {
    return [];
  }

  quota = () => this.request.get('quota');
}

const cofferClient = new CofferClient();
export default cofferClient;
