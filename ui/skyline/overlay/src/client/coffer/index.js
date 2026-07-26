// Licensed under the Apache License, Version 2.0.

import Base from '../client/base';
import { cofferBase } from '../client/constants';
import CofferRequestError from './errors';

export class CofferClient extends Base {
  constructor() {
    super();
    this.repositories = {
      responseKey: 'repository',
      list: (params) => this.safe(this.request.get('repositories', params)),
      show: (id) => this.safe(this.request.get(`repositories/${id}`)),
      create: (data) => this.safe(this.request.post('repositories', data)),
    };
  }

  get baseUrl() {
    return cofferBase();
  }

  get resources() {
    return [];
  }

  safe = (request) =>
    request.catch((error) => {
      const status = error && error.response && error.response.status;
      throw new CofferRequestError(status);
    });

  quota = () => this.safe(this.request.get('quota'));
}

const cofferClient = new CofferClient();
export default cofferClient;
